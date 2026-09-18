"""金额：一律以**分**存整数，输入输出用元。

为什么不直接存浮点的元：`0.1 + 0.2` 在浮点里是 `0.30000000000000004`，
而这里是班费、助学金这种要跟家长对账的数 —— 合计差一分就要解释半天。
（`03` §6.2 的约定：金额以分存整数。）
"""

from __future__ import annotations

from typing import Any

from app.api.errors import INVALID_VALUE, ApiError


def to_cents(raw: Any, label: str = "金额") -> int:
    """把用户填的「元」转成分。接受 `1200`、`1200.5`、`"1,200.50"`、`""`（当 0）。"""
    if raw in (None, ""):
        return 0
    text = str(raw).strip().replace(",", "").replace("，", "").replace("¥", "").replace("元", "")
    if not text:
        return 0
    try:
        return int(round(float(text) * 100))
    except ValueError:
        raise ApiError(INVALID_VALUE, f"「{label}」要填数字（元）", detail={"value": raw}) from None


def format_cents(cents: int | None) -> str:
    """分 → 「1,200.50」这样的展示串。"""
    return f"{(cents or 0) / 100:,.2f}"


def sum_cents(values: list[int | None]) -> int:
    return sum(value or 0 for value in values)
