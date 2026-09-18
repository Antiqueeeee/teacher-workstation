"""HTTP 入参解析。

单独成模块的原因：`classId`「页码」这类参数的整型转换与错误文案，
在列表、统计、导入、班级解析四个地方都要用 —— 各写一份就会出现
「同一个错值，四个地方四种提示」。这类小事是旧应用 40 条缺陷的共同形状。
"""

from __future__ import annotations

from typing import Any

from app.api.errors import INVALID_VALUE, ApiError


def as_int(raw: Any, label: str) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError(INVALID_VALUE, f"「{label}」需要是整数", detail={"value": raw}) from None


def as_optional_int(raw: Any, label: str) -> int | None:
    return None if raw in ("", None) else as_int(raw, label)


def is_truthy(raw: Any) -> bool:
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "是"}
