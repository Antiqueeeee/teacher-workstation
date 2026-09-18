"""宿舍值日：房间与学生的引用解析、以及按房间分组的看板。

从 `dorm_service.py` 拆出来（`CONTRIBUTING.md` §3 的「按子功能分」）：
那边是「房间 + 床位」，这边是「值日」，两者只共用房间与学生的解析规则。
拆的直接原因是文件已经贴到 600 行硬上限。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, ApiError
from app.models.dorm import (
    DUTY_RESULTS,
    DUTY_TASKS,
    WEEKDAYS,
    DormDuty,
    DormRoom,
    weekday_label,
    weekday_number,
)
from app.services.dorm_service import resolve_student


def require_room(session: Session, class_id: int, building: str, room_no: str) -> DormRoom:
    """值日安排里的房间**必须已经存在**（与床位不同：床位导入时会把房间建出来）。

    理由：一条指向不存在宿舍的值日安排没有任何意义，而旧应用的下拉只是复制了一份
    选项、不校验，于是这种记录能造出来（`:13947`）。床位那边是「先有房间再住人」的
    自然顺序，这里反过来 —— 值日是为已有房间排的。
    """
    room_no = str(room_no or "").strip()
    if not room_no:
        raise ApiError(INVALID_VALUE, "房号必填", detail={"field": "room_no"})

    query = select(DormRoom).where(
        DormRoom.deleted_at.is_(None), DormRoom.class_id == class_id, DormRoom.room_no == room_no
    )
    building = str(building or "").strip()
    if building:
        query = query.where(DormRoom.building == building)
    matches = list(session.scalars(query))

    if not matches:
        raise ApiError(
            INVALID_VALUE,
            f"宿舍分布里没有「{room_no}」这间房。请先到「宿舍分布」把它加进去，再排值日。",
            detail={"field": "room_no", "value": room_no},
        )
    if len(matches) > 1:
        buildings = "、".join(sorted(room.building or "（无楼栋）" for room in matches))
        raise ApiError(
            INVALID_VALUE,
            f"房号「{room_no}」在 {buildings} 里都有，请填上楼栋",
            detail={"field": "building", "roomNo": room_no},
        )
    return matches[0]


def apply_duty(values: dict[str, Any], session: Session, row: Any = None) -> None:
    """值日的保存前钩子：房间与学生都解析成引用，星期转成序号。

    `weekday` 与 `weekday_no` 都落库：前者是汉字（对得上老师的表），后者是序号（排序用）。
    与床位不同的是，`weekday` 本身就是真实列，所以不摘掉。
    """
    class_id = values.get("class_id") or (getattr(row, "class_id", None) if row else None)
    if not class_id:
        raise ApiError(INVALID_VALUE, "缺少班级，无法确定这条值日属于哪个班")

    raw_weekday = values.get("weekday") or (getattr(row, "weekday", None) if row else None)
    number = weekday_number(raw_weekday)
    if number is None:
        raise ApiError(
            INVALID_VALUE,
            f"认不出的星期「{raw_weekday}」，只能是{'、'.join(WEEKDAYS)}",
            detail={"field": "weekday", "value": raw_weekday},
        )
    values["weekday"] = WEEKDAYS[number - 1]
    values["weekday_no"] = number  # 排序用（汉字排序是按码位，星期几会乱）

    building = str(values.get("building") or (row.building if row else "") or "").strip()
    room_no = str(values.get("room_no") or (row.room_no if row else "") or "").strip()
    room = require_room(session, class_id, building, room_no)
    values["room_id"] = room.id
    values["class_id"] = class_id

    task = values.get("task")
    if task not in (None, "") and str(task).strip() not in DUTY_TASKS:
        raise ApiError(
            INVALID_VALUE,
            f"认不出的值日任务「{task}」，只能是{'、'.join(DUTY_TASKS)}",
            detail={"field": "task"},
        )

    student = resolve_student(
        session,
        values,
        row,
        class_id,
        required_message="必须填值日学生（姓名或学号）—— 一条不知道谁值日的安排没有意义",
    )
    if student is not None:
        values["student_id"] = student.id
        values["student_name"] = student.name

    # 这几个是输入用的虚拟字段（不是 DormDuty 的列，见床位那段同样的问题）
    for key in ("building", "room_no", "sno"):
        values.pop(key, None)


def duty_board(session: Session, class_id: int) -> dict[str, Any]:
    """值日看板：**按房间分组**，每间房列出 7 天各自的安排。

    分组必须在服务端做：旧应用是前端把整表拉下来再分组，一旦记录多到分页，
    分组结果就会缺一部分而界面上看不出来。
    """
    rooms = list(
        session.scalars(
            select(DormRoom)
            .where(DormRoom.deleted_at.is_(None), DormRoom.class_id == class_id)
            .order_by(DormRoom.building, DormRoom.room_no)
        )
    )
    duties = session.scalars(
        select(DormDuty).where(DormDuty.class_id == class_id, DormDuty.deleted_at.is_(None))
    ).all()

    by_room: dict[int, list[DormDuty]] = {}
    for duty in duties:
        by_room.setdefault(duty.room_id, []).append(duty)

    payload = []
    for room in rooms:
        items = sorted(by_room.get(room.id, []), key=lambda duty: (duty.weekday_no, duty.id))
        days = {duty.weekday_no: [] for duty in items}
        for duty in items:
            days[duty.weekday_no].append(
                {
                    "id": duty.id,
                    "weekday": duty.weekday,
                    "weekdayNo": duty.weekday_no,
                    "studentId": duty.student_id,
                    "studentName": duty.student_name,
                    "sno": duty.sno,
                    "task": duty.task,
                    "checker": duty.checker,
                    "result": duty.result,
                    "note": duty.note,
                    "orphan": duty.orphan,
                }
            )
        payload.append(
            {
                "roomId": room.id,
                "label": room.label,
                "building": room.building,
                "roomNo": room.room_no,
                "capacity": room.capacity,
                "occupied": room.occupied,
                "days": [
                    {"weekday": weekday_label(number), "weekdayNo": number, "items": days.get(number, [])}
                    for number in range(1, len(WEEKDAYS) + 1)
                ],
                "count": len(items),
            }
        )

    # 提到了但已经不在宿舍分布里的房间（房间被删了）——如实列出来，别让记录静默消失
    known = {room.id for room in rooms}
    orphan_rooms = sorted(
        {
            (duty.room_label or "（房间已删除）")
            for duty in duties
            if duty.room_id not in known
        }
    )
    return {
        "classId": class_id,
        "rooms": payload,
        "weekdays": list(WEEKDAYS),
        "tasks": list(DUTY_TASKS),
        "results": list(DUTY_RESULTS),
        "total": len(duties),
        "orphanRooms": orphan_rooms,
    }
