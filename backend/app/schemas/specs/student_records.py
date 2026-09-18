"""学生事务类表的声明：违纪、特殊体质、助学金。

词表照旧应用的 `CFG_*` 逐字搬；助学金金额以分存整数（输入仍是元），
特殊体质一人一条（部分唯一索引）。
"""

from __future__ import annotations

from app.models.discipline import LEVELS, STATUSES, Discipline
from app.models.discipline import TYPES as DISCIPLINE_TYPES
from app.models.welfare import (
    GRANT_LEVELS,
    GRANT_STATUSES,
    GRANT_TYPES,
    HEALTH_LEVELS,
    Grant,
    HealthRecord,
)
from app.schemas.table_spec import ColumnSpec, FieldSpec, TableSpec
from app.services.classroom_service import (
    apply_grant,
    link_discipline_student,
    link_health_student,
)

DISCIPLINE = TableSpec(
    key="disciplines",
    title="违纪记录",
    entity="违纪记录",
    model=Discipline,
    columns=(
        ColumnSpec("date", "日期", w="104px", numeric=True),
        ColumnSpec("student_name", "学生", w="100px"),
        ColumnSpec("type", "违纪类型", w="104px"),
        ColumnSpec("detail", "具体情况"),
        ColumnSpec("level", "程度", w="70px"),
        ColumnSpec("handling", "处理措施", w="190px", sortable=False),
        ColumnSpec("status", "状态", w="88px"),
    ),
    fields=(
        FieldSpec("date", "发生日期", type="date", required=True),
        FieldSpec("student_name", "学生", required=True),
        FieldSpec("type", "违纪类型", type="select", options=DISCIPLINE_TYPES, required=True),
        FieldSpec("level", "违纪程度", type="select", options=LEVELS, default="一般"),
        FieldSpec("status", "处理状态", type="select", options=STATUSES, default="整改中"),
        FieldSpec("detail", "具体情况", type="textarea", required=True, full=True),
        FieldSpec(
            "handling",
            "处理措施",
            type="textarea",
            full=True,
            hint="如：谈话教育并书面检讨，联系家长共同教育",
        ),
        FieldSpec("recorder", "记录人"),
    ),
    search_keys=("student_name", "type", "detail", "handling"),
    filter_keys=("level", "status", "type"),
    default_sort=("date", -1),
    dedupe_keys=("date", "student_name", "type"),  # 同一天同一人同一类型视为同一条
    extra_keys=("student_id", "sno", "open_case"),
    before_save=link_discipline_student,
)

HEALTH = TableSpec(
    key="health_records",
    title="特殊体质",
    entity="健康档案",
    model=HealthRecord,
    columns=(
        ColumnSpec("student_name", "学生", w="100px"),
        ColumnSpec("type", "体质/病症", w="140px"),
        ColumnSpec("detail", "具体情况"),
        ColumnSpec("limit_note", "活动限制", w="180px", sortable=False),
        ColumnSpec("contact", "紧急联系人", w="112px"),
        ColumnSpec("phone", "联系电话", w="118px"),
        ColumnSpec("level", "关注等级", w="104px"),
    ),
    fields=(
        FieldSpec("student_name", "学生", required=True, hint="一个人只建一条"),
        FieldSpec("type", "体质/病症类型", required=True, hint="如 哮喘 / 过敏体质"),
        FieldSpec(
            "level",
            "关注等级",
            type="select",
            options=HEALTH_LEVELS,
            default="需重点关注",
            hint="「需重点关注」的会在代课简报里醒目提示",
        ),
        FieldSpec("record_date", "建档日期", type="date", hint="留空按今天"),
        FieldSpec("contact", "紧急联系人", hint="如 张建国（父）"),
        FieldSpec("phone", "紧急联系电话"),
        FieldSpec(
            "detail",
            "具体情况",
            type="textarea",
            required=True,
            full=True,
            hint="诱因、症状、日常用药等",
        ),
        FieldSpec(
            "emergency",
            "应急处置措施",
            type="textarea",
            required=True,
            full=True,
            hint="发作时应如何处理",
        ),
        FieldSpec(
            "limit_note",
            "体育与活动限制",
            type="textarea",
            full=True,
            hint="如：禁止长跑、剧烈耐力运动",
        ),
    ),
    search_keys=("student_name", "type", "detail"),
    filter_keys=("level", "type"),
    default_sort=("id", -1),
    dedupe_keys=("student_name",),
    extra_keys=("student_id", "sno"),
    before_save=link_health_student,
)

GRANT = TableSpec(
    key="grants",
    title="助学金",
    entity="资助记录",
    model=Grant,
    columns=(
        ColumnSpec("student_name", "学生", w="100px"),
        ColumnSpec("type", "资助类型", w="128px"),
        ColumnSpec("level", "等级", w="66px"),
        # 金额用派生属性展示（库里存的是分），库里按 amount_cents 存
        ColumnSpec("amount_display", "金额（元）", w="96px", numeric=True, sortable=False),
        ColumnSpec("semester", "学期", w="148px"),
        ColumnSpec("reason", "申请理由"),
        ColumnSpec("apply_date", "申请日期", w="104px", numeric=True),
        ColumnSpec("status", "状态", w="82px"),
    ),
    fields=(
        FieldSpec("student_name", "学生", required=True),
        FieldSpec("type", "资助类型", type="select", options=GRANT_TYPES, required=True),
        FieldSpec("level", "等级", type="select", options=GRANT_LEVELS, default="—"),
        FieldSpec(
            "amount_cents",
            "金额（元）",
            type="money",
            hint="填 0 表示减免。按「元」填，库里存成分 —— 浮点算钱会出现小数尾数",
        ),
        FieldSpec("semester", "所属学期", hint="如 2026学年第一学期"),
        FieldSpec("apply_date", "申请日期", type="date"),
        FieldSpec("status", "状态", type="select", options=GRANT_STATUSES, default="申请中"),
        FieldSpec("reason", "申请理由", type="textarea", required=True, full=True),
        FieldSpec("note", "备注", type="textarea", full=True),
    ),
    search_keys=("student_name", "type", "reason"),
    filter_keys=("type", "status", "semester"),
    default_sort=("apply_date", -1),
    dedupe_keys=("student_name", "type", "semester"),
    extra_keys=("student_id", "sno", "amount_yuan", "amount_display", "pending"),
    before_save=apply_grant,
)
