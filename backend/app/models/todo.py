"""待办任务（试点页之一）。

业务日期用 `Date` 而不是字符串 —— 排序与比较才可靠（旧应用用的是
'2026-09-01' 这样的字符串，导入时要解析）。
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin

PRIORITIES = ("高", "中", "低")


class Todo(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "todos"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )

    content: Mapped[str] = mapped_column(String(200), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, default=None)
    priority: Mapped[str] = mapped_column(String(8), default="中", nullable=False)
    done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    done_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
