"""学科与成绩的表声明：课程 / 课程班级 / 课程名单 / 课程成绩。

`courses` 不是班级范围的（课程天生跨班）；另外三张表**有 class_id，但班级由钩子从
课程与名单里推出来**（`class_from_hook=True`，见 `TableSpec` 的说明）—— 它们的班级
与「当前班级」无关，所以不从请求上下文猜，也不该因为多班而报「还没有班级切换界面」。

**界面上看不到任何 id**：填的是「课程名 + 班级名 + 学生姓名」，
由 `services/course_service.py` 的钩子解析成 `course_id` / `class_id` / `student_id`
—— 与「学生姓名」「未交名单」同一套做法。`course_name` / `class_name` 在
`course_students` 与 `course_scores` 上是**虚拟输入字段**（模型上只有同名只读属性），
钩子负责把它们的值摘掉再换成 id，所以那两个表的「新增」表单里能填名字。
"""

from __future__ import annotations

from app.models.course import Course, CourseClass, CourseScore, CourseStudent
from app.models.vocab import SUBJECTS
from app.schemas.table_spec import ColumnSpec, FieldSpec, TableSpec
from app.services.course_service import (
    apply_course_class,
    apply_course_score,
    apply_course_student,
)

# 四个表共用的三个「填名字」字段 —— 抄三遍的话，三处的提示词迟早变成三种说法
COURSE_NAME_FIELD = FieldSpec("course_name", "课程", required=True, hint="填课程名称，如 数学")
CLASS_NAME_FIELD = FieldSpec(
    "class_name", "班级", required=True, hint="填班级名称，如 高二(3)班（在「设置」里看现有班级）"
)

COURSE = TableSpec(
    key="courses",
    title="学科与成绩",
    entity="课程",
    model=Course,
    columns=(
        ColumnSpec("name", "课程", w="120px"),
        ColumnSpec("subject", "科目", w="70px"),
        ColumnSpec("teacher", "任课教师", w="96px"),
        ColumnSpec("hours", "课时", w="62px", numeric=True),
        ColumnSpec("term", "学期", w="150px"),
        ColumnSpec("note", "备注"),
    ),
    fields=(
        FieldSpec("name", "课程名称", required=True, hint="如：数学、体育与健康"),
        FieldSpec("subject", "科目", type="select", options=SUBJECTS, hint="留空表示自定义课程"),
        FieldSpec("teacher", "任课教师", hint="留空就是你自己"),
        FieldSpec("hours", "课时数", type="number", default=0),
        FieldSpec("term", "学期", hint="如：2026-2027学年第一学期"),
        FieldSpec("note", "备注", type="textarea", full=True),
    ),
    search_keys=("name", "teacher", "note"),
    filter_keys=("subject",),
    default_sort=("id", 1),
    dedupe_keys=("name", "term"),  # 同一学期同一门课，重复导入不翻倍
    class_scoped=False,
    extra_keys=("class_count",),
)


COURSE_CLASS = TableSpec(
    key="course_classes",
    title="课程班级",
    entity="课程班级",
    model=CourseClass,
    columns=(
        ColumnSpec("course_name", "课程", w="110px", sortable=False),
        ColumnSpec("class_name", "班级", w="110px"),
        ColumnSpec("student_count", "人数", w="62px", numeric=True, sortable=False),
        ColumnSpec("head_teacher", "班主任", w="90px"),
        ColumnSpec("head_teacher_phone", "班主任电话", w="120px"),
        ColumnSpec("representative", "课代表", w="90px"),
        ColumnSpec("rep_phone", "课代表电话", w="120px"),
        ColumnSpec("progress", "课程进度"),
    ),
    fields=(
        COURSE_NAME_FIELD,
        CLASS_NAME_FIELD,
        FieldSpec("head_teacher", "班主任", hint="这个班的班主任是谁（任课教师找人有用时最需要它）"),
        FieldSpec("head_teacher_phone", "班主任电话"),
        FieldSpec("representative", "课代表"),
        FieldSpec("rep_phone", "课代表电话"),
        FieldSpec("progress", "课程进度", hint="如：第三章 三角函数（3/6 课时）"),
    ),
    search_keys=("class_name", "head_teacher", "representative", "progress"),
    filter_keys=(),
    default_sort=("id", 1),
    dedupe_keys=(),
    # 班级从「这门课教哪个班」推出来（钩子写），不从请求上下文猜 —— 见 TableSpec.class_from_hook
    class_from_hook=True,
    extra_keys=("course_id", "student_count"),
    before_save=apply_course_class,
)


COURSE_STUDENT = TableSpec(
    key="course_students",
    title="课程名单",
    entity="名单行",
    model=CourseStudent,
    columns=(
        ColumnSpec("course_name", "课程", w="110px", sortable=False),
        ColumnSpec("class_name", "班级", w="110px", sortable=False),
        ColumnSpec("student_name", "学生", w="92px"),
        ColumnSpec("sno", "学号", w="100px", sortable=False),
    ),
    fields=(
        COURSE_NAME_FIELD,
        CLASS_NAME_FIELD,
        FieldSpec("student_name", "学生", required=True, hint="填学生姓名；重名时会提示确认"),
    ),
    search_keys=("student_name",),
    filter_keys=(),
    default_sort=("id", 1),
    dedupe_keys=(),
    class_from_hook=True,  # 同上：班级来自课程班级块
    extra_keys=("student_id",),
    before_save=apply_course_student,
)


COURSE_SCORE = TableSpec(
    key="course_scores",
    title="课程成绩",
    entity="课程成绩",
    model=CourseScore,
    columns=(
        ColumnSpec("course_name", "课程", w="110px", sortable=False),
        ColumnSpec("exam_name", "考试", w="130px"),
        ColumnSpec("exam_date", "日期", w="104px", numeric=True),
        ColumnSpec("student_name", "学生", w="92px"),
        ColumnSpec("score", "分数", w="70px", numeric=True),
        ColumnSpec("full_marks", "满分", w="70px", numeric=True),
        ColumnSpec("rate", "得分率", w="80px", numeric=True, sortable=False),
        ColumnSpec("passed", "及格", w="62px", sortable=False),
        ColumnSpec("note", "备注"),
    ),
    fields=(
        COURSE_NAME_FIELD,
        FieldSpec("exam_name", "考试名称", required=True, hint="同一场考试填同一个名字，如 第一次月考"),
        FieldSpec("student_name", "学生", required=True, hint="填学生姓名；本课程教的班以外的学生录不进来"),
        FieldSpec("score", "分数", type="number", required=True),
        FieldSpec(
            "full_marks",
            "满分",
            type="number",
            hint="留空按同场考试已有记录，再没有就按科目默认（语数英 150，其余 100）",
        ),
        FieldSpec("exam_date", "考试日期", type="date", hint="留空按今天；生长曲线按日期排"),
        FieldSpec("note", "备注"),
        # 派生值：得分率与及格（按满分算），不让人填，但要出现在导出里 ——
        # 导出文件再导回来时这两列会被认出来并忽略，而不是报「认不出这一列」
        FieldSpec("rate", "得分率（%）", type="number", editable=False, hint="分数 ÷ 满分"),
        FieldSpec("passed", "是否及格", type="checkbox", editable=False, hint="得分率 ≥ 60%"),
    ),
    search_keys=("exam_name", "student_name", "note"),
    filter_keys=(),
    default_sort=("exam_date", -1),
    dedupe_keys=(),  # 同一场同一个学生重复录入由钩子报错，见 course_service.apply_course_score
    class_from_hook=True,  # 成绩的班级 = 该学生在这个课程里所属的班
    extra_keys=("student_id", "sno"),
    before_save=apply_course_score,
)
