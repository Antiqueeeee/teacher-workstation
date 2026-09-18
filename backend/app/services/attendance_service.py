"""出勤的写入规则：解析学生、挡住「一天两条」、点名按日期整体覆盖。

**点名为什么必须整体覆盖**：旧应用的点名提交是「先按白名单删掉当天记录、再逐人重建」
（`:10056`、`:10066`），而那份白名单漏了「早退」（`:9948` 只有 `迟到/病假/事假/旷课`）。
后果有两个，都不会报错：

1. 老师把某个学生从「早退」改回「正常」，那条早退记录**留在库里**，
   第二天看统计仍然算他异常；
2. 删掉重建会把老师手填的 `reason`（事由）覆写成「全班点名」、`handled` 清空 ——
   而 `handled` 为空正是待办中心「缺勤未联系家长」的触发条件，于是刚跟进完的学生
   又变回待办。

新实现按「提交的是当天完整状态」处理：没标异常的（含被改回正常的）一律不保留，
但**状态没变的那条一个字都不动**，手填的事由与跟进记录不会因为点名而丢失。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, ApiError
from app.models.attendance import ATTENDANCE_TYPES, FOLLOW_UP_STATES, Attendance
from app.models.student import Student
from app.services.attendance_rate import day_summary
from app.services.params import as_int
from app.services.roster import list_class_students


def default_follow_up(att_type: str) -> str:
    """新增记录时「跟进状态」的默认值。

    - 旷课：没人知道学生去哪了 → 必须联系家长，进待办；
    - 病假/事假：家长已经打过招呼 → 无需联系；
    - 迟到/早退：纪律指标，不进跟进列表（与旧应用待办中心的判定范围一致）。

    这只是**默认值**，老师随时可以改；它存在的意义是让「待办」列表既不漏事、也不刷屏。
    """
    return "待联系" if att_type == "旷课" else "无需联系"


def default_period(att_type: str) -> str:
    """迟到按早读、其余按全天 —— 沿用旧应用点名时的写法（`:10066`）。"""
    return "早读" if att_type == "迟到" else "全天"


def next_follow_up(current: str | None, att_type: str) -> str:
    """跟进状态该变成什么（新增、以及点名时类型变了，都走这里）。

    「已通知」是既成事实，系统不悄悄撤掉它 —— 老师改类型多半是在修正记录，
    不该顺手把「已经联系过家长」这件事抹了。
    """
    if current == "已通知":
        return current
    return default_follow_up(att_type)


def _find_student(session: Session, name: str, class_id: int | None) -> Student:
    """按姓名找学生；查无此人或重名都明确报错，**绝不随便挑一个**。"""
    query = select(Student).where(Student.deleted_at.is_(None), Student.name == name)
    if class_id:
        query = query.where(Student.class_id == class_id)
    matches = list(session.scalars(query))

    if not matches:
        raise ApiError(
            INVALID_VALUE,
            f"学生档案里没有叫「{name}」的学生，请先在「学生档案」里加进去",
            detail={"field": "student_name", "value": name},
        )
    if len(matches) > 1:
        raise ApiError(
            INVALID_VALUE,
            f"有 {len(matches)} 个学生都叫「{name}」，无法确定是哪一个。"
            "请先在学生档案里用可区分的写法（例如带上学号）再登记考勤。",
            detail={"field": "student_name", "value": name, "matches": len(matches)},
        )
    return matches[0]


def _reject_duplicate(
    session: Session, row: Any, student: Student, day: date
) -> None:
    """一个学生一天只能有一条记录 —— 在写入时挡住，而不是事后靠统计去重。

    结构上有 `UNIQUE(date, student_id)` 兜底，但老师看到的应该是一句说得清的中文，
    而不是 DatabaseError。旧应用允许一天多条，同一学生被扣两次，45 人班的出勤率
    被压到 93%，没人看得出问题出在哪。
    """
    stmt = select(Attendance).where(
        Attendance.date == day, Attendance.student_id == student.id
    )
    if row is not None and getattr(row, "id", None) is not None:
        stmt = stmt.where(Attendance.id != row.id)
    other = session.scalars(stmt).first()
    if other is not None:
        raise ApiError(
            INVALID_VALUE,
            f"{student.name} 在 {day} 已经有一条考勤记录（{other.type}）。"
            "一天只能有一条，请直接改那一条，或换一天登记。",
            detail={"field": "student_name", "value": student.name, "date": str(day)},
        )


def apply_attendance(values: dict[str, Any], session: Session, row: Any = None) -> None:
    """保存前钩子：新增/编辑/导入三条路径共用（老师填的是姓名，程序要的是 id）。"""
    name = str(
        values.get("student_name") or (getattr(row, "student_name", "") if row else "") or ""
    ).strip()
    if not name:
        raise ApiError(INVALID_VALUE, "必须填写学生姓名", detail={"field": "student_name"})

    # class_id 由写入管线**在钩子之前**解析好放进 values（班级随学生走）
    class_id = values.get("class_id") or (getattr(row, "class_id", None) if row else None)
    student = _find_student(session, name, class_id)
    values["student_id"] = student.id
    values["student_name"] = student.name
    values["class_id"] = student.class_id

    day = values.get("date") or (getattr(row, "date", None) if row else None)
    if day is not None:
        _reject_duplicate(session, row, student, day)

    if row is None:
        # 只有新增才补默认值：编辑时老师看到的就是当前值，
        # 悄悄按类型重算会把「已通知」这类人工结论抹掉
        values["handled"] = values.get("handled") or default_follow_up(str(values.get("type") or ""))


@dataclass
class RollCallEntry:
    """点名表里的一行。`type` 为空表示「正常」——正常不落记录。"""

    student_id: int
    type: str = ""
    period: str = ""
    reason: str = ""
    handled: str | None = None
    handled_note: str = ""


@dataclass
class RollCallResult:
    created: int = 0
    updated: int = 0
    removed: int = 0
    kept: int = 0

    def to_dict(self) -> dict:
        return {
            "created": self.created,
            "updated": self.updated,
            "removed": self.removed,
            "kept": self.kept,
        }


def parse_entries(raw: Any) -> list[RollCallEntry]:
    """解析点名提交体；形状不对时给出说得清的错误，而不是 500。"""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ApiError(INVALID_VALUE, "点名数据需要是一个数组", detail={"field": "entries"})

    entries: list[RollCallEntry] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ApiError(INVALID_VALUE, f"点名数据第 {index} 项不是一条记录", detail={"index": index})
        entry = RollCallEntry(
            student_id=as_int(item.get("studentId"), f"第 {index} 项的学生"),
            type=str(item.get("type") or "").strip(),
            period=str(item.get("period") or "").strip(),
            reason=str(item.get("reason") or ""),
            handled=(str(item["handled"]).strip() if item.get("handled") else None),
            handled_note=str(item.get("handledNote") or ""),
        )
        if entry.type and entry.type not in ATTENDANCE_TYPES:
            raise ApiError(
                INVALID_VALUE,
                f"认不出的考勤类型「{entry.type}」，只能是{'、'.join(ATTENDANCE_TYPES)}",
                detail={"index": index, "field": "type"},
            )
        if entry.handled is not None and entry.handled not in FOLLOW_UP_STATES:
            raise ApiError(
                INVALID_VALUE,
                f"认不出的跟进状态「{entry.handled}」，只能是{'、'.join(FOLLOW_UP_STATES)}",
                detail={"index": index, "field": "handled"},
            )
        entries.append(entry)
    return entries


def roll_call(
    session: Session, class_id: int, day: date, entries: list[RollCallEntry]
) -> RollCallResult:
    """按日期整体覆盖提交：一次事务，当天状态以这次提交为准。"""
    roster = {student.id: student for student in list_class_students(session, class_id)}

    # 不在名册里的学生直接拒绝，而不是静默忽略 —— 忽略等于老师以为记上了、其实没记
    outsiders = sorted({entry.student_id for entry in entries if entry.student_id not in roster})
    if outsiders:
        raise ApiError(
            INVALID_VALUE,
            f"点名名单里有 {len(outsiders)} 个学生不在本班（可能刚转班或已被删除），请刷新页面后重试",
            detail={"studentIds": outsiders},
        )

    ids = list(roster)
    existing: dict[int, Attendance] = {}
    if ids:
        existing = {
            row.student_id: row
            for row in session.scalars(
                select(Attendance).where(
                    Attendance.class_id == class_id,
                    Attendance.date == day,
                    Attendance.student_id.in_(ids),
                )
            )
        }

    desired = {entry.student_id: entry for entry in entries if entry.type}
    result = RollCallResult()

    for student_id, entry in desired.items():
        row = existing.get(student_id)
        if row is None:
            session.add(
                Attendance(
                    class_id=class_id,
                    date=day,
                    student_id=student_id,
                    student_name=roster[student_id].name,
                    type=entry.type,
                    period=entry.period or default_period(entry.type),
                    reason=entry.reason,
                    handled=entry.handled or default_follow_up(entry.type),
                    handled_note=entry.handled_note,
                )
            )
            result.created += 1
        elif row.type == entry.type:
            # 状态没变：一个字都不动（手填的事由、处理情况要留住）
            result.kept += 1
        else:
            row.type = entry.type
            row.period = entry.period or default_period(entry.type)
            # 情况变了，旧事由不再适用；跟进状态回到该类型的默认（「已通知」除外）
            row.reason = entry.reason
            row.handled = entry.handled or next_follow_up(row.handled, entry.type)
            row.handled_note = entry.handled_note
            result.updated += 1

    # 没标异常的学生（含被改回「正常」的）一律不留记录：
    # 这是旧应用「早退残留」的根因所在 —— 覆盖就得覆盖全，不能只覆盖一部分类型
    for student_id, row in existing.items():
        if student_id not in desired:
            session.delete(row)
            result.removed += 1

    session.flush()
    return result


def day_view(session: Session, class_id: int | None, day: date) -> dict:
    """点名表要的一份数据：当天小结 + 全班名单 + 每人当天的状态。

    名单与状态一次给全，界面不用自己拼 —— 「谁在这天该被点名」只能有一个来源，
    否则界面上的名单和统计用的名单迟早漂成两套（旧应用就是这样：点名弹窗按
    `students()` 现取，统计按记录条数算，两边对不上也看不出来）。
    """
    students = list_class_students(session, class_id) if class_id else []
    rows: dict[int, Attendance] = {}
    if students:
        rows = {
            row.student_id: row
            for row in session.scalars(
                select(Attendance).where(
                    Attendance.class_id == class_id, Attendance.date == day
                )
            )
        }

    entries = []
    for student in students:
        row = rows.get(student.id)
        entries.append(
            {
                "studentId": student.id,
                "studentName": student.name,
                "sno": student.sno,
                # type 为空 = 正常（正常不落记录）
                "type": row.type if row else "",
                "period": row.period if row else "",
                "reason": row.reason if row else "",
                "handled": row.handled if row else "",
                "handledNote": row.handled_note if row else "",
            }
        )

    return {
        "date": day.isoformat(),
        "classId": class_id,
        "summary": day_summary(session, class_id, day).to_dict(),
        "students": entries,
    }
