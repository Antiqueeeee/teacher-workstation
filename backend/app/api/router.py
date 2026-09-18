"""v1 路由汇总：注册表接口 + 每张表的通用 CRUD。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.crud_factory import build_router
from app.api.v1.transfer import router as transfer_router
from app.config import APP_VERSION
from app.schemas.registry import TABLES

router = APIRouter(prefix="/api/v1")


@router.get("/health", tags=["系统"])
def health() -> dict:
    return {"ok": True, "data": {"version": APP_VERSION, "tables": len(TABLES)}}


@router.get("/meta/registry", tags=["系统"])
def registry() -> dict:
    """全部表的声明，前端据此渲染列表/表单/筛选项，避免两边各写一遍。"""
    return {"ok": True, "data": [spec.to_dict() for spec in TABLES.values()]}


for _spec in TABLES.values():
    router.include_router(build_router(_spec))

# 导入 / 模板下载：不属于某一张表，单独挂载
router.include_router(transfer_router)
