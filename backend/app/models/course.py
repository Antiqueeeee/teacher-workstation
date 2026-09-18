"""学科与成绩：课程、课程班级、课程名单、课程成绩。

旧应用（`:15053`）把这块存成三层嵌套数组 **课程 → classes[] → students[]**，
外加 `homework[]` 与 `scores[]` 两个平行数组，而且直接改内存里的对象再整包 save
（`saveCourse` `:14357`）。嵌套结构在库里没法查、没法分页、没法统计，于是它那边的
成绩分析只能在前端遍历整个数组现算，及格线写死 60 分（`:14797`）、
分析阈值写死 80%/40 分（`:14811`）—— 150 分制的科目一律算错。

这里按文档 `02` §23 拆成四张**平表**，并把旧应用在这一点上的毛病逐个改掉：

1. **嵌套 → 平表**：`courses`（课程本身）/ `course_classes`（这门课教的每个班）/
   `course_students`（每个班在这门课上的名单）/ `course_scores`（课程成绩）；
2. **及格线按满分算**：`score_rate` 是得分率，及格 = 得分率 ≥ 60%（`PASS_RATIO`）。
   150 分制的 90 分与 100 分制的 60 分是同一档，与成绩模块共用同一个比例；
3. **学生是关联不是字符串**：旧应用存 `sno` 字符串（历史数据里还有数字型），
   姓名对不上就永远对不上；这里 `student_id` 是外键，`student_name` 只是快照；
4. **课程作业不再单列一份数据**：旧应用 `courses[].homework[].rate` 是**手填**的
   （`:14689`），与作业情况模块的提交率是两份互不相干的数。现在课程作业就是
   `homework` 表里带 `course_id` 的行，提交率、未交名单、名单解析全部复用同一套实现。
   *（这一条与文档 `02` §23 的迁移决策一致，见 `06-变更登记表`。）*

**为什么这四张表都不是 `class_scoped`**：课程天生跨班 —— 任课教师教 6 个班时，
一门课下面的 `course_classes` 分属不同的班，而「当前班级」这个概念在课程页面里
根本不存在（单班部署下也是）。所以 `class_id` 由钩子从课程/名单里**推出来**写进行里，
而不是靠请求上下文猜（猜错的后果是把 A 班的课算到 B 班上，且不报错）。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin
from app.models.exam import PASS_RATIO

__all__ = [
    "PASS_RATIO",
    "Course",
    "CourseClass",
    "CourseScore",
    "CourseStudent",
    "score_rate",
    "score_passed",
]


def score_rate(score: float | None, full_marks: int | None) -> float | None:
    """得分率（0–100，一位小数）。满分缺失或 <= 0 时返回 None —— 不是 0%。

    **跨考试比较只能看得分率**：150 分制的数学 120 分与 100 分制的地理 80 分
    直接比大小没有意义。成绩模块用的是同一套比例（`models/exam.py:PASS_RATIO`）。
    """
    if score is None or not full_marks or full_marks <= 0:
        return None
    return round(score / full_marks * 100, 1)


def score_passed(score: float | None, full_marks: int | None) -> bool:
    """这门课这一场是否及格：**按满分算的得分率**，不是写死的 60 分。

    满分缺失时不算及格（不假装通过）—— 与 `score_stats.meets` 的取法一致。
    """
    rate = score_rate(score, full_marks)
    return rate is not None and rate >= PASS_RATIO * 100


class Course(Base, TimestampMixin, SoftDeleteMixin):
    """一门课程（如「数学」「体育与健康」）。"""

    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    # 科目取自词表 SUBJECTS；自定义课程（如「体育与健康」）可以留空
    subject: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    # 任课教师。旧应用没有这个字段，课表里却有 —— 任课教师本人用这份工作台时，
    # 「我教哪几门」要能一眼看出来
    teacher: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    hours: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    term: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    classes = relationship(
        "CourseClass",
        cascade="all, delete-orphan",
        lazy="selectin",
        back_populates="course",
        order_by="CourseClass.id",
    )

    @property
    def class_count(self) -> int:
        return len(self.classes)


class CourseClass(Base, TimestampMixin, SoftDeleteMixin):
    """「这门课在这个班上」—— 课程的班级块。

    旧应用的 `classes[]` 元素，除了班级本身还带着**那个班的**班主任、课代表
    联系方式与课程进度（`:14757`）。这三样是任课教师真正要用的东西（联系不上班主任
    就找不到人），所以照原样保留在这一行上。
    """

    __tablename__ = "course_classes"
    __table_args__ = (
        # 同一门课同一个班只有一行（未删除的）。用**部分**唯一索引：
        # 软删除的行还占着唯一键的话，「删掉再加回来」会直接撞约束报 500
        Index(
            "uq_course_classes_course_class",
            "course_id",
            "class_id",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # 班级名快照：列表、导出、看板不必每行去 join classes
    class_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    head_teacher: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    head_teacher_phone: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    representative: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    rep_phone: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    progress: Mapped[str] = mapped_column(String(128), default="", nullable=False)

    course = relationship("Course", back_populates="classes")
    students = relationship(
        "CourseStudent",
        cascade="all, delete-orphan",
        lazy="selectin",
        back_populates="course_class",
        order_by="CourseStudent.id",
    )

    @property
    def course_name(self) -> str:
        return self.course.name if self.course else ""

    @property
    def student_count(self) -> int:
        return len(self.students)


class CourseStudent(Base, TimestampMixin, SoftDeleteMixin):
    """一个学生在这门课的这个班上的名单行。"""

    __tablename__ = "course_students"
    __table_args__ = (
        Index(
            "uq_course_students_class_student",
            "course_class_id",
            "student_id",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_class_id: Mapped[int] = mapped_column(
        ForeignKey("course_classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # 与 course_class 的班级一致：由钩子写定，不是用户填的（见 services/course_service.py）
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # 姓名快照：列表与导出不必 join
    student_name: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    course_class = relationship("CourseClass", back_populates="students")
    student = relationship("Student", lazy="selectin")

    @property
    def sno(self) -> str:
        return self.student.sno if self.student else ""

    @property
    def course_name(self) -> str:
        parent = self.course_class
        return parent.course.name if parent and parent.course else ""

    @property
    def class_name(self) -> str:
        parent = self.course_class
        return parent.class_name if parent else ""


class CourseScore(Base, TimestampMixin, SoftDeleteMixin):
    """课程成绩：一个学生、一门课、一场考试的一格分数。

    `full_marks`（满分）是**每行都带**的正式字段：旧应用把它写死成 150 的上限、
    及格线写死成 60 分，170 分制的科目就没法录。同一场考试的多行通常填同一个满分，
    表单会拿同场已有的值当默认（见 `services/course_service.py`）。
    """

    __tablename__ = "course_scores"
    __table_args__ = (
        Index(
            "uq_course_scores_exam_student",
            "course_id",
            "exam_name",
            "student_id",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # 成绩属于哪个班：由学生所属的班推出来（课程可能教多个班）
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True, nullable=False
    )
    student_name: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    exam_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # 考试日期：生长曲线按它排（旧应用按录入顺序排，「本场」与「上一场」会反）
    exam_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    # 列的默认值是 100；真正好用的默认值由服务层给（同场考试已有记录 → 该科目词表默认，
    # 见 services/course_service.py:default_full_marks）
    full_marks: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    note: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    course = relationship("Course", lazy="selectin")
    student = relationship("Student", lazy="selectin")

    @property
    def sno(self) -> str:
        return self.student.sno if self.student else ""

    @property
    def course_name(self) -> str:
        return self.course.name if self.course else ""

    @property
    def rate(self) -> float | None:
        """得分率（%）—— 及格、优秀、跨考试比较都读它。"""
        return score_rate(self.score, self.full_marks)

    @property
    def passed(self) -> bool:
        return score_passed(self.score, self.full_marks)
