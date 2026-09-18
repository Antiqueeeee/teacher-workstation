"""班规制度（试点页之一）。

在旧应用的基础上加了 `version` / `effective_from` / `effective_to` ——
原来只有「更新日期」，无法回答「这条规矩当时是否有效」。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin

CATEGORIES = ("考勤", "课堂", "作业", "卫生", "纪律", "仪容", "宿舍", "其他")


class Rule(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )

    category: Mapped[str] = mapped_column(String(16), default="其他", nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    version: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date, default=None)
    effective_to: Mapped[date | None] = mapped_column(Date, default=None)
