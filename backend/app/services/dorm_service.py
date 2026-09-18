"""宿舍的写入与视图。

这一块是用户明确反馈「配置时会有意义不明的报错」的地方（`:13619`）。旧应用那几条
报错路径，在这里逐条对应到**说清原因的中文提示**：

| 旧应用 | 新实现 |
|---|---|
| 改容量用 `window.prompt()`，浏览器禁用 prompt 时返回 null → 静默什么都不做 | 应用内模态框 + `PATCH /dorm_rooms/{id}`，失败一定有提示 |
| `if(target){...}` 没有 else，但成功 toast 无条件执行 → 「设置成功」其实没写进去 | 写入走同一套校验，写不进去就报错；成功就是真成功 |
| `DB.find` 结果不判空就取 `d.name` → `Cannot read properties of undefined` | 所有查找按 id 且判空，找不到给 `NOT_FOUND` + 中文说明 |
| 床号自由文本，「靠窗」解析成 0 → 从网格里消失、满员误判 | 床位号归一化成**整数**（提取第一段数字），解析不出来的行进冲突报告 |
| 容量调小于已住人数 → 显示上就少几个人 | **拒绝**，并列出需要调整的名单 |

两条与数据完整性有关的规则也在这里（旧应用都没有）：

- `UNIQUE(room_id, bed_no)` + 写入时的检查 → **床位已占用**会明确告诉你是谁住的；
- 部分唯一索引 `uq_dorm_beds_student` → **一个学生只能有一张床**，
  重复分配时告诉他现在住哪、并让人决定是否换床（而不是悄悄多出一张）。
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.errors import (
    DORM_BED_OUT_OF_RANGE,
    DORM_BED_TAKEN,
    DORM_CAPACITY_BELOW_OCCUPIED,
    DORM_STUDENT_ALREADY_ASSIGNED,
    INVALID_VALUE,
    NOT_FOUND,
    ApiError,
)
from app.models.dorm import (
    DUTY_RESULTS,
    DUTY_TASKS,
    MAX_CAPACITY,
    WEEKDAYS,
    DormBed,
    DormDuty,
    DormRoom,
    weekday_label,
    weekday_number,
)
from app.models.student import Student
from app.services.params import as_int
from app.services.roster import find_student, list_class_students

# 「1号床」「01」「床 1」「1」都能认；「靠窗」认不出 —— 认不出就报错，不猜
BED_NUMBER = re.compile(r"\d+")


def normalize_bed_no(raw: Any) -> int | None:
    """把老师写的床号归一化成整数。认不出来返回 None（由调用方报错）。

    旧应用取的是**第一段数字**（`:13645`），所以「1号床（靠窗）」→ 1 —— 这个宽容度要保留，
    因为老师手里就是这种写法。区别在于：旧应用认不出来时静默变成 0，
    那条记录从此在网格里看不见；这里会明确报「认不出的床位号」。
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw) if raw.is_integer() else None
    match = BED_NUMBER.search(str(raw))
    return int(match.group()) if match else None


def apply_room(values: dict[str, Any], session: Session, row: Any = None) -> None:
    """房间的保存前钩子：房号必填、容量合法、**容量不能小于已住人数**。

    最后一条是旧应用最伤人之处：把 6 人间改成 2 人间，界面上就少显示 4 个人，
    而库里什么都没变（`:13685` 读取时取「第一条 capacity>0」，其余记录照旧）。
    这里拒绝，并列出需要先搬走谁。
    """
    room_no = str(values.get("room_no") or (getattr(row, "room_no", "") if row else "")).strip()
    if not room_no:
        raise ApiError(INVALID_VALUE, "房号必填", detail={"field": "room_no"})
    values["room_no"] = room_no
    if "building" in values:
        values["building"] = str(values.get("building") or "").strip()

    if "capacity" in values:
        capacity = as_int(values.get("capacity"), "容量")
        if not 1 <= capacity <= MAX_CAPACITY:
            raise ApiError(
                INVALID_VALUE,
                f"容量要在 1–{MAX_CAPACITY} 之间（一间宿舍住 {MAX_CAPACITY} 人以上多半是填错了）",
                detail={"field": "capacity", "value": values.get("capacity")},
            )
        if row is not None:
            # **按最大床位号判**，不是按人数：看板只画 1..capacity 这些格子，
            # 只看人数的话「8 人间里只住了 5、6 号床两个人 → 容量改成 3」会成功，
            # 而那两个人从此不在看板上、也不在未分配名单里 —— 看起来就是「人少了」
            # （评审实测）。这条检查同时覆盖人数那种情形：床位号 1,2,3 改成容量 2 时
            # 最大床位号 3 > 2，一样被拦下。
            occupied = [bed for bed in row.beds if bed.student_id is not None]
            beyond = [bed for bed in occupied if bed.bed_no > capacity]
            if beyond:
                names = "、".join(f"{bed.bed_no} 号床 {bed.student_name or '（空）'}" for bed in beyond)
                raise ApiError(
                    DORM_CAPACITY_BELOW_OCCUPIED,
                    f"这间住着 {len(occupied)} 个人，其中 {names} 的床位号超过了 {capacity}。"
                    f"容量不能改成 {capacity} —— 那样这几个人会从宿舍分布里消失。"
                    "请先把他们的床位挪到前面的床位号，或把容量调大一些。",
                    detail={
                        "occupied": len(occupied),
                        "capacity": capacity,
                        "beyond": [bed.bed_no for bed in beyond],
                    },
                )
        values["capacity"] = capacity

    # 同一楼栋同房号不能重复 —— 旧应用允许重复，于是同一个房间在界面上被拆成两张卡，
    # 容量各自算各自的。**新建与改名都要查**：只在新建时查的话，把 A2 改成已存在的 A1
    # 会一路写下去，最后撞数据库唯一索引报 500（评审实测）。
    clash = session.scalars(
        select(DormRoom).where(
            DormRoom.deleted_at.is_(None),
            # 更新时 class_id 会被写入管线摘掉（不允许改班级），所以要从行上取
            DormRoom.class_id == (values.get("class_id") or (row.class_id if row else None)),
            DormRoom.building == values.get("building", getattr(row, "building", "") if row else ""),
            DormRoom.room_no == room_no,
            DormRoom.id != (row.id if row is not None and row.id else 0),
        )
    ).first()
    if clash is not None:
        raise ApiError(
            INVALID_VALUE,
            f"「{clash.label}」已经在这份名单里了，请直接"
            + ("改成另一个房号（同一个房间不需要建两条）" if row is not None else "编辑那一间（不用新建）"),
            detail={"field": "room_no", "roomId": clash.id},
        )


def apply_room_delete(session: Session, row: Any) -> None:
    """删房间之前先看里面有没有人 —— 有就拒绝，并列出是谁。

    房间是软删除、床位不跟着删，于是「删掉房间」会让那间房的人**从所有视图里消失**
    （看板按房间画、未分配名单按「有没有 student_id」判定，两边都看不到他），
    想给他排到别处还会因为同名房间撞唯一索引报 500（评审实测）。
    所以这里挡住：腾空或搬走之后才允许删房间。
    """
    occupied = [bed for bed in row.beds if bed.student_id is not None]
    if occupied:
        names = "、".join(f"{bed.bed_no} 号床 {bed.student_name or '（未知）'}" for bed in occupied)
        raise ApiError(
            INVALID_VALUE,
            f"「{row.label}」里还住着 {len(occupied)} 个人（{names}），不能直接删。"
            "请先把床位腾空，或把人搬到别的房间。",
            detail={"roomId": row.id, "occupied": len(occupied)},
        )


def resolve_room(session: Session, class_id: int, building: str, room_no: str) -> DormRoom:
    """按（楼栋、房号）取房间，没有就建一间。

    导入时这段是必需的：老师的表里只有「楼栋/房号/床号/姓名」，
    没有「先建房间再分配」这一步 —— 建房间是导入的副作用，不是额外操作。

    楼栋留空时有一步**无歧义的回退**：如果这个房号只在一个楼栋里出现过，就用那一间。
    不加这一步的话，老师的表里只写「房号 202」就会凭空多出一间「无楼栋 202」，
    和已有的「1号楼 202」并排显示，两边各自算容量。房号在多个楼栋都有时明确报错，
    让人填上楼栋 —— 猜楼的后果比报错糟糕。
    """
    def find(where_building: str | None):
        query = select(DormRoom).where(
            DormRoom.deleted_at.is_(None), DormRoom.class_id == class_id, DormRoom.room_no == room_no
        )
        if where_building is not None:
            query = query.where(DormRoom.building == where_building)
        return list(session.scalars(query))

    exact = find(building)
    if exact:
        return exact[0]

    if not building:
        matches = find(None)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            buildings = "、".join(sorted(room.building or "（无楼栋）" for room in matches))
            raise ApiError(
                INVALID_VALUE,
                f"房号「{room_no}」在 {buildings} 里都有，请填上楼栋再登记床位",
                detail={"field": "building", "roomNo": room_no},
            )

    room = DormRoom(class_id=class_id, building=building, room_no=room_no)
    session.add(room)
    session.flush()
    return room


def apply_bed(values: dict[str, Any], session: Session, row: Any = None) -> None:
    """床位的保存前钩子：解析房间、归一化床号、解析学生，并挡住三种冲突。

    新增、编辑、导入三条路径都走它（导入旧宿舍表就靠这段）。
    """
    class_id = values.get("class_id") or (getattr(row, "class_id", None) if row else None)
    if not class_id:
        raise ApiError(INVALID_VALUE, "缺少班级，无法确定这个床位属于哪个班")

    building = str(
        values.get("building") or (row.building if row else "") or ""
    ).strip()
    room_no = str(
        values.get("room_no") or (row.room_no if row else "") or ""
    ).strip()
    if not room_no:
        raise ApiError(INVALID_VALUE, "房号必填", detail={"field": "room_no"})

    room = resolve_room(session, class_id, building, room_no)
    values["room_id"] = room.id
    values["class_id"] = class_id

    raw_bed = values.get("bed_no")
    if raw_bed in (None, ""):
        raw_bed = row.bed_no if row is not None else None
    # 格式已在 `field_value._parse_bed_no` 里统一校验过（导入预览也走那一份）。
    # 这里只补「旧记录没带过来」这一种情况，以及**本场**才有的范围检查。
    bed_no = normalize_bed_no(raw_bed)
    if bed_no is None or bed_no < 1:
        raise ApiError(
            INVALID_VALUE,
            f"认不出的床位号「{raw_bed}」。请填数字，例如 1 或 1号床。",
            detail={"field": "bed_no", "value": raw_bed},
        )
    if bed_no > room.capacity:
        raise ApiError(
            DORM_BED_OUT_OF_RANGE,
            f"{room.label} 是 {room.capacity} 人间，没有 {bed_no} 号床。"
            "请改床位号，或先把这间房的容量调大。",
            detail={"field": "bed_no", "value": bed_no, "capacity": room.capacity},
        )
    values["bed_no"] = bed_no

    student = resolve_student(session, values, row, class_id)
    if student is not None:
        values["student_id"] = student.id
        values["student_name"] = student.name

    # 这三个是**输入用的虚拟字段**（不是 DormBed 的列：楼栋/房号在房间上，学号在学生上）。
    # 必须在建行之前摘掉，否则 `spec.model(**columns)` 会去 set 只读属性，
    # 报 `property 'room_no' has no setter`（建行时才炸，很难往这里想）。
    # 输出不受影响：列表/导出读的是模型上的派生属性
    for key in ("building", "room_no", "sno"):
        values.pop(key, None)

    # 床位已被别人占用 —— 说清是谁，而不是让老师自己去翻
    taken = session.scalars(
        select(DormBed).where(
            DormBed.room_id == room.id,
            DormBed.bed_no == bed_no,
            DormBed.id != (row.id if row is not None and row.id else 0),
        )
    ).first()
    if taken is not None:
        raise ApiError(
            DORM_BED_TAKEN,
            f"{room.label} 的 {bed_no} 号床已经住了 {taken.student_name or '（未知）'}。"
            "要换人的话，请先把原来那条改到别的床位。",
            detail={"field": "bed_no", "bedNo": bed_no, "by": taken.student_name},
        )

    # 一个学生只能有一张床
    if student is not None:
        other = session.scalars(
            select(DormBed).where(
                DormBed.class_id == class_id,
                DormBed.student_id == student.id,
                DormBed.id != (row.id if row is not None and row.id else 0),
            )
        ).first()
        if other is not None:
            here = other.room.label if other.room else "别的房间"
            raise ApiError(
                DORM_STUDENT_ALREADY_ASSIGNED,
                f"{student.name} 已经住在 {here} 的 {other.bed_no} 号床了。"
                "换床的话，请先把他从原来的床位腾出来。",
                detail={
                    "field": "student_name",
                    "studentId": student.id,
                    "roomId": other.room_id,
                    "bedId": other.id,
                },
            )


def resolve_student(
    session: Session,
    values: dict[str, Any],
    row: Any,
    class_id: int,
    *,
    required_message: str | None = None,
) -> Student | None:
    """按姓名（优先）或学号找学生（床位与值日共用）。

    规则本身在 `services/roster.py:find_student` —— 这是**第四处**要用它的地方，
    所以在那之前先收成一份（原先监护人、出勤、宿舍各写了一遍）。

    空值有两种情形：**明确传空**表示「腾出这个位置 / 换人」，没传则表示「保持原样」——
    两者不能混，否则改一下「寝室长」就会把学生从床上清掉。
    """
    name = str(values.get("student_name") or "").strip()
    sno = str(values.get("sno") or "").strip()
    provided = "student_name" in values or "sno" in values

    if not name and not sno:
        if required_message:
            # 值日这类「必须有人」的场景：给一句贴合场景的话，而不是复用床位那句
            raise ApiError(INVALID_VALUE, required_message, detail={"field": "student_name"})
        if row is None:
            raise ApiError(
                INVALID_VALUE,
                "要填学生姓名（或学号）。空床位不用登记 —— 界面上按房间容量自动显示成空位。",
                detail={"field": "student_name"},
            )
        if provided:
            values["student_id"] = None
            values["student_name"] = ""
        return None

    student, problem = find_student(session, name=name, sno=sno, class_id=class_id)
    if problem is not None:
        raise ApiError(INVALID_VALUE, problem, detail={"field": "student_name" if name else "sno"})
    return student


def room_tree(session: Session, class_id: int) -> dict[str, Any]:
    """宿舍分布的主视图：每间房的容量、床位占用、空床位，以及还没分到床位的学生。

    容量与床位一次给全 —— 「这间住几个人、还剩几个空位」只该有一个来源，
    旧应用是靠界面按 `capacity` 现算的，于是容量读错一次整间房就错了。
    """
    rooms = list(
        session.scalars(
            select(DormRoom)
            .where(DormRoom.deleted_at.is_(None), DormRoom.class_id == class_id)
            .order_by(DormRoom.building, DormRoom.room_no)
        )
    )

    payload = []
    for room in rooms:
        by_no = {bed.bed_no: bed for bed in room.beds}
        beds = []
        for bed_no in range(1, room.capacity + 1):
            bed = by_no.get(bed_no)
            beds.append(
                {
                    "bedId": bed.id if bed else None,
                    "bedNo": bed_no,
                    "studentId": bed.student_id if bed else None,
                    "studentName": bed.student_name if bed else "",
                    "sno": bed.sno if bed else "",
                    "leader": bool(bed.leader) if bed else False,
                    "note": bed.note if bed else "",
                    "orphan": bool(bed.orphan) if bed else False,
                }
            )
        payload.append(
            {
                "roomId": room.id,
                "building": room.building,
                "roomNo": room.room_no,
                "label": room.label,
                "capacity": room.capacity,
                "occupied": room.occupied,
                "full": room.full,
                "note": room.note,
                "beds": beds,
            }
        )

    return {
        "classId": class_id,
        "rooms": payload,
        "unassigned": unassigned_boarders(session, class_id),
        "stats": {
            "roomCount": len(payload),
            "bedCount": sum(room["capacity"] for room in payload),
            "occupied": sum(room["occupied"] for room in payload),
        },
    }


def unassigned_boarders(session: Session, class_id: int) -> list[dict[str, Any]]:
    """住宿但还没有床位的在册学生。

    判定住宿生读学生档案的 `boarding` —— 住宿生是「谁的床位还没分」的分子来源；
    顺带把两个方向的缺口都算出来（有床位但档案写着走读的人不是问题，只提示）。
    """
    seated = set(
        session.scalars(
            select(DormBed.student_id).where(
                DormBed.class_id == class_id, DormBed.student_id.is_not(None)
            )
        )
    )
    boarders = session.scalars(
        select(Student).where(
            Student.deleted_at.is_(None),
            Student.class_id == class_id,
            func.json_extract(Student.extra, "$.boarding") == "住校",
        )
    )
    return [
        {"studentId": student.id, "studentName": student.name, "sno": student.sno}
        for student in boarders
        if student.id not in seated
    ]
