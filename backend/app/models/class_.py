"""班级。

用户已确认要支持多个班（班主任带一个班，任课教师常教多个班），所以所有班级范围内的
表都带 `class_id`。只有一个班时前端不显示班级切换器。

教室名、团支部名这类原本靠 `meta.grade + meta.classNo` 字符串拼接的字段
（旧应用 `:11337`、`:11259`），改为这里的可配字段。
"""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class Class(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    grade: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    class_no: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    head_teacher_name: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    room_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    youth_branch_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"<Class {self.id} {self.grade}{self.class_no}>"
