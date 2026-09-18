"""应用入口。

启动时：建目录 → 自动跑数据库迁移 → 确保至少有一个班级（单班场景前端不需要选班级）。
同时把 `frontend/` 作为静态资源托管 —— 手机与电脑访问同一个地址，无需构建步骤。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.errors import INTERNAL, NOT_FOUND, VALIDATION, ApiError
from app.api.router import router as api_router
from app.config import APP_NAME, APP_VERSION, FRONTEND_DIR, ensure_dirs
from app.db.engine import SessionLocal
from app.db.migrate import upgrade_to_head
from app.models.class_ import Class

logger = logging.getLogger("teacher-workstation")


def _ensure_default_class() -> None:
    """一个班都没有时建一个空班级（不是演示数据）。

    单班级场景下，前端的接口都不用传 classId。
    """
    with SessionLocal() as session:
        exists = session.scalar(select(Class.id).where(Class.deleted_at.is_(None)).limit(1))
        if exists is None:
            session.add(Class(grade="", class_no="", name="我的班级"))
            session.commit()
            logger.info("已创建默认班级")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_dirs()
    upgrade_to_head()
    _ensure_default_class()
    logger.info("%s v%s 启动完成", APP_NAME, APP_VERSION)
    yield


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError):
        return JSONResponse(
            status_code=exc.status,
            content={"ok": False, "error": {"code": exc.code, "message": exc.message, "detail": exc.detail}},
        )

    # 必须注册 Starlette 的基类：FastAPI 内部抛的也是 starlette 的 HTTPException
    # （未知路由、请求体解析失败等），注册 fastapi.HTTPException 那个子类是捕不到的。
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException):
        message = str(exc.detail)
        if "parsing the body" in message:
            message = "请求内容不是合法的 JSON（请确认以 UTF-8 提交）"
        code = NOT_FOUND if exc.status_code == 404 else VALIDATION
        return JSONResponse(
            status_code=exc.status_code,
            content={"ok": False, "error": {"code": code, "message": message, "detail": None}},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError):
        errors = exc.errors()
        json_invalid = any(error.get("type") == "json_invalid" for error in errors)
        return JSONResponse(
            # 请求体根本不是合法 JSON 属于「请求错误」(400)，
            # 而不是「参数语义不合法」(422)
            status_code=400 if json_invalid else 422,
            content={
                "ok": False,
                "error": {
                    "code": VALIDATION,
                    "message": "请求内容不是合法的 JSON（请确认以 UTF-8 提交）"
                    if json_invalid
                    else "请求参数不合法",
                    "detail": errors,
                },
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception):
        # 兜底也要给出可定位的信息，而不是一句「出错了」
        logger.exception("未处理异常: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": {"code": INTERNAL, "message": f"服务内部错误：{type(exc).__name__}", "detail": None},
            },
        )


def create_app() -> FastAPI:
    app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)
    register_error_handlers(app)
    app.include_router(api_router)

    if FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
    else:
        logger.warning("前端目录不存在，仅提供 API：%s", FRONTEND_DIR)

    return app


app = create_app()
