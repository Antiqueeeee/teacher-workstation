"""列表查询构造 —— **列表接口与导出接口共用同一份**。

为什么必须共用：「导出当前筛选结果」这句话只有在两边用同一套筛选时才成立。
各写一遍的话，导出的内容迟早和屏幕上看到的不一致，而用户会拿导出文件去对账。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.schemas.common import resolve_paging
from app.schemas.registry import TableSpec
from app.services.class_scope import resolve_class_id
from app.services.field_value import parse_value
from app.services.params import as_optional_int

FILTER_PREFIX = "filter."


@dataclass
class ListQuery:
    stmt: Select
    page: int
    page_size: int

    def total(self, session: Session) -> int:
        return session.scalar(select(func.count()).select_from(self.stmt.order_by(None).subquery())) or 0


def _apply_filters(spec: TableSpec, stmt: Select, params: Any) -> Select:
    """`filter.<列>=值` 精确筛选。

    值按字段声明解析，所以 `filter.done=true`、`filter.done=是` 都能用，
    并且非法值会给出和其它入口一致的提示。
    """
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
                from app.api.errors import INVALID_VALUE, ApiError

                raise ApiError(INVALID_VALUE, issue.message, detail={"filter": column})
            value = parsed
        stmt = stmt.where(getattr(spec.model, column) == value)
    return stmt


def build_list_query(spec: TableSpec, session: Session, params: Any) -> ListQuery:
    model = spec.model
    stmt = select(model)
    if spec.soft_delete:
        stmt = stmt.where(model.deleted_at.is_(None))

    if spec.class_scoped:
        class_id = resolve_class_id(spec, params.get("classId"), session)
        if class_id is not None:
            stmt = stmt.where(model.class_id == class_id)

    keyword = (params.get("q") or "").strip()
    if keyword and spec.search_keys:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(*[getattr(model, key).like(like) for key in spec.search_keys]))

    stmt = _apply_filters(spec, stmt, params)

    sort_key = params.get("sort") or spec.default_sort[0]
    if sort_key not in spec.sortable_keys:
        sort_key = spec.default_sort[0]
    default_dir = "desc" if spec.default_sort[1] < 0 else "asc"
    direction = (params.get("dir") or default_dir).strip().lower()
    column = getattr(model, sort_key)
    stmt = stmt.order_by(column.desc() if direction.startswith("d") else column.asc(), model.id.desc())

    page, page_size = resolve_paging(
        as_optional_int(params.get("page"), "page"),
        as_optional_int(params.get("pageSize"), "pageSize"),
    )
    return ListQuery(stmt=stmt, page=page, page_size=page_size)
