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
from app.models.vocab import SUBJECTS

# 科目词表的家在 models/vocab.py（作业与成绩共用一份），这里保留 SUBJECTS 的
# 导出以兼容既有 import；不要在别处再抄一份
__all__ = ["SUBJECTS", "QUALITIES", "RATE_MODES", "Homework", "HomeworkUnsubmitted"]

# 与旧应用一致（作业表单的 options）
QUALITIES = ("优", "良", "中", "差")

# 提交率的两种模式：自动按未交名单算 / 手工覆盖（学校要求按人数上报之类）。
# 取值用中文而不是 auto/manual —— 它会出现在界面下拉里，中英混排看着别扭
RATE_MODES = ("自动", "手工")


def compute_rate(total: int | None, unsubmitted: int) -> int | None:
    """提交率 = (应交 − 未交) / 应交。应交 0 人时返回 None（界面显示「—」）。

    放在模型模块里而不是服务层：`Homework.rate_auto`（派生属性）要用它，
    而 models 不能 import services（分层禁令）。**规则只有这一份** ——
    服务层的写入钩子也 import 它，不另写一遍。
    """
    if not total or total <= 0:
        return None
    missing = max(0, min(unsubmitted, total))  # 名单比应交人数还多时按应交人数封顶
    return round((total - missing) / total * 100)


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
    # 属于哪门课（可空）：班主任布置的作业没有课程，任课教师从「学科与成绩」布置的有。
    # 旧应用把课程作业单存成 `courses[].homework[]`（第二份并行数据、提交率还是手填的），
    # 这里合并成同一张表 —— 提交率、未交名单、名单解析因此只有一套实现
    course_id: Mapped[int | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), index=True, default=None
    )

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
    course = relationship("Course", lazy="selectin")

    @property
    def course_name(self) -> str:
        """这次作业属于哪门课（空的表示班主任布置的常规作业）。"""
        return self.course.name if self.course else ""

    @property
    def unsubmitted_names(self) -> str:
        """未交名单（顿号分隔）。展示与导出用它，与 `rate` **同源** —— 都来自这张子表。"""
        return "、".join(link.student_name for link in self.unsubmitted)

    @property
    def unsubmitted_count(self) -> int:
        return len(self.unsubmitted)

    @property
    def rate_auto(self) -> int | None:
        """**按未交名单**算出来的提交率，不管当前是什么模式。

        手工覆盖时用它对照：`rate` 与 `rate_auto` 差得远，多半是手工值填错了
        （或者名单没更新）。界面据此提示差异 —— 否则「同一个提交率两个来源」
        这件事在页面上完全看不出来。
        """
        return compute_rate(self.total, len(self.unsubmitted))


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
