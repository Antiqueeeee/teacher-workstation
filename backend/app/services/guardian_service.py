"""监护人的保存前处理：把「学生姓名」解析成 `student_id`，并带出 `class_id` 与冗余姓名。

为什么必须有这个钩子：**老师记的是名字，程序需要的是 id**。这个转换只能有一处 ——
新增、编辑、导入三条路径都走它。各写一遍的话，三条路迟早推出不同结果，
而这个项目的旧版就是被这种「同一件事多处实现」拖垮的。

同名学生会**明确报错**而不是随便挑一个：会议里就点过「有重名」这个现实问题，
静默挂到同名学生身上，比报错糟糕得多。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, ApiError
from app.models.student import Student


def link_student(values: dict[str, Any], session: Session, row: Any = None) -> None:
    """解析并写入 `student_id` / `student_name` / `class_id`。"""
    name = str(values.get("student_name") or (getattr(row, "student_name", "") if row else "") or "").strip()
    if not name:
        raise ApiError(INVALID_VALUE, "必须填写学生姓名", detail={"field": "student_name"})

    class_id = values.get("classId") or (getattr(row, "class_id", None) if row else None)
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
            "请先在学生档案里用可区分的写法（例如带上学号）再录联系人。",
            detail={"field": "student_name", "value": name, "matches": len(matches)},
        )

    student = matches[0]
    values["student_id"] = student.id
    values["student_name"] = student.name
    values["class_id"] = student.class_id
