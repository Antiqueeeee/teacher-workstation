"""家长联系日志的写入规则。

只有一条：把老师填的**学生姓名**解析成 `student_id`。
规则本身在 `services/roster.py:find_student`（监护人、出勤、宿舍、联系日志共用一份）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, ApiError
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
