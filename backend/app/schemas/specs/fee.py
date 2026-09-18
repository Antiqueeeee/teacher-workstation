"""班级费用的表声明：收费项目 / 缴费记录 / 收支流水。

三张表：`fee_categories`（项目与每人应缴标准）、`fee_records`（一个学生一条应缴/实缴）、
`fee_ledger`（收支流水）。**金额都是分**（字段类型 `money`，界面填元）。
"""

from __future__ import annotations

from app.models.fee import FEE_STATUSES, LEDGER_KINDS, FeeCategory, FeeLedger, FeeRecord
from app.schemas.table_spec import ColumnSpec, FieldSpec, TableSpec
from app.services.fee_service import apply_category, apply_ledger, apply_record

FEE_CATEGORY = TableSpec(
    key="fee_categories",
    title="收费项目",
    entity="收费项目",
    model=FeeCategory,
    columns=(
        ColumnSpec("name", "费用名称", w="140px"),
        ColumnSpec("amount_yuan", "每人应缴（元）", w="130px", numeric=True, sortable=False),
        ColumnSpec("note", "收费说明"),
    ),
    fields=(
        FieldSpec("name", "费用名称", required=True, hint="如 班费"),
        FieldSpec(
            "amount_cents",
            "每人应缴（元）",
            type="money",
            hint="按元填，库里存分。改它**不会**自动改写已收过的记录（应缴是收钱时的约定）",
        ),
        FieldSpec("note", "收费说明", type="textarea", full=True, hint="如 每学期一次性收取，用于班级公共支出"),
    ),
    search_keys=("name", "note"),
    filter_keys=(),
    default_sort=("id", 1),
    dedupe_keys=("name",),
    extra_keys=("amount_yuan", "amount_cents"),
    before_save=apply_category,
)

FEE_RECORD = TableSpec(
    key="fee_records",
    title="缴费记录",
    entity="缴费记录",
    model=FeeRecord,
    columns=(
        ColumnSpec("student_name", "学生", w="100px"),
        ColumnSpec("should_pay_yuan", "应缴（元）", w="100px", numeric=True, sortable=False),
        ColumnSpec("paid_yuan", "实缴（元）", w="100px", numeric=True, sortable=False),
        ColumnSpec("status", "状态", w="80px", sortable=False),
        ColumnSpec("date", "缴费日期", w="104px", numeric=True),
        ColumnSpec("note", "备注", w="140px"),
    ),
    fields=(
        FieldSpec("category_id", "收费项目", type="number", required=True, hint="填收费项目的 id（在「收费项目」页看）"),
        FieldSpec("student_name", "学生", required=True),
        FieldSpec("should_pay_cents", "应缴（元）", type="money", hint="留空按收费项目的标准（存成快照）"),
        FieldSpec("paid_cents", "实缴（元）", type="money", default=0),
        FieldSpec("date", "缴费日期", type="date", hint="留空按今天"),
        FieldSpec("note", "备注", hint="如 现金 / 微信 / 减免"),
    ),
    search_keys=("student_name", "note"),
    # 状态是**推导值**（由应缴/实缴算出来），构不出 SQL —— 所以不能当筛选键。
    # 「还没缴齐的人」用 /fees/categories/{id} 的催缴名单，那份名单后端算过。
    filter_keys=("category_id",),
    default_sort=("date", -1),
    dedupe_keys=("category_id", "student_name"),  # 同一项目同一个学生只有一条
    extra_keys=("student_id", "sno", "should_pay_yuan", "paid_yuan", "owed_cents", "status"),
    before_save=apply_record,
)

FEE_LEDGER = TableSpec(
    key="fee_ledger",
    title="收支流水",
    entity="流水",
    model=FeeLedger,
    columns=(
        ColumnSpec("date", "日期", w="104px", numeric=True),
        ColumnSpec("kind", "方向", w="70px"),
        ColumnSpec("item", "项目", w="160px"),
        ColumnSpec("amount_yuan", "金额（元）", w="100px", numeric=True, sortable=False),
        ColumnSpec("note", "备注"),
    ),
    fields=(
        FieldSpec("category_id", "收费项目", type="number", required=True, hint="填收费项目的 id"),
        FieldSpec("date", "日期", type="date", hint="留空按今天"),
        FieldSpec("kind", "方向", type="select", options=LEDGER_KINDS, default="收入"),
        FieldSpec("item", "项目", required=True, hint="如 班费收缴 / 买扫除工具"),
        FieldSpec("amount_cents", "金额（元）", type="money", required=True),
        FieldSpec("note", "备注", type="textarea", full=True),
    ),
    search_keys=("item", "note"),
    filter_keys=("kind", "category_id"),
    # 同日流水按**录入顺序**排（旧应用只按日期字符串排，同一天顺序随机）
    default_sort=("date", -1),
    dedupe_keys=(),
    extra_keys=("amount_yuan",),
    before_save=apply_ledger,
)
