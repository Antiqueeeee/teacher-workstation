"""班规制度（试点页之一）。

在旧应用的基础上加了 `version` / `effective_from` / `effective_to` ——
原来只有「更新日期」，无法回答「这条规矩当时是否有效」。

`CATEGORIES` 用的是**旧应用里真实在用的词表**（它的 select 选项 + 默认值），
不是我另编一套：词表对不上，老师手里已有的表格一条都导不进来。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin

# 与旧应用 :9684 一致
CATEGORIES = (
    "考勤纪律",
    "课堂纪律",
    "学习管理",
    "卫生值日",
    "宿舍管理",
    "文明礼仪",
    "安全规范",
    "激励条款",
)


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
