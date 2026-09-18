"""通用序列化与分页辅助。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.config import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


def jsonable(value: Any) -> Any:
    """把模型字段值转成 JSON 可序列化的形式。

    日期统一输出 ISO 字符串（`YYYY-MM-DD`），时间戳输出 ISO 8601，
    与前端「日期就是一个字符串」的既有写法兼容。
    """
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def serialize(obj: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: jsonable(getattr(obj, key, None)) for key in keys}


def serialize_row(spec: Any, obj: Any) -> dict[str, Any]:
    """按表声明把一条记录转成可输出的字典。

    JSON 列里的字段（学生档案的 `extra`）走这里统一摊平 ——
    调用方不必知道某个字段是列还是 JSON。
    """
    json_fields = getattr(spec, "json_fields", frozenset())
    plain_keys = tuple(key for key in spec.output_keys if key not in json_fields)
    data = serialize(obj, plain_keys)
    if json_fields:
        payload = getattr(obj, spec.json_column, None) or {}
        for key in spec.output_keys:
            if key in json_fields:
                data[key] = jsonable(payload.get(key))
    return data


def split_values(spec: Any, values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """把值分成「真实列」与「JSON 列」两份（写入侧，与 `serialize_row` 对称）。

    JSON 那份要转成可序列化的形式：日期对象直接塞进 JSON 列会抛
    「Object of type date is not JSON serializable」（踩过一次），
    所以统一走 `jsonable` 转成 ISO 字符串。

    新增、更新、批量、导入四条写入路径都调用它 —— 分流规则只有这一处。
    """
    json_fields = getattr(spec, "json_fields", frozenset())
    if not json_fields:
        return values, {}
    columns = {key: value for key, value in values.items() if key not in json_fields}
    payload = {key: jsonable(value) for key, value in values.items() if key in json_fields}
    return columns, payload


def page_meta(total: int, page: int, page_size: int) -> dict[str, int]:
    return {"total": total, "page": page, "pageSize": page_size}


def resolve_paging(page: int | None, page_size: int | None) -> tuple[int, int]:
    """规整分页参数，避免 0 页、超大页把内存打满。"""
    safe_page = max(1, page or 1)
    safe_size = page_size or DEFAULT_PAGE_SIZE
    safe_size = max(1, min(safe_size, MAX_PAGE_SIZE))
    return safe_page, safe_size
