"""班级事务类（班委 / 团员 / 值日 / 违纪 / 特殊体质 / 助学金）的写入规则。

五张表共用同一个「把姓名解析成 student_id」的钩子（`roster.student_link_hook`）；
只有值日与助学金有自己的额外规则。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, ApiError
from app.models.classroom import DUTY_AREAS, DutyMember, WEEKDAYS
from app.models.student import Student
from app.models.welfare import GRANT_STATUSES
from app.services.roster import resolve_names, split_names, student_link_hook
from app.services.roster import find_student

# 五张表共用的钩子（各拿到一个独立实例，提示词一致）
link_cadre_student = student_link_hook()
_link_youth_raw = student_link_hook()


def link_youth_student(values: dict[str, Any], session: Session, row: Any = None) -> None:
    """团员：解析学生 + 入团时间留空按今天（旧应用也是这个默认）。"""
    _link_youth_raw(values, session, row)
    if row is None and values.get("join_date") in (None, ""):
        values["join_date"] = date.today()
link_discipline_student = student_link_hook()
_link_health_raw = student_link_hook()


def link_health_student(values: dict[str, Any], session: Session, row: Any = None) -> None:
    """特殊体质：解析学生 + 确认这个人还没有档案。

    **一人一条要在写入时检查**：唯一索引是兜底，直接撞上去老师看到的是
    「服务内部错误：IntegrityError」——而这张表是用来应急的（发作时找电话），
    数据库说不上话的报错最不该出现在这里。
    """
    from app.models.welfare import HealthRecord

    _link_health_raw(values, session, row)
    if row is None and values.get("record_date") in (None, ""):
        values["record_date"] = date.today()

    student_id = values.get("student_id")
    if student_id:
        existing = session.scalars(
            select(HealthRecord).where(
                HealthRecord.deleted_at.is_(None), HealthRecord.student_id == student_id
            )
        ).first()
        if existing is not None:
            raise ApiError(
                INVALID_VALUE,
                f"{existing.student_name} 已经有一条特殊体质档案了（{existing.type}）。"
                "一个人只建一条 —— 请直接改那一条，免得应急时看到两条互相矛盾的信息。",
                detail={"field": "student_name", "recordId": existing.id},
            )
link_grant_student = student_link_hook()


def apply_duty(values: dict[str, Any], session: Session, row: Any = None) -> Callable[[Any], None] | None:
    """值日的保存前钩子：星期转序号、区域校验、组长解析，落库后再写成员子表。

    成员是 `values.pop("members_text")` 摘出来的一串姓名（顿号分隔），
    与未交名单同一套解析（`roster.split_names` / `resolve_names`）——
    **查无此人或重名都明确报错**，不静默挂错人。
    """
    text = values.pop("members_text", None)
    weekday = str(values.get("weekday") or (row.weekday if row is not None else "") or "").strip()
    if weekday not in WEEKDAYS:
        raise ApiError(
            INVALID_VALUE,
            f"认不出的星期「{weekday}」，只能是{'、'.join(WEEKDAYS)}",
            detail={"field": "weekday", "value": weekday},
        )
    values["weekday"] = weekday
    values["weekday_no"] = WEEKDAYS.index(weekday) + 1

    area = str(values.get("area") or (row.area if row is not None else "") or "").strip()
    if area and area not in DUTY_AREAS:
        raise ApiError(
            INVALID_VALUE,
            f"认不出的区域「{area}」，只能是{'、'.join(DUTY_AREAS)}",
            detail={"field": "area", "value": area},
        )

    class_id = values.get("class_id") or (getattr(row, "class_id", None) if row else None)
    leader = str(values.get("leader_name") or "").strip()
    if leader:
        student, problem, _kind = find_student(session, name=leader, class_id=class_id)
        if problem is not None:
            raise ApiError(INVALID_VALUE, problem, detail={"field": "leader_name"})
        values["leader_id"] = student.id
        values["leader_name"] = student.name
    elif row is not None and "leader_name" in values:
        values["leader_id"] = None

    def after_save(saved: Any) -> None:
        if text is None:
            return
        result = resolve_names(session, split_names(text), saved.class_id)
        if not result.ok:
            raise ApiError(
                INVALID_VALUE,
                "值日成员里有认不出的学生：" + "；".join(result.problems),
                detail={"field": "members_text"},
            )
        saved.members.clear()
        for student in result.students:
            saved.members.append(DutyMember(student_id=student.id, student_name=student.name))
        # 冗余串一并写好：列表与搜索读它（派生属性构不出 SQL）
        saved.members_cache = "、".join(student.name for student in result.students)
        session.flush()

    return after_save


def apply_grant(values: dict[str, Any], session: Session, row: Any = None) -> None:
    """助学金：解析学生、确认状态在词表里。

    金额的「元 → 分」不在这里做 —— 那是字段类型 `money` 的活
    （`field_value._parse_money`），这样**导入预览**也会按同一套规则解析。
    """
    link_grant_student(values, session, row)
    status = values.get("status")
    if status is not None and status not in GRANT_STATUSES:
        raise ApiError(
            INVALID_VALUE,
            f"认不出的状态「{status}」，只能是{'、'.join(GRANT_STATUSES)}",
            detail={"field": "status"},
        )


def youth_consistency(session: Session, class_id: int) -> dict[str, list[dict[str, Any]]]:
    """团员名册与学生档案「政治面貌」的对不上清单（文档 §5 要求的双向一致性提示）。

    **只在界面上提示，不自动改写任何一边** —— 两份数据都可能是事实
    （学生刚入团还没更新档案，或刚退团），系统替老师选一个是最容易出怪事的设计。
    """
    from app.models.classroom import YouthMember

    members = {
        row.student_id: row.student_name
        for row in session.scalars(
            select(YouthMember).where(
                YouthMember.deleted_at.is_(None), YouthMember.class_id == class_id
            )
        )
        if row.student_id
    }
    students = list(
        session.scalars(
            select(Student).where(Student.deleted_at.is_(None), Student.class_id == class_id)
        )
    )

    in_roster_not_in_archive: list[dict[str, Any]] = []
    in_archive_not_in_roster: list[dict[str, Any]] = []
    for student in students:
        politics = str((student.extra or {}).get("politics") or "")
        is_member = student.id in members
        if is_member and politics not in ("共青团员", ""):
            in_roster_not_in_archive.append(
                {"studentId": student.id, "studentName": student.name, "politics": politics}
            )
        elif not is_member and politics == "共青团员":
            in_archive_not_in_roster.append(
                {"studentId": student.id, "studentName": student.name, "politics": politics}
            )
    return {
        "inRosterNotInArchive": in_roster_not_in_archive,
        "inArchiveNotInRoster": in_archive_not_in_roster,
    }
