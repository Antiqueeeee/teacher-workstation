"""请求级会话依赖与「写请求在响应之前落库」的收口。

**为什么单独一个模块**：`get_session` 只负责建会话、关会话（不知道 HTTP）；
「把会话挂到 `request.state` 上供提交路由收口」是 HTTP 这一层的事，
所以放在 `api/` 里 —— `db/` 不认识 FastAPI。

FastAPI 的 yield 依赖在**响应发出之后**才收尾，所以提交只能放在这里与
`CommittingRoute` 里配合完成（详见那个模块的说明）。
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from app.db.engine import get_session


def db_session(request: Request) -> Iterator[Session]:
    """每个请求一个会话，并把它挂到 `request.state.session` 上。

    接口里照旧写 `session: Session = Depends(db_session)`；
    `CommittingRoute` 在响应发出前用同一个会话提交。
    """
    for session in get_session():
        request.state.session = session
        yield session
