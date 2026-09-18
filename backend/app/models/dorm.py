"""宿舍：房间与床位。

旧应用这一块（`:13619`）是一行 = **一个床位分配**，容量寄生在「该房间数组顺序第一条
记录」上，而种子数据里根本没有 `capacity` 字段 —— 于是容量永远回退成 8 人间
（`Number(x.capacity) || 8`），老师设过的人数重开就没了。分组键用 `building|room`
字符串拼接，键里带 `|` 或 `undefined` 时找不到目标，**却仍然提示「设置成功」**。

新模型把两件事分开：

- `DormRoom`：楼栋 / 房号 / **容量** / 备注。`(class_id, building, room_no)` 唯一。
  容量是房间的**正式字段**（`NOT NULL DEFAULT 8`），不是寄生在别处的一个数。
- `DormBed`：一条**占用记录** —— 某房间的某个床位号住着某个学生。
  床位号是**整数**（界面显示「N 号床」），`(room_id, bed_no)` 唯一；
  一个学生只能有一张床，由 `uq_dorm_beds_student`（部分唯一索引，空床位不算）保证。

空床位不落库：房间有 `capacity` 个床位号（1..capacity），减掉已占用的就是空位。
这样「几个床位」只有一个来源（房间的容量），不会出现「床位行数与容量不一致」这种
需要人去同步的状态 —— 旧应用正是靠界面同步，才会出现「满员误判」「记录从视图消失」。
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin

# 旧应用的兜底值（`Number(x.capacity) || 8`），新模型做成列的默认值，改不掉也不会消失
DEFAULT_CAPACITY = 8
MAX_CAPACITY = 40  # 一间宿舍住 40 人以上一定是填错了，挡在写入时


class DormRoom(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "dorm_rooms"
    __table_args__ = (
        UniqueConstraint(
            "class_id", "building", "room_no", name="uq_dorm_rooms_class_building_room"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    building: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    room_no: Mapped[str] = mapped_column(String(16), nullable=False)
    # 容量是房间的正式字段 —— 独立成列，不再寄生在某条记录上
    capacity: Mapped[int] = mapped_column(Integer, default=DEFAULT_CAPACITY, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    beds = relationship(
        "DormBed",
        cascade="all, delete-orphan",
        lazy="selectin",
        back_populates="room",
    )

    @property
    def occupied(self) -> int:
        # 只数**真的住了人**的记录：手工往库里塞一条空床位不该让容量显得被占
        return sum(1 for bed in self.beds if bed.student_id is not None)

    @property
    def full(self) -> bool:
        """住满了没有。占用数只能等于容量 —— 超过的路径在写入时就被拒绝了。"""
        return self.occupied >= self.capacity

    @property
    def label(self) -> str:
        """展示名：有楼栋就是「1号楼 203」，没有就只显示房号（很多学校只有一个宿舍楼）。"""
        return f"{self.building} {self.room_no}".strip()


class DormBed(Base, TimestampMixin):
    """一个床位占用记录。**没有软删除**：床位腾出来就是删掉这一行。

    软删除会让 `(room_id, bed_no)` 唯一约束与「重新分配同一个床位」冲突，
    而「找回一条床位记录」这个需求并不存在（重新分配即可）。
    """

    __tablename__ = "dorm_beds"
    __table_args__ = (
        UniqueConstraint("room_id", "bed_no", name="uq_dorm_beds_room_bed"),
        # 一人一床：student_id 为空表示空床位，多个空床位不算冲突 ——
        # 所以只能用**部分**唯一索引（写法与 students.sno 那条一致）
        Index(
            "uq_dorm_beds_student",
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
    room_id: Mapped[int] = mapped_column(
        ForeignKey("dorm_rooms.id", ondelete="CASCADE"), index=True, nullable=False
    )
    bed_no: Mapped[int] = mapped_column(Integer, nullable=False)
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True, default=None
    )
    # 姓名是快照：列表与导出不必 join（与成绩/出勤同一套做法）
    student_name: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    # 寝室长：旧应用的字段，保留
    leader: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    room = relationship("DormRoom", back_populates="beds")
    student = relationship("Student", lazy="selectin")

    # 下面四个是**派生属性**（来自房间与学生）。用途是把「楼栋/房号/床号/姓名」
    # 这个扁平形状暴露出去 —— 旧应用的导入表就是一行一个床位，导入导出要继续认它。
    # 它们不是真实列，所以注册表里**不能声明为可排序/可筛选**（看门测试会拦）。
    @property
    def building(self) -> str:
        return self.room.building if self.room else ""

    @property
    def room_no(self) -> str:
        return self.room.room_no if self.room else ""

    @property
    def sno(self) -> str:
        return self.student.sno if self.student else ""

    @property
    def room_label(self) -> str:
        return self.room.label if self.room else ""

    @property
    def orphan(self) -> bool:
        """学生已从档案里删除，床位还占着。

        软删除的学生不会连带删掉床位（床位是**在用资源**，不是历史记录），
        但床位号仍被占着 —— 所以这里如实标出来，让老师点一下腾空，
        而不是让一个查不到的学生继续占着床位。
        """
        return self.student is not None and self.student.deleted_at is not None
