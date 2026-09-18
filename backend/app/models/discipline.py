"""违纪记录。

旧应用（`:14309` CFG_DISC）按**姓名**统计「多次违纪学生」（`new Set(sno)` 也拿姓名兜底），
重名会把两个人合成一个，改名就断链。这里改成 `student_id` 引用。
文档 §14 还要求状态流转与处理时间线 —— 状态是受约束的枚举，
处理过程写在 `handling` 里（时间线留到后续增强，不在本轮）。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin

# 与旧应用一致（`:14209` 的 type 选项，11 项）
TYPES = (
    "考勤纪律",
    "课堂纪律",
    "作业纪律",
    "宿舍纪律",
    "仪容仪表",
    "同学关系",
    "卫生值日",
    "校园安全",
    "考试纪律",
    "公物管理",
    "其他",
)
LEVELS = ("轻微", "一般", "严重")
STATUSES = ("整改中", "跟踪观察", "已结案")


class Discipline(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "disciplines"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True, default=None
    )
    student_name: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    type: Mapped[str] = mapped_column(String(16), nullable=False)
    level: Mapped[str] = mapped_column(String(8), default="一般", nullable=False)
    status: Mapped[str] = mapped_column(String(8), default="整改中", nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    handling: Mapped[str] = mapped_column(Text, default="", nullable=False)
    recorder: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    student = relationship("Student", lazy="selectin")

    @property
    def sno(self) -> str:
        return self.student.sno if self.student else ""

    @property
    def open_case(self) -> bool:
        """还没结案 —— 首页跟进清单与「未结案」KPI 都用它。"""
        return self.status != "已结案"
