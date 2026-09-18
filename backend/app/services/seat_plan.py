"""座位表的大小与「回退一次」用的快照。

从 `seat_service.py` 拆出来（`CONTRIBUTING.md` §3 的「按职责分」）：那边是排位规则，
这边是配置与快照。拆的直接原因是文件已经贴到 600 行硬上限。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, NOT_FOUND, ApiError
from app.models.app_state import AppState
from app.models.seat import MAX_COLS, MAX_ROWS, DEFAULT_COLS, DEFAULT_ROWS, DEFAULT_RULE, Seat, SeatPlan
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
            Seat.class_id == class_id, (Seat.row > new_rows) | (Seat.col > new_cols)
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


def take_snapshot(session: Session, class_id: int) -> None:
    """存一张「现在的座位表」，供回退一次用。只保留最近一张（旧覆盖新）。

    **连座位表大小一起存**：只存座位的话，「先批量操作 → 再把表改小 → 回退」会把座位
    还原到格子外面，那个人在界面上既不在网格里、也不在「未排座」名单里
    （评审实测：rows=1 却有 3 个人坐着，第三个找不到）。
    """
    plan = get_plan(session, class_id)
    seats = session.scalars(
        select(Seat).where(Seat.class_id == class_id).order_by(Seat.row, Seat.col)
    ).all()
    payload = {"plan": {"rows": plan.rows, "cols": plan.cols}, "seats": [
        {
            "row": seat.row,
            "col": seat.col,
            "student_id": seat.student_id,
            "student_name": seat.student_name,
            "note": seat.note,
            "locked": seat.locked,
        }
        for seat in seats
    ]}
    key = f"{SNAPSHOT_KEY}:{class_id}"
    row = session.get(AppState, key)
    if row is None:
        session.add(AppState(key=key, value=payload))
    else:
        row.value = payload
    session.flush()


def snapshot_is_available(session: Session, class_id: int) -> bool:
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

    # 兼容早期格式（只有座位、没有座位表大小）
    payload = row.value
    if isinstance(payload, list):
        seat_items, plan_rows, plan_cols = payload, None, None
    else:
        seat_items = payload.get("seats") or []
        saved_plan = payload.get("plan") or {}
        plan_rows, plan_cols = saved_plan.get("rows"), saved_plan.get("cols")

    plan = get_plan(session, class_id)
    rows = plan_rows or plan.rows
    cols = plan_cols or plan.cols
    outside = [
        item
        for item in seat_items
        if not (1 <= item["row"] <= rows and 1 <= item["col"] <= cols)
    ]
    if outside:
        raise ApiError(
            INVALID_VALUE,
            f"快照里有 {len(outside)} 个座位落在当前的座位表外面（现在是 {rows} 排 × {cols} 列），"
            "回退会让它们看不见。请先把座位表改回原来的大小，再回退。",
            detail={"rows": rows, "cols": cols, "outside": len(outside)},
        )

    session.execute(delete(Seat).where(Seat.class_id == class_id))
    plan.rows, plan.cols = rows, cols
    # 学生可能已经不在了：清空数据是**硬删**学生，而快照存在 app_state 里（被保留），
    # 于是回退时按快照插座位会撞外键 → 界面得到 500「服务内部错误」（评审实测）。
    # 只认**真的不存在**的学生（软删的学生行还在，座位照旧恢复，看板会把他标成「档案里没有」）
    existing_ids = set(session.scalars(select(Student.id)))
    restored = 0
    cleared = 0
    for item in seat_items:
        student_id = item.get("student_id")
        if student_id is not None and student_id not in existing_ids:
            student_id = None
            cleared += 1
        session.add(
            Seat(
                class_id=class_id,
                row=item["row"],
                col=item["col"],
                student_id=student_id,
                # 人不在了就别留名字，否则看板上会显示一个查不到的人
                student_name="" if student_id is None else item.get("student_name", ""),
                note=item.get("note", ""),
                locked=bool(item.get("locked")),
            )
        )
        restored += 1
    session.delete(row)  # 回退一次就用掉，免得连点两次往回退到更早的状态
    session.flush()
    return {"restored": restored, "clearedSeats": cleared}
