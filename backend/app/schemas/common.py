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


def page_meta(total: int, page: int, page_size: int) -> dict[str, int]:
    return {"total": total, "page": page, "pageSize": page_size}


def resolve_paging(page: int | None, page_size: int | None) -> tuple[int, int]:
    """规整分页参数，避免 0 页、超大页把内存打满。"""
    safe_page = max(1, page or 1)
    safe_size = page_size or DEFAULT_PAGE_SIZE
    safe_size = max(1, min(safe_size, MAX_PAGE_SIZE))
    return safe_page, safe_size
