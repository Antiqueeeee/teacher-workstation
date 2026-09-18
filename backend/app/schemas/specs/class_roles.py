"""班级角色类的表声明：班委、团员、值日。

字段与词表都照旧应用的 `CFG_*` 逐字搬过来（选项文字不能改，否则老师的历史数据会对不上），
只做两处结构性调整：学生改 `student_id` 引用、值日成员改关联子表。
"""

from __future__ import annotations

from app.models.classroom import (
    APPRAISALS,
    DUTY_AREAS,
    DUTY_CHECKS,
    WEEKDAYS,
    YOUTH_FEES,
    YOUTH_POSTS,
    Cadre,
    DutyGroup,
    YouthMember,
)
from app.schemas.table_spec import ColumnSpec, FieldSpec, TableSpec
from app.services.classroom_service import apply_duty, link_cadre_student, link_youth_student

CADRE = TableSpec(
    key="cadres",
    title="班委成员",
    entity="班委",
    model=Cadre,
    columns=(
        ColumnSpec("post", "职务", w="104px"),
        ColumnSpec("student_name", "姓名", w="110px"),
        ColumnSpec("duty", "主要职责"),
        ColumnSpec("term", "任期", w="132px"),
        # 联系电话/学号取自学生档案（派生属性，不给排序）
        ColumnSpec("phone", "联系电话", w="118px", sortable=False),
        ColumnSpec("appraise", "履职评价", w="92px"),
    ),
    fields=(
        FieldSpec("student_name", "学生姓名", required=True, hint="重名时会提示确认"),
        FieldSpec("post", "职务", required=True, hint="如 班长 / 学习委员"),
        FieldSpec("term", "任期", hint="如 2026-2027学年"),
        FieldSpec("start_date", "任职开始", type="date"),
        FieldSpec("end_date", "任职结束", type="date", hint="留空表示仍在任"),
        FieldSpec("appraise", "履职评价", type="select", options=APPRAISALS, default="良好"),
        FieldSpec("duty", "主要职责", type="textarea", full=True),
    ),
    search_keys=("student_name", "post", "duty"),
    filter_keys=("appraise", "post"),
    default_sort=("id", 1),
    dedupe_keys=("student_name", "post"),  # 同一人同一职务重复导入不翻倍
    extra_keys=("student_id", "sno", "phone"),
    before_save=link_cadre_student,
)

YOUTH = TableSpec(
    key="youth_members",
    title="团员名册",
    entity="团员",
    model=YouthMember,
    columns=(
        ColumnSpec("student_name", "姓名", w="110px"),
        ColumnSpec("sno", "学号", w="92px", sortable=False),
        ColumnSpec("gender", "性别", w="62px", sortable=False),
        ColumnSpec("join_date", "入团时间", w="106px", numeric=True),
        ColumnSpec("branch", "所属团支部", w="150px"),
        ColumnSpec("post", "团内职务", w="96px"),
        ColumnSpec("fee", "团费", w="76px"),
        ColumnSpec("note", "备注"),
    ),
    fields=(
        FieldSpec("student_name", "学生", required=True),
        FieldSpec("join_date", "入团时间", type="date", hint="留空按今天"),
        FieldSpec("branch", "所属团支部", hint="如 高二(3)班团支部"),
        FieldSpec("post", "团内职务", type="select", options=YOUTH_POSTS, default="团员"),
        FieldSpec("fee", "团费缴纳", type="select", options=YOUTH_FEES, default="已缴"),
        FieldSpec("note", "备注", type="textarea", full=True),
    ),
    search_keys=("student_name", "branch", "note"),
    filter_keys=("fee", "post"),
    default_sort=("join_date", -1),
    dedupe_keys=("student_name",),  # 一个人只会有一条团员记录
    extra_keys=("student_id", "sno", "gender"),
    before_save=link_youth_student,
)

DUTY = TableSpec(
    key="duty_groups",
    title="值日安排",
    entity="值日",
    model=DutyGroup,
    columns=(
        # 显示用**星期几的汉字**（模型上有 `weekday` 这一列）；排序仍走 `weekday_no`
        # —— 按汉字排是按码位排，星期五会跑到星期一前面。所以这一列不给点排序
        ColumnSpec("weekday", "星期", w="84px", sortable=False),
        ColumnSpec("group_name", "小组", w="76px"),
        ColumnSpec("area", "负责区域", w="126px"),
        ColumnSpec("members_cache", "值日成员"),
        ColumnSpec("leader_name", "组长", w="84px"),
        ColumnSpec("check", "检查结果", w="92px"),
    ),
    fields=(
        FieldSpec("weekday", "星期", type="select", options=WEEKDAYS, default="星期一"),
        FieldSpec("group_name", "小组", hint="如 第1组"),
        FieldSpec("area", "负责区域", type="select", options=DUTY_AREAS, required=True),
        FieldSpec("leader_name", "组长", hint="填学生姓名"),
        FieldSpec("check", "检查结果", type="select", options=DUTY_CHECKS, default="合格"),
        FieldSpec(
            "members_text",
            "值日成员",
            type="textarea",
            required=True,
            full=True,
            hint="多人用顿号分隔，如 张三、李四；认不出的学生会报错",
        ),
        # 排序/筛选用的星期序号（由钩子从「星期」算出来，不让人填）
        FieldSpec("weekday_no", "星期序号", type="number", editable=False),
    ),
    search_keys=("members_cache", "area", "leader_name"),
    filter_keys=("weekday_no", "check", "area"),
    default_sort=("weekday_no", 1),
    dedupe_keys=("weekday", "area", "group_name"),
    extra_keys=("members_cache", "member_count"),
    before_save=apply_duty,
)
