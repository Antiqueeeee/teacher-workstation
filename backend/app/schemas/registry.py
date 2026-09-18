"""表注册表：一张表的所有「声明式」信息，是通用 CRUD 与前端 cfg 的唯一来源。

为什么要有它：
- 旧应用里每个模块都手写一遍「列 / 字段 / 筛选项 / 校验」，同一个口径散在多处；
- 这里把「这张表长什么样」集中成数据，后端据此生成路由、前端据此渲染列表与表单
  （见 `docs/改造方案/03-目标架构与代码组织.md` §5.1 的 `/meta/registry`）。

新增一张表 = 加一个模型 + 在 `TABLES` 里加一条 `TableSpec`，不需要写 CRUD 代码。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.db.base import Base
from app.models.rule import CATEGORIES as RULE_CATEGORIES
from app.models.rule import Rule
from app.models.template import CATEGORIES as TEMPLATE_CATEGORIES
from app.models.template import Template
from app.models.todo import PRIORITIES, Todo

# 字段类型（与前端 field 渲染器一一对应）
FIELD_TYPES = ("text", "number", "textarea", "select", "checkbox", "date")


@dataclass(frozen=True)
class ColumnSpec:
    """列表页的一列。"""

    k: str
    label: str
    w: str | None = None
    numeric: bool = False
    sortable: bool = True


@dataclass(frozen=True)
class FieldSpec:
    """表单/导入的一个字段。"""

    k: str
    label: str
    type: str = "text"
    required: bool = False
    options: tuple[str, ...] = ()
    default: Any = None
    full: bool = False          # 表单里占整行
    hint: str = ""
    editable: bool = True       # 只读字段（如系统生成的计数）


@dataclass(frozen=True)
class TableSpec:
    """一张表的完整声明。"""

    key: str                     # URL 与前端 cfg 的 key，如 "todos"
    model: type[Base]
    title: str                   # 页面标题
    entity: str                  # 单数称呼，用于文案
    columns: tuple[ColumnSpec, ...] = ()
    fields: tuple[FieldSpec, ...] = ()
    search_keys: tuple[str, ...] = ()          # 关键词搜索覆盖的列
    filter_keys: tuple[str, ...] = ()          # 允许 filter.<k> 精确筛选的列
    default_sort: tuple[str, int] = ("id", -1)  # (列, 方向) 方向 1=升序 -1=降序
    class_scoped: bool = True                  # 是否属于某个班级
    soft_delete: bool = True
    dedupe_keys: tuple[str, ...] = ()          # 导入时的「判重键」：同键视为同一条记录，跳过而不是重复插入
    extra_keys: tuple[str, ...] = field(default_factory=tuple)  # 输出里额外带的列

    @property
    def sortable_keys(self) -> frozenset[str]:
        return frozenset({c.k for c in self.columns if c.sortable} | {"id", "created_at", "updated_at"})

    @property
    def field_map(self) -> dict[str, FieldSpec]:
        return {f.k: f for f in self.fields}

    @property
    def output_keys(self) -> tuple[str, ...]:
        keys = ["id"]
        if self.class_scoped:
            keys.append("class_id")
        keys += [c.k for c in self.columns]
        keys += [f.k for f in self.fields if f.k not in {c.k for c in self.columns}]
        keys += [k for k in self.extra_keys if k not in keys]
        keys += ["created_at", "updated_at"]
        return tuple(dict.fromkeys(keys))

    def to_dict(self) -> dict[str, Any]:
        """给前端的形状（`GET /api/v1/meta/registry`），可直接当页面 cfg 用。"""
        return {
            "key": self.key,
            "title": self.title,
            "entity": self.entity,
            "classScoped": self.class_scoped,
            "defaultSort": {"k": self.default_sort[0], "dir": self.default_sort[1]},
            "columns": [asdict(column) for column in self.columns],
            "fields": [asdict(field_spec) for field_spec in self.fields],
            "filterKeys": list(self.filter_keys),
            "searchKeys": list(self.search_keys),
        }


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
        FieldSpec("category", "类别", type="select", options=RULE_CATEGORIES, default="其他"),
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
        ColumnSpec("use_count", "使用次数", w="90px", numeric=True),
        ColumnSpec("content", "内容"),
    ),
    fields=(
        FieldSpec("title", "标题", required=True),
        FieldSpec("category", "场景", type="select", options=TEMPLATE_CATEGORIES, default="其他"),
        FieldSpec("content", "内容", type="textarea", full=True, required=True),
        FieldSpec("use_count", "使用次数", type="number", default=0, editable=False),
    ),
    search_keys=("title", "content"),
    filter_keys=("category",),
    default_sort=("id", -1),
    class_scoped=False,  # 话术模板是全班共享的素材，不属于某个班级
    dedupe_keys=("title",),  # 同标题视为同一条模板
)

TABLES: dict[str, TableSpec] = {spec.key: spec for spec in (TODO, RULE, TEMPLATE)}


def get_spec(key: str) -> TableSpec | None:
    return TABLES.get(key)
