"""班级费用：费用类别、缴费记录、收支流水。

旧应用（`:15837`，`fees` 页）是一行 = 一个类别，下面嵌 `records[]` 与 `ledger[]` 两个数组。
结构上这里拆成三张表，并修掉文档 §15 列的四条：

1. **金额以分存整数**：旧应用直接用浮点的元，`0.1 + 0.2 = 0.30000000000000004`，
   而这是班费 —— 要跟家长对账的数（`03` §6.2 的约定）；
2. **状态是推导出来的**，不落库：旧应用的 `feeStatus()` 是前端算的，而导出/导入里
   没有这个字段，两边对不上；
3. **收支用显式枚举**（`收入` / `支出`），不再像旧应用那样把「非支出一律判收入」
   —— 导入时一个错别字就能把一笔开销记成进账；
4. **同日流水按录入顺序排**（`date, id`），旧应用只按日期字符串排，同一天的顺序随机。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin

# 收支方向：只有这两种（旧应用的判定是「不是支出就当收入」）
LEDGER_KINDS = ("收入", "支出")

# 缴费状态（推导值，不落库）：由应缴与实缴算出来，见 services/fee_service.py:status_of
FEE_STATUSES = ("已缴", "部分", "未缴", "免缴")


class FeeCategory(Base, TimestampMixin, SoftDeleteMixin):
    """一个收费项目（如「班费」）。"""

    __tablename__ = "fee_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    # 每人应缴标准（分）。改它**不会**回填历史记录：应缴是收钱那一刻的约定
    amount_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    @property
    def amount_yuan(self) -> str:
        return f"{self.amount_cents / 100:.2f}"


class FeeRecord(Base, TimestampMixin, SoftDeleteMixin):
    """某个学生在一个收费项目上的应缴与实缴。"""

    __tablename__ = "fee_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("fee_categories.id", ondelete="CASCADE"), index=True, nullable=False
    )
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True, default=None
    )
    student_name: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    # 应缴是**快照**（收钱那一刻的约定），之后改类别标准不该改写历史记录
    should_pay_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paid_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    date: Mapped[date | None] = mapped_column(Date, default=None)
    note: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    student = relationship("Student", lazy="selectin")

    @property
    def sno(self) -> str:
        return self.student.sno if self.student else ""

    @property
    def should_pay_yuan(self) -> str:
        return f"{self.should_pay_cents / 100:.2f}"

    @property
    def paid_yuan(self) -> str:
        return f"{self.paid_cents / 100:.2f}"

    @property
    def owed_cents(self) -> int:
        """还差多少（应缴 − 实缴，不小于 0）。"""
        return max(0, self.should_pay_cents - self.paid_cents)

    @property
    def status(self) -> str:
        """缴费状态 —— **推导值**，由 `services/fee_service.py:status_of` 算。

        模型上放一个转发是为了让列表/导出/筛选能直接读它（同一份实现）。
        """
        from app.services.fee_service import status_of

        return status_of(self.should_pay_cents, self.paid_cents)


class FeeLedger(Base, TimestampMixin, SoftDeleteMixin):
    """一笔收支流水。方向是显式枚举。"""

    __tablename__ = "fee_ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("fee_categories.id", ondelete="CASCADE"), index=True, nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    item: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    @property
    def amount_yuan(self) -> str:
        return f"{self.amount_cents / 100:.2f}"
