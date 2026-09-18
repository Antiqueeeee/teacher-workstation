"""通用 CRUD 路由工厂：按 `TableSpec` 生成一整套 REST 接口。

一个表只需要在 `schemas/registry.py` 里声明一次，路由、校验、分页、筛选、软删除
全部由这里生成 —— 避免旧应用那种「每个模块手写一遍列表/表单/校验」的重复。

支持动态表：`spec_provider` 每次请求都会重新取声明，所以像学生档案那种
「字段定义存在数据库、老师随时增删字段」的表，不需要重启服务就能生效。

接口（见 `docs/改造方案/03` §5.1）：
    GET    /{key}                列表：q / sort / dir / page / pageSize / classId
                                 / filter.<列> / includeDeleted
    GET    /{key}/schema         该表的声明（前端可直接当 cfg 用）
    GET    /{key}/stats          计数统计（与列表**同一套条件**，否则 KPI 和列表会对不上）
    GET    /{key}/{id}           单条
    POST   /{key}                新增
    PATCH  /{key}/{id}           局部更新
    DELETE /{key}/{id}           软删除
    POST   /{key}/{id}/restore   恢复软删除（软删除必须留出口，否则「能找回」是空话）
    POST   /{key}/batch          批量：{"action": "delete"|"update", "ids": [], "patch": {}}

四条纪律，改这个文件时别丢：
1. 字段语义只在 `services/field_value.py` 实现一次；
2. 筛选/统计/导出共用 `services/table_query.py`；**写入**共用 `services/table_write.py`；
3. 可见性（软删除）只有 `_visible_or_none` 一处判定；
4. 输出统一走 `serialize_row` —— 它知道哪些字段在真实列、哪些在 JSON 列。
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, NOT_FOUND, ApiError
from app.db.base import utcnow
from app.db.engine import get_session
from app.schemas.common import page_meta, serialize_row
from app.schemas.registry import FieldSpec, TableSpec
from app.services.params import as_int
from app.services.table_query import build_conditions, build_list_query, field_expr
from app.services.table_write import save as save_row

SpecProvider = Callable[[], TableSpec]


def _visible_or_none(spec: TableSpec, session: Session, row_id: int):
    """按 id 取一条**未删除**记录；不存在或已删除都返回 None。

    软删除的可见性判定只有这里一处 —— 批量操作曾经绕过它，
    导致能改到界面上看不见的已删记录。
    """
    row = session.get(spec.model, row_id)
    if row is None:
        return None
    if spec.soft_delete and getattr(row, "deleted_at", None) is not None:
        return None
    return row


def _get_or_404(spec: TableSpec, session: Session, row_id: int):
    row = _visible_or_none(spec, session, row_id)
    if row is None:
        raise ApiError(NOT_FOUND, f"这条{spec.entity}不存在，可能已被删除", status=404, detail={"id": row_id})
    return row


def _bucket_label(field: FieldSpec | None, value: Any) -> str:
    """统计分组的展示名：布尔走「是/否」词表，不能冒出 True/False。"""
    if field is not None and field.type == "checkbox":
        return "是" if value else "否"
    return "" if value is None else str(value)


def build_router(spec_provider: SpecProvider) -> APIRouter:
    """按表声明生成路由。传的是 **provider** 而不是 spec 本身 ——
    动态表的声明每次请求现取（老师加字段后立刻生效）。"""
    bootstrap_spec = spec_provider()
    router = APIRouter(prefix=f"/{bootstrap_spec.key}", tags=[bootstrap_spec.title])

    @router.get("")
    def list_items(request: Request, session: Session = Depends(get_session)):
        spec = spec_provider()
        query = build_list_query(spec, session, request.query_params)
        total = query.total(session)
        rows = session.scalars(
            query.stmt.limit(query.page_size).offset((query.page - 1) * query.page_size)
        ).all()
        return {
            "ok": True,
            "data": [serialize_row(spec, row) for row in rows],
            "meta": page_meta(total, query.page, query.page_size),
        }

    @router.get("/stats")
    def stats(request: Request, session: Session = Depends(get_session)):
        """KPI 用。与列表**共用同一套条件** —— 否则搜完之后的总数不是搜索结果的总数。"""
        spec = spec_provider()
        conditions = build_conditions(spec, session, request.query_params)
        model = spec.model
        total = session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0

        groups: dict[str, dict[str, int]] = {}
        for column in spec.filter_keys:
            # 必须走 field_expr：JSON 字段（学生档案的 extra）不是模型属性，
            # 直接 getattr(model, key) 会抛 AttributeError（踩过一次）
            attr = field_expr(spec, column)
            rows = session.execute(
                select(attr, func.count()).select_from(model).where(*conditions).group_by(attr)
            ).all()
            field = spec.field_map.get(column)
            groups[column] = {_bucket_label(field, key): count for key, count in rows}
        return {"ok": True, "data": {"total": total, "groups": groups}}

    @router.get("/schema")
    def schema():
        return {"ok": True, "data": spec_provider().to_dict()}

    @router.get("/{row_id}")
    def get_one(row_id: int, session: Session = Depends(get_session)):
        spec = spec_provider()
        return {"ok": True, "data": serialize_row(spec, _get_or_404(spec, session, row_id))}

    @router.post("", status_code=201)
    def create_one(
        request: Request,
        body: dict[str, Any] = Body(default_factory=dict),
        session: Session = Depends(get_session),
    ):
        spec = spec_provider()
        row = save_row(
            spec,
            session,
            body,
            partial=False,
            class_id_raw=request.query_params.get("classId") or body.get("classId"),
        )
        return {"ok": True, "data": serialize_row(spec, row)}

    @router.patch("/{row_id}")
    def update_one(
        row_id: int,
        body: dict[str, Any] = Body(default_factory=dict),
        session: Session = Depends(get_session),
    ):
        spec = spec_provider()
        row = _get_or_404(spec, session, row_id)
        save_row(spec, session, body, partial=True, row=row)
        return {"ok": True, "data": serialize_row(spec, row)}

    @router.delete("/{row_id}")
    def delete_one(row_id: int, session: Session = Depends(get_session)):
        spec = spec_provider()
        row = _get_or_404(spec, session, row_id)
        if spec.before_delete is not None:
            spec.before_delete(session, row)  # 删不了就抛错，不让它删一半
        if spec.soft_delete:
            row.deleted_at = utcnow()
        else:
            session.delete(row)
        session.flush()
        # 写操作统一返回更新后的完整记录（约定见 03 §5.2）
        return {"ok": True, "data": serialize_row(spec, row) if spec.soft_delete else {"id": row_id}}

    @router.post("/{row_id}/restore")
    def restore_one(row_id: int, session: Session = Depends(get_session)):
        spec = spec_provider()
        row = session.get(spec.model, row_id)
        if row is None:
            raise ApiError(NOT_FOUND, f"这条{spec.entity}不存在", status=404, detail={"id": row_id})
        if spec.soft_delete and getattr(row, "deleted_at", None) is not None:
            row.deleted_at = None
        session.flush()
        return {"ok": True, "data": serialize_row(spec, row)}

    @router.post("/batch")
    def batch(body: dict[str, Any] = Body(...), session: Session = Depends(get_session)):
        spec = spec_provider()
        action = (body.get("action") or "").strip()
        ids = [as_int(raw, "ids") for raw in (body.get("ids") or [])]
        if not ids:
            raise ApiError(INVALID_VALUE, "没有选中任何记录")

        # 只处理「当前可见」的行：已删除的不再参与批量操作（否则会出现
        # 「界面上看不到，却被动过」的记录）
        rows = [row for row in (_visible_or_none(spec, session, i) for i in ids) if row is not None]

        if action == "delete":
            for row in rows:
                if spec.before_delete is not None:
                    spec.before_delete(session, row)
                if spec.soft_delete:
                    row.deleted_at = utcnow()
                else:
                    session.delete(row)
            session.flush()
        elif action == "update":
            patch = body.get("patch") or {}
            if not patch:
                raise ApiError(INVALID_VALUE, "没有要修改的内容")
            for row in rows:
                # 逐行走同一条写入管线（钩子、JSON 分流都在里面）
                save_row(spec, session, patch, partial=True, row=row)
        else:
            raise ApiError(INVALID_VALUE, "action 只能是 delete 或 update", detail={"action": action})

        # 同时回报「选中多少、实际处理多少」，让界面能如实说明差异
        return {"ok": True, "data": {"requested": len(ids), "affected": len(rows)}}

    return router
