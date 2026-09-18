"""座位：座位表配置（行列数）与一个一个的座位。

旧应用（`:11005`）的两处结构问题：

1. **没有行列唯一约束**：手工新增/编辑时同行同列的格子可以存在两条，网格是
   `map[row+'-'+col] = seat` 后写覆盖 —— 于是**新建的重复格在网格里看不见**，
   列表里却在，表头「已排 N 人」还把重复的一起算进去。这里 `UNIQUE(class_id,row,col)`。
2. **没有「锁定的座位」这个概念**：一键随机排位把所有座位整体替换，还想保留的
   安排（视力、身高、特殊需要）挡不住。这里 `locked` 标记的座位不参与随机。

另外「组」在旧应用里是从列算出来的（`:10730` `group='第'+col+'组'`），却又存了一份字段，
两处会漂。这里它是**派生属性**（由列决定），只读、不落库。
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin

# 座位表规模的上下限：0 列在老应用里是允许的（`:10480`），结果是一张空表 + 排位无处可放
MIN_GRID = 1
MAX_ROWS = 20
MAX_COLS = 16

DEFAULT_ROWS = 8
DEFAULT_COLS = 6
DEFAULT_RULE = "按身高、视力排，视力差的坐前排"


class SeatPlan(Base, TimestampMixin):
    """一个班的座位表参数（行列数 + 排位原则文本）。

    单独一张表而不是塞进全局 `app_state`：多班是两个真实场景（班主任带一个班、
    任课教师教多个班），座位表参数属于某个班，全局键会让两个班互相覆盖。
    """

    __tablename__ = "seat_plans"

    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), primary_key=True
    )
    rows: Mapped[int] = mapped_column(Integer, default=DEFAULT_ROWS, nullable=False)
    cols: Mapped[int] = mapped_column(Integer, default=DEFAULT_COLS, nullable=False)
    rule: Mapped[str] = mapped_column(Text, default=DEFAULT_RULE, nullable=False)


class Seat(Base, TimestampMixin, SoftDeleteMixin):
    """一个座位格子。空座位也可以是一条记录（只有 row/col，没有学生）。"""

    __tablename__ = "seats"
    __table_args__ = (
        UniqueConstraint("class_id", "row", "col", name="uq_seats_class_position"),
        # 一个学生只能坐一个座位（空座不算）—— 与床位同一套做法
        Index(
            "uq_seats_student",
            "class_id",
            "student_id",
            unique=True,
            sqlite_where=text("student_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    row: Mapped[int] = mapped_column(Integer, nullable=False)
    col: Mapped[int] = mapped_column(Integer, nullable=False)
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True, default=None
    )
    student_name: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    # 「视力 500 度，需要前排」这类关键信息：随机排位**不清它**
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 锁定：不参与随机排位、也不参与轮换
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    student = relationship("Student", lazy="selectin")

    @property
    def group(self) -> str:
        """第几组（由列决定）—— 派生值，不落库，所以不会和列数漂掉。"""
        return f"第{self.col}组"

    @property
    def sno(self) -> str:
        """学号（派生）—— 列表、导出、导入都按这个扁平形状用（与床位同一套做法）。"""
        return self.student.sno if self.student else ""

    @property
    def position(self) -> str:
        return f"{self.row} 排 {self.col} 列"

    @property
    def orphan(self) -> bool:
        """学生已从档案删除，座位还占着。"""
        return self.student is not None and self.student.deleted_at is not None
