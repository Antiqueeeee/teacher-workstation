"""作业与「未交名单」。

这是用户明确提的痛点之一：「作业的提交率疑似还需要用户自己算」。

旧应用在这里有三套互不相通的口径：
1. `rate` —— 手填的数字，新增时默认 100；
2. `unsubmitted` —— 自由文本名单，只用来出一张「欠交频次榜」；
3. 首页「作业待收」卡片 —— 读的是 `submitted` / `total` 两个**根本不存在的字段**，恒显示 0。

新模型把三者合一：名单是**学生关联**（子表），提交率由名单**算出来**。

`total`（应交人数）是创建时的**快照**：学生后来转学进来，历史作业的应交人数不该跟着变 ——
否则「上周的提交率」会莫名其妙地变低。需要时可以手工改这一条。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin

# 与旧应用一致（:6220 的 SUBJECTS）
SUBJECTS = ("语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理")

# 与旧应用一致（作业表单的 options）
QUALITIES = ("优", "良", "中", "差")

# 提交率的两种模式：自动按未交名单算 / 手工覆盖（学校要求按人数上报之类）。
# 取值用中文而不是 auto/manual —— 它会出现在界面下拉里，中英混排看着别扭
RATE_MODES = ("自动", "手工")


class Homework(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "homework"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )

    date: Mapped[date] = mapped_column(Date, nullable=False)
    subject: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    deadline: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    quality: Mapped[str] = mapped_column(String(8), default="良", nullable=False)
    teacher: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    # 应交人数（创建时的快照；未填时按当时全班人数算）
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 生效的提交率：由名单算出来并**写在这里**，列表/导出/导入三条路因此读同一个值
    rate: Mapped[int | None] = mapped_column(Integer, default=None)
    rate_mode: Mapped[str] = mapped_column(String(8), default="自动", nullable=False)
    # 只在 提交率模式 = 手工 时使用
    rate_manual: Mapped[int | None] = mapped_column(Integer, default=None)

    unsubmitted = relationship(
        "HomeworkUnsubmitted",
        cascade="all, delete-orphan",
        lazy="selectin",
        back_populates="homework",
    )

    @property
    def unsubmitted_names(self) -> str:
        """未交名单（顿号分隔）。展示与导出用它，与 `rate` **同源** —— 都来自这张子表。"""
        return "、".join(link.student_name for link in self.unsubmitted)

    @property
    def unsubmitted_count(self) -> int:
        return len(self.unsubmitted)


class HomeworkUnsubmitted(Base, TimestampMixin):
    """一条「某人没交这次作业」。

    没有软删除：它跟着作业走（作业软删/恢复时一起处理），单独恢复一条未交记录没有意义。
    """

    __tablename__ = "homework_unsubmitted"
    __table_args__ = (UniqueConstraint("homework_id", "student_id", name="uq_homework_unsubmitted"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    homework_id: Mapped[int] = mapped_column(
        ForeignKey("homework.id", ondelete="CASCADE"), index=True, nullable=False
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # 姓名是冗余展示列：导出与列表不必 join
    student_name: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    homework = relationship("Homework", back_populates="unsubmitted")
