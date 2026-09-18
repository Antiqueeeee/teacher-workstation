"""班级事务类表的声明：待办、班规、话术模板。

单独成模块是 `CONTRIBUTING.md` §3 的「按聚合分」：一组紧密相关的表一个文件。
类型定义在 `schemas/table_spec.py`，汇总与访问器在 `schemas/registry.py`。
"""

from __future__ import annotations

from app.models.rule import CATEGORIES as RULE_CATEGORIES
from app.models.rule import Rule
from app.models.template import CATEGORIES as TEMPLATE_CATEGORIES
from app.models.template import TONES as TEMPLATE_TONES
from app.models.template import Template
from app.models.todo import PRIORITIES, Todo
from app.schemas.table_spec import ColumnSpec, FieldSpec, TableSpec

TODO = TableSpec(
    key="todos",
    model=Todo,
    title="待办任务",
    entity="待办",
    columns=(
        ColumnSpec("content", "内容"),
        ColumnSpec("due_date", "截止日期", w="110px", numeric=True),
        ColumnSpec("priority", "优先级", w="80px"),
        ColumnSpec("done", "状态", w="90px"),
        ColumnSpec("note", "备注"),
    ),
    fields=(
        FieldSpec("content", "内容", required=True),
        FieldSpec("due_date", "截止日期", type="date"),
        FieldSpec("priority", "优先级", type="select", options=PRIORITIES, default="中"),
        FieldSpec("done", "已完成", type="checkbox", default=False),
        FieldSpec("note", "备注", type="textarea"),
    ),
    search_keys=("content", "note"),
    filter_keys=("priority", "done"),
    default_sort=("id", -1),
    dedupe_keys=("content", "due_date"),  # 同内容 + 同截止日视为同一条，重复导入不会翻倍
)


RULE = TableSpec(
    key="rules",
    model=Rule,
    title="班规制度",
    entity="班规",
    columns=(
        ColumnSpec("category", "类别", w="90px"),
        ColumnSpec("title", "标题"),
        ColumnSpec("version", "版本", w="80px"),
        ColumnSpec("effective_from", "生效日期", w="110px", numeric=True),
        ColumnSpec("effective_to", "失效日期", w="110px", numeric=True),
        ColumnSpec("content", "内容"),
    ),
    fields=(
        FieldSpec("category", "类别", type="select", options=RULE_CATEGORIES),
        FieldSpec("title", "标题", required=True),
        FieldSpec("version", "版本"),
        FieldSpec("effective_from", "生效日期", type="date"),
        FieldSpec("effective_to", "失效日期", type="date"),
        FieldSpec("content", "内容", type="textarea", full=True),
    ),
    search_keys=("title", "content"),
    filter_keys=("category",),
    default_sort=("id", -1),
    dedupe_keys=("category", "title"),  # 同类同标题视为同一条班规
)


TEMPLATE = TableSpec(
    key="templates",
    model=Template,
    title="话术模板库",
    entity="模板",
    columns=(
        ColumnSpec("title", "标题"),
        ColumnSpec("category", "场景", w="100px"),
        ColumnSpec("tone", "语气", w="100px"),
        ColumnSpec("use_count", "使用次数", w="90px", numeric=True),
        ColumnSpec("content", "内容"),
    ),
    fields=(
        FieldSpec("title", "标题", required=True),
        FieldSpec("category", "场景", type="select", options=TEMPLATE_CATEGORIES),
        FieldSpec("tone", "语气", type="select", options=TEMPLATE_TONES),
        FieldSpec("content", "内容", type="textarea", full=True, required=True),
        FieldSpec("use_count", "使用次数", type="number", default=0, editable=False),
    ),
    search_keys=("title", "content"),
    filter_keys=("category", "tone"),
    default_sort=("id", -1),
    class_scoped=False,  # 话术模板是全班共享的素材，不属于某个班级
    dedupe_keys=("title",),  # 同标题视为同一条模板
)
