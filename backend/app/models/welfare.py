"""特殊体质档案与助学金。

两张表都涉及**钱与安全**，所以各有两条硬约束：

- 特殊体质：**一个学生一条**（部分唯一索引）—— 旧应用可以给同一个人建多条，
  应急时看到互相矛盾的两条；
- 助学金：金额以**分**存整数（`03` §6.2 的约定），不用浮点 —— 浮点加法会出现
  `0.1 + 0.2 = 0.30000000000000004` 这种尾数，而这是要跟家长对账的钱。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin

HEALTH_LEVELS = ("需重点关注", "常规关注")

# 与旧应用一致（`:14065` CFG_GRANTS）
GRANT_TYPES = (
    "国家助学金",
    "校级奖助学金",
    "临时困难补助",
    "免学杂费",
    "营养餐补助",
    "社会捐助",
    "其他",
)
GRANT_LEVELS = ("一等", "二等", "三等", "甲等", "乙等", "—")
# 状态按顺序流转（申请中 → 公示中 → 已发放 / 未通过）
GRANT_STATUSES = ("申请中", "公示中", "已发放", "未通过")
GRANT_PENDING = ("申请中", "公示中")


class HealthRecord(Base, TimestampMixin, SoftDeleteMixin):
    """特殊体质 / 健康档案。一人一条。"""

    __tablename__ = "health_records"
    __table_args__ = (
        # 一人一条（未删除的）：旧应用可以建多条，应急时看到两条互相矛盾的
        Index(
            "uq_health_records_student",
            "class_id",
            "student_id",
            unique=True,
            sqlite_where=text("student_id IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True, default=None
    )
    student_name: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    type: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    level: Mapped[str] = mapped_column(String(16), default="需重点关注", nullable=False)
    record_date: Mapped[date | None] = mapped_column(Date, default=None)
    contact: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    emergency: Mapped[str] = mapped_column(Text, default="", nullable=False)
    limit_note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    student = relationship("Student", lazy="selectin")

    @property
    def sno(self) -> str:
        return self.student.sno if self.student else ""


class Grant(Base, TimestampMixin, SoftDeleteMixin):
    """助学金 / 资助记录。金额以分存整数。"""

    __tablename__ = "grants"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True, default=None
    )
    student_name: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    type: Mapped[str] = mapped_column(String(16), nullable=False)
    level: Mapped[str] = mapped_column(String(8), default="—", nullable=False)
    # 金额（分）。输入用元、这里存分 —— 浮点算钱会出现尾数，而这是要跟家长对账的数
    amount_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    semester: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    apply_date: Mapped[date | None] = mapped_column(Date, default=None)
    status: Mapped[str] = mapped_column(String(8), default="申请中", nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    student = relationship("Student", lazy="selectin")

    @property
    def sno(self) -> str:
        return self.student.sno if self.student else ""

    @property
    def amount_yuan(self) -> str:
        """金额（元，两位小数）—— 列表、导出、合计都读它。"""
        return f"{self.amount_cents / 100:.2f}"

    @property
    def amount_display(self) -> str:
        """0 元显示「减免」（旧应用就是这个写法）。"""
        return self.amount_yuan if self.amount_cents else "减免"

    @property
    def pending(self) -> bool:
        return self.status in GRANT_PENDING
