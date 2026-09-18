"""监护人。

一个学生可以有多个监护人 —— 这是会议里明确的诉求：学生只写了一个联系人，
联系不上时得找其他人（「统一起来方便查找，直接搜名字就能打电话」）。

所以这里是一张**子表**（一名学生多行），而不是旧应用那种「一行里塞下父母双方」的写法。
旧应用的父/母姓名电话也确实同时出现在学生档案字段里，属于同一件事两处存 ——
新模型里这类信息只留在监护人表（详见 `docs/改造方案/03` §6.3）。

`role` 的取值来自旧应用真实数据（父亲/母亲/父母/祖父母），另加「其他」兜底。
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin

ROLES = ("父亲", "母亲", "祖父母", "其他")


class Guardian(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "guardians"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # 学生姓名是**冗余展示列**：列表、搜索、导入判重都按名字走，省掉每次列表都 join。
    # 不变量：student_name / class_id 都由 student_id 派生，写入时统一在
    # services/guardian_service.link_student 里保持一致。
    student_name: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    role: Mapped[str] = mapped_column(String(16), default="其他", nullable=False)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    job: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    wechat: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    # 主要联系人：紧急情况先打这一个
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
