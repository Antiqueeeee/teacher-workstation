"""话术模板（试点页之一）。

**故意选一个「不属于某个班级」的表** —— 用来验证注册表与 CRUD 工厂同时支持
班级范围与全局两种表（旧应用里话术模板也是全班共享的通用素材）。

旧应用把这 45 条长文案硬编码在核心脚本里（`:8060` 首次进入时播种），
这里改成普通数据，由夹具/种子装载。
"""

from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin

CATEGORIES = ("家长沟通", "学生谈话", "表彰鼓励", "问题反馈", "通知公告", "其他")


class Template(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(primary_key=True)

    title: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(16), default="其他", nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
