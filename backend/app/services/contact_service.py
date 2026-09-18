"""家长联系日志的写入规则与跟进清单。

写入规则只有一条：把老师填的**学生姓名**解析成 `student_id`。
规则本身在 `services/roster.py:find_student`（监护人、出勤、宿舍、联系日志共用一份）。

「待再次联系」的清单放在这里也是一处口径：首页跟进卡片与 `/contacts/follow-ups`
读的是同一个函数（只是首页多给一个时间窗），否则同一个概念两处各筛一遍，
数字迟早对不上（评审点名过）。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, ApiError
from app.models.contact import ContactLog
from app.services.roster import find_student
from app.services.hooks import chain, default_today


def link_contact_student(values: dict[str, Any], session: Session, row: Any = None) -> None:
    """解析学生并写入 `student_id`，同时把姓名归一化成档案里的写法。"""
    class_id = values.get("class_id") or (getattr(row, "class_id", None) if row else None)
    name = str(
        values.get("student_name") or (getattr(row, "student_name", "") if row else "") or ""
    ).strip()
    if not name:
        raise ApiError(INVALID_VALUE, "必须填写学生姓名", detail={"field": "student_name"})

    student, problem, _kind = find_student(session, name=name, class_id=class_id)
    if problem is not None:
        raise ApiError(INVALID_VALUE, problem, detail={"field": "student_name", "value": name})
    values["student_id"] = student.id
    values["student_name"] = student.name


# 声明里用这个：先解析学生，再补「日期留空按今天」
link_contact_student_with_date = chain(link_contact_student, default_today())


def _follow_up_conditions(class_id: int | None, since: date | None) -> list:
    """「待再次联系」的判定条件 —— 清单与计数**共用这一份**。

    早先首页清单带 30 天窗口、而首页卡片的计数不带，于是「卡片说 3 件、点开只有 1 件」
    （评审实测）。两个入口现在都从这里取条件、由调用方传同一个窗口。
    """
    conditions = [ContactLog.deleted_at.is_(None), ContactLog.needs_follow_up.is_(True)]
    if class_id is not None:
        conditions.append(ContactLog.class_id == class_id)
    if since is not None:
        conditions.append(ContactLog.date >= since)
    return conditions


def follow_ups(
    session: Session,
    class_id: int | None,
    *,
    since: date | None = None,
    limit: int | None = None,
) -> list[ContactLog]:
    """标记了「待再次联系」的记录，按日期从早到晚（先出现的先处理）。"""
    stmt = (
        select(ContactLog)
        .where(*_follow_up_conditions(class_id, since))
        .order_by(ContactLog.date.asc(), ContactLog.id.asc())
    )
    if limit:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt))


def follow_up_count(session: Session, class_id: int | None, *, since: date | None = None) -> int:
    """待再次联系的条数 —— 与清单同一套条件、同一个窗口（卡片上的数就是清单的总数）。"""
    return int(
        session.scalar(
            select(func.count())
            .select_from(ContactLog)
            .where(*_follow_up_conditions(class_id, since))
        )
        or 0
    )
