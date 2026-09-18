"""写请求的提交时机：在**响应发出之前**落库。

问题出在 FastAPI 的 yield 依赖上：`get_session` 里 `yield session` 之后的提交
要等**响应发出之后**才执行。于是「提交时报错」（磁盘满、库被别的进程锁住、
约束在提交阶段才炸）发生时，客户端已经拿到 `200 {"ok":true}` 了 ——
老师以为记上了，其实没记上，而且**不会去看日志**。

这里把 POST/PUT/PATCH/DELETE 的提交挪到响应之前：提交失败会走统一的错误处理器
返回 500，界面据此提示「没保存上」。读请求提交什么也不做（没有待提交的东西）。

`get_session` 里那道提交保留为**保险**（脚本直接调服务层、老代码路径），
两次提交里第二次是空操作。
"""

from __future__ import annotations

import logging

from fastapi.routing import APIRoute

logger = logging.getLogger("teacher-workstation")

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class CommittingRoute(APIRoute):
    """写请求在响应前提交（一个地方管全部接口，新加接口不会漏）。"""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            response = await original(request)
            session = getattr(request.state, "session", None)
            # 出错响应（4xx/5xx）不提交：这时候库里的改动本来就该丢掉，
            # 让依赖收尾时的 rollback 处理（与之前的行为一致）
            if session is not None and request.method in WRITE_METHODS and response.status_code < 400:
                try:
                    session.commit()
                except Exception:
                    session.rollback()
                    logger.exception("写请求提交失败：%s %s", request.method, request.url.path)
                    raise
            return response

        return handler
