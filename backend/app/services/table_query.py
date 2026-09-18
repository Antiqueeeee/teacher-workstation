"""列表查询构造 —— **列表、统计、导出三处共用同一份条件**。

为什么必须共用：
- 「总数」和「列表」如果各算一遍筛选，用户搜完之后看到的总数就不是搜索结果的总数
  （评审实测：`q=P-KPI` 时列表 total=1、KPI 显示「共 2 条」）；
- 「导出当前筛选结果」同理 —— 各写一遍，导出的内容和屏幕上看到的迟早不一致，
  而用户会拿导出文件去对账。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.api.errors import INVALID_VALUE, ApiError
from app.schemas.common import resolve_paging
from app.schemas.registry import TableSpec
from app.services.class_scope import resolve_class_id
from app.services.field_value import parse_value
from app.services.params import as_optional_int, is_truthy

FILTER_PREFIX = "filter."


def build_conditions(spec: TableSpec, session: Session, params: Any) -> list:
    """列表 / 统计 / 导出共用的 where 条件：软删除 + 班级 + 关键词 + 精确筛选。

    `includeDeleted=1` 时连已删除的一起返回 —— 软删除要有出口，
    否则「删除后还能找回」就是一句空话（界面上曾这么承诺过）。
    """
    model = spec.model
    conditions: list = []

    if spec.soft_delete and not is_truthy(params.get("includeDeleted")):
        conditions.append(model.deleted_at.is_(None))

    if spec.class_scoped:
        class_id = resolve_class_id(spec, params.get("classId"), session)
        if class_id is not None:
            conditions.append(model.class_id == class_id)

    keyword = (params.get("q") or "").strip()
    if keyword and spec.search_keys:
        like = f"%{keyword}%"
        conditions.append(or_(*[getattr(model, key).like(like) for key in spec.search_keys]))

    for raw_key, raw_value in params.items():
        if not raw_key.startswith(FILTER_PREFIX) or raw_value == "":
            continue
        column = raw_key[len(FILTER_PREFIX) :]
        if column not in spec.filter_keys:
            continue
        field_spec = spec.field_map.get(column)
        value: Any = raw_value
        if field_spec is not None:
            parsed, issue = parse_value(field_spec, raw_value)
            if issue is not None:
                # 筛选值不合法时不要静默忽略，否则用户会以为「筛出来就这些」
                raise ApiError(INVALID_VALUE, issue.message, detail={"filter": column})
            value = parsed
        conditions.append(getattr(model, column) == value)

    return conditions


def build_order_by(spec: TableSpec, params: Any) -> list:
    model = spec.model
    sort_key = params.get("sort") or spec.default_sort[0]
    if sort_key not in spec.sortable_keys:
        sort_key = spec.default_sort[0]
    default_dir = "desc" if spec.default_sort[1] < 0 else "asc"
    direction = (params.get("dir") or default_dir).strip().lower()
    column = getattr(model, sort_key)
    # 次级排序固定按 id 倒序：同一天导入的几十条记录才不会每次刷新都换顺序
    return [column.desc() if direction.startswith("d") else column.asc(), model.id.desc()]


@dataclass
class ListQuery:
    stmt: Select
    page: int
    page_size: int

    def total(self, session: Session) -> int:
        return session.scalar(select(func.count()).select_from(self.stmt.order_by(None).subquery())) or 0


def build_list_query(spec: TableSpec, session: Session, params: Any) -> ListQuery:
    stmt = (
        select(spec.model)
        .where(*build_conditions(spec, session, params))
        .order_by(*build_order_by(spec, params))
    )
    page, page_size = resolve_paging(
        as_optional_int(params.get("page"), "page"),
        as_optional_int(params.get("pageSize"), "pageSize"),
    )
    return ListQuery(stmt=stmt, page=page, page_size=page_size)
