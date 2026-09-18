"""考试、考试的科目与满分、以及一行成绩。

旧应用的模型有三个结构性毛病，这里逐个从结构上改掉：

1. **一个学生一场考试只存一行，各科分数塞在一个 `scores:{科目:分}` 对象里**
   （`:12323`）。科目名成了数据的一部分，于是「这场考了哪几科」只能靠遍历所有学生的
   key 猜出来，满分也就只能取「全部科目的并集」——
   某场只考 6 科时，及格线被按 9 科的满分算，全班及格率凭空变低（`:12095`）。
   现在分成 `exam_subjects`（这场考了哪几科、每科满分多少）与 `scores`
   （一个学生一科一行），「这场考试的满分」是一个**明确的数字**，不再是推断出来的。
2. **没有缺考概念**：空值经 `num()` 一律变 0（`:2665`），缺考的学生排在最后一名，
   与「考了 0 分」完全无法区分。现在 `scores.absent` 是独立标记，
   且 `value` 可以为空 —— **空值不等于 0 分**，这一点在库里是能表达出来的。
3. **名次是持久化字段**（`rank`，`:12051`）。改一次满分设置、转走一个学生，
   库里存的名次就跟事实不符了，而界面上看不出来（`:13251` 改了满分却不重算）。
   现在名次**不落库**，每次都从成绩现算（`services/score_stats.py`）。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin

# 与旧应用一致（`:12507` CFG_EXAMS 的 type 选项），默认「月考」
EXAM_KINDS = ("月考", "期中", "期末", "周测", "模拟考", "单元测")

# 及格/优秀按**得分率**判定（旧应用就是比例，但分母用了「全科并集满分」，是错的）
PASS_RATIO = 0.6
EXCELLENT_RATIO = 0.8

# 单科评价的分档（与旧应用 `:12763` 一致），都作用在得分率上，不是绝对分 ——
# 150 分制与 100 分制混在一个班里时，只有得分率是可比的
RATE_BANDS = ((85, "优势科目"), (70, "平稳"), (60, "需加强"))


class Exam(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), default="月考", nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    subjects = relationship(
        "ExamSubject",
        cascade="all, delete-orphan",
        lazy="selectin",
        back_populates="exam",
    )


class ExamSubject(Base, TimestampMixin):
    """一场考试的一个科目：**这场考试的满分就是这个数**。

    没有软删除：它跟着考试走，单独「恢复一个科目」没有意义。
    """

    __tablename__ = "exam_subjects"
    __table_args__ = (
        UniqueConstraint("exam_id", "subject", name="uq_exam_subjects_exam_subject"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True, nullable=False
    )
    subject: Mapped[str] = mapped_column(String(16), nullable=False)
    full_marks: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    exam = relationship("Exam", back_populates="subjects")


class Score(Base, TimestampMixin):
    """一个学生、一场考试、一个科目的一格成绩。

    一行一格而不是「一行一个学生的字典」，代价是行数多（45 人 × 9 科 = 405 行/场），
    换来的是：每科的缺考能单独标、空值与 0 分能区分、统计可以直接用 SQL 聚合，
    而且加一个科目不需要动表结构。
    """

    __tablename__ = "scores"
    __table_args__ = (
        UniqueConstraint("exam_id", "student_id", "subject", name="uq_scores_exam_student_subject"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True, nullable=False
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # 姓名快照：列表与导出不必 join
    student_name: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    subject: Mapped[str] = mapped_column(String(16), nullable=False)
    # 分数用 Float：语文作文之类会出现 118.5 这种半分。统计时统一四舍五入到一位小数，
    # 免得浮点误差让「同分」判断失效（同分并列是名次的核心规则）
    # 缺考：value 必须为空。**不能用 0 代替** —— 0 分与没考是两件事
    value: Mapped[float | None] = mapped_column(Float, default=None)
    absent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
