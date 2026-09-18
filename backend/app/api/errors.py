"""统一错误结构与异常。

目标（源自 `docs/改造方案/04` 的缺陷清单）：**不再出现「出错了：Cannot read properties
of undefined」这类无上下文提示**。所有失败都带一个稳定的 `code` 和一句人看得懂的中文
`message`，前端按 code 决定怎么呈现。

响应形状：
    {"ok": false, "error": {"code": "...", "message": "...", "detail": {...}}}
"""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """业务错误。由 main.py 的异常处理器转成统一响应。"""

    def __init__(self, code: str, message: str, *, status: int = 400, detail: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.detail = detail


# 错误码常量（前端 api.js 按这些 code 映射到具体提示）
NOT_FOUND = "NOT_FOUND"
VALIDATION = "VALIDATION"
FIELD_REQUIRED = "FIELD_REQUIRED"
UNKNOWN_FIELD = "UNKNOWN_FIELD"
INVALID_VALUE = "INVALID_VALUE"
TABLE_NOT_FOUND = "TABLE_NOT_FOUND"
CLASS_ID_REQUIRED = "CLASS_ID_REQUIRED"
CLASS_NOT_FOUND = "CLASS_NOT_FOUND"
INTERNAL = "INTERNAL"
