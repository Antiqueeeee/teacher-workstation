"""教学学业类表的声明：作业情况、出勤记录、考试管理。

类型定义在 `schemas/table_spec.py`，汇总与访问器在 `schemas/registry.py`。
"""

from __future__ import annotations

from app.models.attendance import ATTENDANCE_TYPES, FOLLOW_UP_STATES, PERIODS, Attendance
from app.models.exam import EXAM_KINDS, Exam
from app.models.homework import QUALITIES, RATE_MODES, SUBJECTS, Homework
from app.schemas.table_spec import ColumnSpec, FieldSpec, TableSpec
from app.services.attendance_service import apply_attendance
from app.services.exam_service import apply_exam
from app.services.homework_service import apply_homework
HOMEWORK = TableSpec(
    key="homework",
    model=Homework,
    title="作业情况",
    entity="作业",
    columns=(
        ColumnSpec("date", "布置日期", w="104px", numeric=True),
        ColumnSpec("subject", "科目", w="70px"),
        ColumnSpec("content", "作业内容"),
        ColumnSpec("total", "应交", w="62px", numeric=True),
        # 派生属性（关系算出来的）**不能声明为可排序**：它构不出 SQL 表达式，
        # 点一下表头就是 AttributeError → 500。列表里照常显示，只是不给点
        ColumnSpec("unsubmitted_names", "未交名单", sortable=False),
        ColumnSpec("rate", "提交率", w="78px", numeric=True),
        ColumnSpec("rate_auto", "按名单算", w="84px", numeric=True, sortable=False),
        ColumnSpec("quality", "质量", w="62px"),
    ),
    fields=(
        FieldSpec("date", "布置日期", type="date", required=True),
        FieldSpec("subject", "科目", type="select", options=SUBJECTS, required=True),
        FieldSpec("content", "作业内容", type="textarea", full=True, required=True),
        FieldSpec("deadline", "截止时间", hint="如 次日早读前"),
        # 课程作业：填课程名就把这条作业挂到那门课上（学科与成绩页会按课程汇总）。
        # 虚拟字段 —— 钩子把它换成 course_id，见 services/homework_service.py
        FieldSpec(
            "course_name",
            "所属课程",
            hint="任课教师布置的作业填课程名（如 数学）；班主任的常规作业留空",
        ),
        FieldSpec("total", "应交人数", type="number", hint="留空按当前全班人数（存成快照，之后不再变）"),
        FieldSpec(
            "unsubmitted_names",
            "未交名单",
            type="textarea",
            full=True,
            hint="多人用顿号分隔；全部交齐填「无」。提交率由它自动算出，不用手填",
        ),
        FieldSpec(
            "rate_mode",
            "提交率模式",
            type="select",
            options=RATE_MODES,
            default="自动",
            hint="手工只用于特殊情况（如学校要求按人数上报）",
        ),
        FieldSpec("rate_manual", "手工提交率（%）", type="number"),
        # 计算出来的值：不让人填（editable=False），但声明成字段，导出的文件再导回来时
        # 这一列会被认出来并忽略，而不是报「认不出这一列」
        FieldSpec("rate", "提交率（%）", type="number", editable=False),
        # 按名单算的值：与生效提交率并排放在导出里，手工覆盖时一眼看出两个数不一致
        FieldSpec(
            "rate_auto",
            "按名单算（%）",
            type="number",
            editable=False,
            hint="与「提交率」不一致时，说明手工覆盖的值与未交名单对不上",
        ),
        FieldSpec("quality", "完成质量", type="select", options=QUALITIES, default="良"),
        FieldSpec("teacher", "布置教师"),
        # course_id 由钩子从「所属课程」解析出来，不让人填；声明成字段是为了
        # 它出现在导出里、也能用 filter.course_id 精确筛选（学科与成绩页就是这么取的）
        FieldSpec("course_id", "课程（编号）", type="number", editable=False),
    ),
    search_keys=("content", "teacher"),
    filter_keys=("subject", "quality", "course_id"),
    extra_keys=("course_name", "course_id"),
    default_sort=("date", -1),
    dedupe_keys=("date", "subject", "content"),  # 同一天同一科同一份作业，重复导入不翻倍
    before_save=apply_homework,
)


ATTENDANCE = TableSpec(
    key="attendance",
    model=Attendance,
    title="出勤记录",
    entity="考勤记录",
    columns=(
        ColumnSpec("date", "日期", w="104px", numeric=True),
        ColumnSpec("student_name", "学生", w="92px"),
        ColumnSpec("type", "类型", w="70px"),
        ColumnSpec("period", "节次", w="92px"),
        ColumnSpec("reason", "事由"),
        ColumnSpec("handled", "跟进状态", w="92px"),
        ColumnSpec("handled_note", "处理情况"),
    ),
    fields=(
        FieldSpec("date", "日期", type="date", required=True),
        # 与家长通讯同一套做法：填姓名，钩子解析成 student_id，重名时明确报错
        FieldSpec("student_name", "学生", required=True, hint="填学生姓名；重名时会提示确认"),
        FieldSpec("type", "类型", type="select", options=ATTENDANCE_TYPES, required=True),
        FieldSpec(
            "period",
            "节次",
            type="select",
            options=PERIODS,
            default="全天",
            hint="只作留档，不参与统计",
        ),
        FieldSpec("reason", "事由", type="textarea", full=True, hint="如：发热就医、家中有事"),
        FieldSpec(
            "handled",
            "跟进状态",
            type="select",
            options=FOLLOW_UP_STATES,
            hint="留空按类型自动判定：旷课为「待联系」，其余为「无需联系」",
        ),
        FieldSpec(
            "handled_note",
            "处理情况",
            type="textarea",
            full=True,
            hint="如：已电话联系家长确认",
        ),
    ),
    search_keys=("student_name", "reason", "handled_note"),
    filter_keys=("type", "period", "handled"),
    default_sort=("date", -1),
    # 刻意不软删除：UNIQUE(date, student_id) 与软删除冲突 —— 删掉的记录仍占着唯一键，
    # 同一天同一个学生就再也登记不进来（见 models/attendance.py）
    soft_delete=False,
    dedupe_keys=("date", "student_name"),  # 一天一个学生只有一条，重复导入不翻倍
    extra_keys=("student_id",),            # 点名表要按学生 id 匹配
    before_save=apply_attendance,
)


EXAM = TableSpec(
    key="exams",
    model=Exam,
    title="考试管理",
    entity="考试",
    columns=(
        ColumnSpec("name", "考试名称"),
        ColumnSpec("date", "日期", w="104px", numeric=True),
        ColumnSpec("kind", "类型", w="80px"),
        ColumnSpec("note", "备注"),
    ),
    fields=(
        FieldSpec("name", "考试名称", required=True, full=True, hint="如：2026 学年第二学期期末考"),
        FieldSpec("date", "考试日期", type="date", required=True),
        FieldSpec("kind", "考试类型", type="select", options=EXAM_KINDS, default="月考"),
        FieldSpec("note", "备注", type="textarea", full=True),
    ),
    search_keys=("name", "note"),
    filter_keys=("kind",),
    default_sort=("date", -1),
    dedupe_keys=("date", "name"),  # 同一天同名视为同一场，重复导入不翻倍
    # 新建考试时按词表把科目表建出来（考试考哪几科必须当场确定，见 exam_service）
    before_save=apply_exam,
)
