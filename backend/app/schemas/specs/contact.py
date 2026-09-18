"""联系人类表的声明：家长通讯（一学生多监护人）、家长联系日志（沟通留档）。

类型定义在 `schemas/table_spec.py`，汇总与访问器在 `schemas/registry.py`。
"""

from __future__ import annotations

from app.models.contact import CATEGORIES as CONTACT_CATEGORIES
from app.models.contact import CHANNELS as CONTACT_CHANNELS
from app.models.contact import DIRECTIONS as CONTACT_DIRECTIONS
from app.models.contact import RESULTS as CONTACT_RESULTS
from app.models.contact import ContactLog
from app.models.guardian import ROLES as GUARDIAN_ROLES
from app.models.guardian import Guardian
from app.schemas.table_spec import ColumnSpec, FieldSpec, TableSpec
from app.services.contact_service import link_contact_student
from app.services.guardian_service import link_student

GUARDIAN = TableSpec(
    key="guardians",
    model=Guardian,
    title="家长通讯",
    entity="监护人",
    columns=(
        ColumnSpec("student_name", "学生", w="90px"),
        ColumnSpec("name", "姓名"),
        ColumnSpec("role", "关系", w="76px"),
        ColumnSpec("phone", "电话", w="130px"),
        ColumnSpec("job", "工作单位", w="130px"),
        ColumnSpec("is_primary", "主要联系人", w="100px"),
        ColumnSpec("note", "备注"),
    ),
    fields=(
        # 表单里填的是**学生姓名**，不是 id —— 老师记的是名字。
        # student_id / class_id 由 services/guardian_service.py 的 before_save 解析出来，
        # 同名学生会明确报错让人确认，而不是随便挂到一个同名学生身上
        FieldSpec("student_name", "学生", required=True, hint="填学生姓名；重名时会提示确认"),
        FieldSpec("name", "监护人姓名", required=True),
        FieldSpec("role", "关系", type="select", options=GUARDIAN_ROLES, default="其他"),
        FieldSpec("phone", "电话", hint="手机号或固定电话"),
        FieldSpec("job", "工作单位"),
        FieldSpec("wechat", "微信/其他联系标识"),
        FieldSpec("is_primary", "主要联系人", type="checkbox", default=False, hint="紧急情况优先打这一个"),
        FieldSpec("note", "备注", type="textarea", full=True),
    ),
    search_keys=("student_name", "name", "phone", "job"),
    filter_keys=("role", "is_primary"),
    default_sort=("id", -1),
    class_scoped=True,
    dedupe_keys=("student_name", "name"),  # 同一学生的同一位监护人，重复导入不翻倍
    extra_keys=("student_id",),
    # 把老师填的「学生姓名」解析成 student_id，并带出 class_id 与冗余姓名
    before_save=link_student,
)


CONTACT = TableSpec(
    key="contacts",
    title="家长联系日志",
    entity="联系记录",
    model=ContactLog,
    columns=(
        ColumnSpec("date", "日期", w="104px", numeric=True),
        ColumnSpec("student_name", "学生", w="92px"),
        ColumnSpec("channel", "方式", w="76px"),
        ColumnSpec("direction", "方向", w="76px"),
        ColumnSpec("category", "事由", w="80px"),
        ColumnSpec("result", "结果", w="84px"),
        ColumnSpec("content", "沟通内容"),
        ColumnSpec("needs_follow_up", "待跟进", w="80px"),
        # 附件数是派生值（媒体服务批量填），不能声明为可排序
        ColumnSpec("attachment_count", "附件", w="64px", numeric=True, sortable=False),
    ),
    fields=(
        FieldSpec("date", "日期", type="date", required=True),
        FieldSpec(
            "student_name",
            "学生",
            required=True,
            hint="填学生姓名；重名时会提示确认",
        ),
        FieldSpec("channel", "联系方式", type="select", options=CONTACT_CHANNELS, default="电话"),
        FieldSpec(
            "direction",
            "联系方向",
            type="select",
            options=CONTACT_DIRECTIONS,
            default="去电",
            hint="谁联系谁 —— 回看时最有用的是「打了几次都没接」这种",
        ),
        FieldSpec("category", "事由", type="select", options=CONTACT_CATEGORIES, default="其他"),
        FieldSpec(
            "result",
            "结果",
            type="select",
            options=CONTACT_RESULTS,
            default="已沟通",
        ),
        FieldSpec(
            "content",
            "沟通内容",
            type="textarea",
            full=True,
            hint="聊了什么、约定了什么",
        ),
        FieldSpec("feedback", "家长反馈", type="textarea", full=True),
        FieldSpec(
            "needs_follow_up",
            "需要再次联系",
            type="checkbox",
            default=False,
            hint="勾上会出现在首页「需要我跟进」里",
        ),
        FieldSpec("note", "备注", type="textarea", full=True),
    ),
    search_keys=("student_name", "content", "feedback", "note"),
    filter_keys=("channel", "direction", "category", "result", "needs_follow_up"),
    default_sort=("date", -1),
    dedupe_keys=("date", "student_name", "channel"),  # 同一天同一人同一渠道视为同一条
    extra_keys=("student_id", "sno", "attachment_count"),
    # 这条表支持挂附件（照片 + 录音归档）—— 通用列表据此显示附件数与入口
    media_owner=True,
    before_save=link_contact_student,
)
