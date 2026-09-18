"""座位表的规则：随机排位、整体轮换、交换、以及一次回退。

这一块的算法全部在服务端，而且每个批量操作都**先存一张快照**再改 ——
旧应用的 `shuffleSeats`（`:10684`）与 `shiftSeats`（`:10644`）都是直接整体替换
`DB.data.seats`，做错了没有任何退路（`:10704`）。

三个刻意的行为（都是对旧应用的修正）：

1. **随机排位保留备注与锁定座位**。旧应用填空格时强制 `note:''`（`:10700`），
   视力/身高的备注全丢；这里备注跟着学生走，`locked` 的座位连人带位置都不动。
2. **座位不够时自动加排，并如实报出来**（旧应用会悄悄把 `seatPlan.rows` 撑大）。
3. **每次批量操作前存一张快照，支持回退一次**（`POST /seats/restore`）。
"""

from __future__ import annotations

import random
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, NOT_FOUND, SEAT_STUDENT_ALREADY_SEATED, SEAT_TAKEN, ApiError
from app.models.app_state import AppState
from app.models.seat import DEFAULT_COLS, DEFAULT_RULE, DEFAULT_ROWS, MAX_COLS, MAX_ROWS, Seat, SeatPlan
from app.models.student import Student
from app.services.params import as_int

SNAPSHOT_KEY = "seat_snapshot"


# ---------------------------------------------------------------- 座位表参数


def get_plan(session: Session, class_id: int) -> SeatPlan:
    plan = session.get(SeatPlan, class_id)
    if plan is None:
        plan = SeatPlan(class_id=class_id)
        session.add(plan)
        session.flush()
    return plan


def set_plan(
    session: Session, class_id: int, rows: Any, cols: Any, rule: Any = None
) -> SeatPlan:
    """改行列数。**缩小之前先看现有座位** —— 被挪到网格外的座位会变成「看不见但还在」。"""
    plan = get_plan(session, class_id)
    new_rows = as_int(rows, "排数")
    new_cols = as_int(cols, "列数")
    if not 1 <= new_rows <= MAX_ROWS:
        raise ApiError(INVALID_VALUE, f"排数要在 1–{MAX_ROWS} 之间", detail={"field": "rows"})
    if not 1 <= new_cols <= MAX_COLS:
        raise ApiError(INVALID_VALUE, f"列数要在 1–{MAX_COLS} 之间", detail={"field": "cols"})

    outside = session.scalars(
        select(Seat).where(
            Seat.deleted_at.is_(None),
            Seat.class_id == class_id,
            (Seat.row > new_rows) | (Seat.col > new_cols),
        )
    ).all()
    if outside:
        seated = [seat for seat in outside if seat.student_id is not None]
        detail = "、".join(f"{seat.position} {seat.student_name or '（空）'}" for seat in outside[:6])
        raise ApiError(
            INVALID_VALUE,
            f"缩小之后有 {len(outside)} 个座位落到格子外面（{detail}）"
            + (f"，其中 {len(seated)} 个坐着人。" if seated else "。")
            + "请先把这些座位腾空或删掉。",
            detail={"field": "rows", "outside": len(outside), "withStudent": len(seated)},
        )

    plan.rows = new_rows
    plan.cols = new_cols
    if rule is not None:
        plan.rule = str(rule)
    session.flush()
    return plan


# ---------------------------------------------------------------- 快照


def _save_snapshot(session: Session, class_id: int) -> None:
    """存一张「现在的座位表」，供回退一次用。只保留最近一张（旧覆盖新）。"""
    seats = session.scalars(
        select(Seat).where(Seat.class_id == class_id, Seat.deleted_at.is_(None)).order_by(Seat.row, Seat.col)
    ).all()
    payload = [
        {
            "row": seat.row,
            "col": seat.col,
            "student_id": seat.student_id,
            "student_name": seat.student_name,
            "note": seat.note,
            "locked": seat.locked,
        }
        for seat in seats
    ]
    key = f"{SNAPSHOT_KEY}:{class_id}"
    row = session.get(AppState, key)
    if row is None:
        session.add(AppState(key=key, value=payload))
    else:
        row.value = payload
    session.flush()


def snapshot_exists(session: Session, class_id: int) -> bool:
    row = session.get(AppState, f"{SNAPSHOT_KEY}:{class_id}")
    return bool(row and row.value)


def restore(session: Session, class_id: int) -> dict[str, Any]:
    """回退到上一次批量操作之前。只能回一次（旧应用的批量操作没有任何撤销）。"""
    row = session.get(AppState, f"{SNAPSHOT_KEY}:{class_id}")
    if row is None or not row.value:
        raise ApiError(
            NOT_FOUND,
            "没有可回退的快照。回退只保留上一次批量操作之前的状态。",
            status=404,
        )

    session.execute(delete(Seat).where(Seat.class_id == class_id))
    restored = 0
    for item in row.value:
        session.add(
            Seat(
                class_id=class_id,
                row=item["row"],
                col=item["col"],
                student_id=item.get("student_id"),
                student_name=item.get("student_name", ""),
                note=item.get("note", ""),
                locked=bool(item.get("locked")),
            )
        )
        restored += 1
    session.delete(row)  # 回退一次就用掉，免得连点两次往回退到更早的状态
    session.flush()
    return {"restored": restored}


# ---------------------------------------------------------------- 排位


def _roster(session: Session, class_id: int) -> list[Student]:
    return list(
        session.scalars(
            select(Student)
            .where(Student.deleted_at.is_(None), Student.class_id == class_id)
            .order_by(Student.sno, Student.name, Student.id)
        )
    )


def _cells(rows: int, cols: int) -> list[tuple[int, int]]:
    """行优先的格子顺序 —— 与旧应用一致（先坐满第 1 排）。"""
    return [(row, col) for row in range(1, rows + 1) for col in range(1, cols + 1)]


def randomize(session: Session, class_id: int, *, seed: int | None = None) -> dict[str, Any]:
    """一键随机排位。

    - `locked` 的座位连人带位置都不动（旧应用没有这个概念，想保留的安排挡不住）；
    - 备注**跟着学生走**（旧应用填空格时强制 `note=''`，视力/身高信息全丢）；
    - 座位不够时自动加排，并如实报出来。
    """
    plan = get_plan(session, class_id)
    _save_snapshot(session, class_id)

    existing = session.scalars(
        select(Seat).where(Seat.class_id == class_id, Seat.deleted_at.is_(None))
    ).all()
    notes = {seat.student_id: seat.note for seat in existing if seat.student_id and seat.note}
    locked = [seat for seat in existing if seat.locked]
    locked_ids = {seat.student_id for seat in locked if seat.student_id}
    locked_cells = {(seat.row, seat.col) for seat in locked}

    pool = [student for student in _roster(session, class_id) if student.id not in locked_ids]
    if not pool:
        raise ApiError(INVALID_VALUE, "班里还没有学生，先到「学生档案」里加人")

    rows, cols = plan.rows, plan.cols
    free = [cell for cell in _cells(rows, cols) if cell not in locked_cells]
    added_rows = 0
    while len(free) < len(pool) and rows < MAX_ROWS:
        rows += 1
        added_rows += 1
        free = [cell for cell in _cells(rows, cols) if cell not in locked_cells]
    if len(free) < len(pool):
        raise ApiError(
            INVALID_VALUE,
            f"座位不够：{len(pool)} 个学生，最多只能排 {len(free)} 个（{MAX_ROWS} 排 × {cols} 列）。"
            "请先加列，或把学生分批安排。",
            detail={"students": len(pool), "cells": len(free)},
        )

    plan.rows = rows
    session.execute(delete(Seat).where(Seat.class_id == class_id))
    shuffler = random.Random(seed)
    shuffler.shuffle(pool)

    for seat in locked:
        session.add(
            Seat(
                class_id=class_id,
                row=seat.row,
                col=seat.col,
                student_id=seat.student_id,
                student_name=seat.student_name,
                note=seat.note,
                locked=True,
            )
        )

    for student, (row, col) in zip(pool, free):
        session.add(
            Seat(
                class_id=class_id,
                row=row,
                col=col,
                student_id=student.id,
                student_name=student.name,
                note=notes.get(student.id, ""),  # 备注跟人走，不再被清空
            )
        )
    session.flush()
    return {
        # 这里叫 `placed` 而不是 `seated`：接口会把结果与看板合并返回，
        # 而看板的 `seated` 是「一共坐着几个」（含锁定的那些），语义不同不能撞名
        "placed": len(pool),
        "locked": len(locked),
        "addedRows": added_rows,
        "rows": rows,
        "cols": cols,
    }


# 轮换方向：上下左右，越界回绕
SHIFT_DIRECTIONS = ("up", "down", "left", "right")


def shift(session: Session, class_id: int, direction: str, step: Any = 1) -> dict[str, Any]:
    """整体环移（每月换座）。锁定座位不动，其余按方向平移、越界回绕。

    第 1 排在最前面，所以「往前」= 行号变小。
    """
    if direction not in SHIFT_DIRECTIONS:
        raise ApiError(
            INVALID_VALUE,
            f"方向只能是 {'、'.join(SHIFT_DIRECTIONS)}",
            detail={"field": "direction"},
        )
    offset = as_int(step, "步长")
    if not 1 <= offset <= max(MAX_ROWS, MAX_COLS):
        raise ApiError(INVALID_VALUE, "步长太大了", detail={"field": "step"})

    plan = get_plan(session, class_id)
    seats = session.scalars(
        select(Seat).where(Seat.class_id == class_id, Seat.deleted_at.is_(None))
    ).all()
    if not seats:
        raise ApiError(INVALID_VALUE, "还没有排座位，先一键随机排位或手工添加")

    _save_snapshot(session, class_id)
    locked_cells = {(seat.row, seat.col) for seat in seats if seat.locked}
    movers = [seat for seat in seats if not seat.locked]

    # 轮换只在**非锁定格子之间**做循环置换。
    #
    # 不能简单地整行取模：锁定座位占着某个格子，整行平移会有人被转到它那一格上。
    # 而「转得进去的格子」是确定的：每列（或每行）里去掉锁定格子剩下的位置。
    #
    # 算法上还必须**先算好位置、再删掉重建**：置换没法逐行 UPDATE ——
    # 把 A 挪到 B 的位置时 B 还没挪走，途中必然撞上 UNIQUE(class_id,row,col)
    # （实测 500；单测里只有一个座位时看不出这个问题）。
    # 默认位置是「原地」：**每个 mover 都必须有一条去处**，否则删掉重建时会丢人
    # （只剩一个空格子的那一列就是这种情况）。
    states: dict[int, tuple] = {
        seat.id: (seat.student_id, seat.student_name, seat.note, seat.locked) for seat in movers
    }
    target: dict[int, tuple[int, int]] = {seat.id: (seat.row, seat.col) for seat in movers}

    if direction in ("up", "down"):
        delta = -offset if direction == "up" else offset
        for col in range(1, plan.cols + 1):
            free = [row for row in range(1, plan.rows + 1) if (row, col) not in locked_cells]
            moving = [seat for seat in movers if seat.col == col]
            if len(free) < 2 or not moving:
                continue
            index = {row: position for position, row in enumerate(free)}
            for seat in moving:
                target[seat.id] = (free[(index[seat.row] + delta) % len(free)], col)
    else:
        delta = -offset if direction == "left" else offset
        for row in range(1, plan.rows + 1):
            free = [col for col in range(1, plan.cols + 1) if (row, col) not in locked_cells]
            moving = [seat for seat in movers if seat.row == row]
            if len(free) < 2 or not moving:
                continue
            index = {col: position for position, col in enumerate(free)}
            for seat in moving:
                target[seat.id] = (row, free[(index[seat.col] + delta) % len(free)])

    moved = sum(1 for seat in movers if target[seat.id] != (seat.row, seat.col))
    for seat in movers:
        session.delete(seat)
    session.flush()
    for seat_id, (row, col) in target.items():
        state = states[seat_id]
        session.add(
            Seat(
                class_id=class_id,
                row=row,
                col=col,
                student_id=state[0],
                student_name=state[1],
                note=state[2],
                locked=state[3],
            )
        )
    session.flush()
    return {"moved": moved, "direction": direction, "step": offset}


def swap(session: Session, class_id: int, seat_id: int, target_row: int, target_col: int) -> dict[str, Any]:
    """把某个座位挪到（或与）目标格交换 —— 拖拽/点选交换走这一个实现。

    旧应用的 `seatDrop`（`:10716`）与手工编辑各自处理行列，后写覆盖造出过
    「网格里看不见、列表里还在」的重复格。这里位置唯一约束 + 一次事务。
    """
    source = session.get(Seat, seat_id)
    if source is None or source.class_id != class_id or source.deleted_at is not None:
        raise ApiError(NOT_FOUND, "这个座位不存在，可能已被删除", status=404, detail={"seatId": seat_id})

    plan = get_plan(session, class_id)
    if not (1 <= target_row <= plan.rows and 1 <= target_col <= plan.cols):
        raise ApiError(
            INVALID_VALUE,
            f"目标格（{target_row} 排 {target_col} 列）在座位表外面",
            detail={"rows": plan.rows, "cols": plan.cols},
        )
    if source.row == target_row and source.col == target_col:
        return {"moved": 0, "swapped": False}

    target = session.scalars(
        select(Seat).where(
            Seat.class_id == class_id,
            Seat.deleted_at.is_(None),
            Seat.row == target_row,
            Seat.col == target_col,
        )
    ).first()

    _save_snapshot(session, class_id)
    if target is None:
        source.row, source.col = target_row, target_col
        session.flush()
        return {"moved": 1, "swapped": False}

    # 目标已有人：换位置。**备注跟着人走**（旧应用的拖拽也是这个语义）。
    # 同一对行互换时不能直接互相赋值 —— 第一条 UPDATE 就会撞上
    # `UNIQUE(class_id,row,col)`（此刻两个格子还都有人）。所以先删掉这两条，
    # 再按换过来的位置重建。座位没有外部引用，换 id 没关系。
    # 取值必须在删除**之前**做完：删除并 flush 之后再读已删实例的属性不可靠
    source_place = (source.row, source.col)
    target_place = (target.row, target.col)
    source_state = (source.student_id, source.student_name, source.note, source.locked)
    target_state = (target.student_id, target.student_name, target.note, target.locked)

    session.delete(source)
    session.delete(target)
    session.flush()
    for state, place in ((source_state, target_place), (target_state, source_place)):
        session.add(
            Seat(
                class_id=class_id,
                row=place[0],
                col=place[1],
                student_id=state[0],
                student_name=state[1],
                note=state[2],
                locked=state[3],
            )
        )
    session.flush()
    return {"moved": 1, "swapped": True}


def apply_seat(values: dict[str, Any], session: Session, row: Any = None) -> None:
    """座位的保存前钩子：位置合法、格子不重复、一个学生只坐一处。

    这是「手工新增/编辑不校验行列冲突」（旧应用 `:10792` 后写覆盖）的修复点。
    """
    class_id = values.get("class_id") or (getattr(row, "class_id", None) if row else None)
    if not class_id:
        raise ApiError(INVALID_VALUE, "缺少班级，无法确定这个座位属于哪个班")

    plan = get_plan(session, class_id)
    seat_row = as_int(values.get("row", getattr(row, "row", None)), "排")
    seat_col = as_int(values.get("col", getattr(row, "col", None)), "列")
    if not 1 <= seat_row <= plan.rows or not 1 <= seat_col <= plan.cols:
        raise ApiError(
            INVALID_VALUE,
            f"位置超出座位表：当前是 {plan.rows} 排 × {plan.cols} 列，"
            f"填的是 {seat_row} 排 {seat_col} 列。要更多格子请先改座位表大小。",
            detail={"field": "row", "rows": plan.rows, "cols": plan.cols},
        )
    values["row"], values["col"] = seat_row, seat_col

    self_id = row.id if row is not None and row.id else 0
    clash = session.scalars(
        select(Seat).where(
            Seat.class_id == class_id,
            Seat.deleted_at.is_(None),
            Seat.row == seat_row,
            Seat.col == seat_col,
            Seat.id != self_id,
        )
    ).first()
    if clash is not None:
        raise ApiError(
            SEAT_TAKEN,
            f"{seat_row} 排 {seat_col} 列已经有座位了"
            + (f"（{clash.student_name}）" if clash.student_name else "（空座）")
            + "。请换一个格子，或先改那一格。",
            detail={"field": "col", "seatId": clash.id},
        )

    student = _resolve_student(session, values, row, class_id)
    if student is not None:
        other = session.scalars(
            select(Seat).where(
                Seat.class_id == class_id,
                Seat.deleted_at.is_(None),
                Seat.student_id == student.id,
                Seat.id != self_id,
            )
        ).first()
        if other is not None:
            raise ApiError(
                SEAT_STUDENT_ALREADY_SEATED,
                f"{student.name} 已经坐在 {other.position} 了。要挪位置请改那一条，"
                "或用座位表上的拖拽/点选交换。",
                detail={"field": "student_name", "seatId": other.id},
            )
        values["student_id"] = student.id
        values["student_name"] = student.name


def _resolve_student(
    session: Session, values: dict[str, Any], row: Any, class_id: int
) -> Student | None:
    """按姓名或学号找学生；都不给就是空座（空座可以有记录，只是没人坐）。"""
    name = str(values.get("student_name") or "").strip()
    sno = str(values.get("sno") or "").strip()
    provided = "student_name" in values or "sno" in values
    if not name and not sno:
        if row is not None and provided:
            values["student_id"] = None
            values["student_name"] = ""
        return None

    query = select(Student).where(Student.deleted_at.is_(None), Student.class_id == class_id)
    query = query.where(Student.name == name) if name else query.where(Student.sno == sno)
    matches = list(session.scalars(query))
    if not matches:
        who = f"叫「{name}」的学生" if name else f"学号是「{sno}」的学生"
        raise ApiError(INVALID_VALUE, f"学生档案里没有{who}", detail={"field": "student_name"})
    if len(matches) > 1:
        raise ApiError(
            INVALID_VALUE,
            f"有 {len(matches)} 个学生都叫「{name}」，系统分不清是哪一个。请改用学号指定。",
            detail={"field": "student_name", "matches": len(matches)},
        )
    return matches[0]


# ---------------------------------------------------------------- 看板


def clear_seats(session: Session, class_id: int) -> int:
    """清空座位（座位表参数留着）。破坏性操作，所以先存快照供回退一次。"""
    _save_snapshot(session, class_id)
    removed = session.execute(delete(Seat).where(Seat.class_id == class_id)).rowcount or 0
    session.flush()
    return removed


def board(session: Session, class_id: int) -> dict[str, Any]:
    """座位表要的一份数据：行列数、每格是谁、以及还没排座的学生。"""
    plan = get_plan(session, class_id)
    seats = session.scalars(
        select(Seat).where(Seat.class_id == class_id, Seat.deleted_at.is_(None))
    ).all()
    by_cell = {(seat.row, seat.col): seat for seat in seats}

    grid = []
    for row in range(1, plan.rows + 1):
        line = []
        for col in range(1, plan.cols + 1):
            seat = by_cell.get((row, col))
            line.append(
                {
                    "seatId": seat.id if seat else None,
                    "row": row,
                    "col": col,
                    "group": f"第{col}组",
                    "studentId": seat.student_id if seat else None,
                    "studentName": seat.student_name if seat else "",
                    "sno": seat.sno if seat else "",
                    "note": seat.note if seat else "",
                    "locked": bool(seat.locked) if seat else False,
                    "orphan": bool(seat.orphan) if seat else False,
                }
            )
        grid.append(line)

    seated = {seat.student_id for seat in seats if seat.student_id}
    unseated = [
        {"studentId": student.id, "studentName": student.name, "sno": student.sno}
        for student in session.scalars(
            select(Student)
            .where(Student.deleted_at.is_(None), Student.class_id == class_id)
            .order_by(Student.sno, Student.name)
        )
        if student.id not in seated
    ]

    return {
        "classId": class_id,
        "rows": plan.rows,
        "cols": plan.cols,
        "rule": plan.rule,
        "cells": plan.rows * plan.cols,
        "seated": len([seat for seat in seats if seat.student_id]),
        "grid": grid,
        "unseated": unseated,
        "canRestore": snapshot_exists(session, class_id),
    }
