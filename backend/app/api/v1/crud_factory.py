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

五条纪律，改这个文件时别丢：
1. 字段语义只在 `services/field_value.py` 实现一次（校验、默认值都从那里来）；
2. 筛选/统计/导出共用 `services/table_query.py` 的条件构造；
3. 可见性（软删除）只有 `_visible_or_none` 一处判定；
4. 保存前的派生/校验走统一的 `before_save` 钩子（新增、更新、批量、导入四条路径都调用）；
5. 输出统一走 `serialize_row` —— 它知道哪些字段在真实列、哪些在 JSON 列。
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.errors import (
    FIELD_REQUIRED,
    INVALID_VALUE,
    NOT_FOUND,
    UNKNOWN_FIELD,
    ApiError,
)
from app.db.base import utcnow
from app.db.engine import get_session
from app.schemas.common import page_meta, serialize_row, split_values
from app.schemas.registry import FieldSpec, TableSpec
from app.services.class_scope import resolve_class_id
from app.services.field_value import CODE_MISSING_REQUIRED, apply_defaults, parse_value
from app.services.params import as_int
from app.services.table_query import build_conditions, build_list_query

# 这些键由系统管理，出现在提交体里不算「未知字段」，但也不允许客户端直接改
RESERVED_KEYS = frozenset({"id", "class_id", "classId", "created_at", "updated_at", "deleted_at"})

SpecProvider = Callable[[], TableSpec]


# --------------------------------------------------------------------------- 校验


def _short(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw)
    return text if len(text) <= 100 else text[:100] + "…"


def coerce(field: FieldSpec, raw: Any) -> Any:
    """按声明解析入参；不合法就抛带中文说明的 ApiError。

    真正的语义在 `services/field_value.py` —— **Excel 导入走的是同一份实现**。
    两边各写一遍的话，「同一个字段在两条路上理解不一致」是迟早的事。
    """
    value, issue = parse_value(field, raw)
    if issue is None:
        return value
    code = FIELD_REQUIRED if issue.code == CODE_MISSING_REQUIRED else INVALID_VALUE
    raise ApiError(code, issue.message, detail={"field": field.k, "value": _short(raw)})


def normalize(spec: TableSpec, payload: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    """校验整个提交体，返回可直接赋给模型的值。

    - `partial=False`（新增）：必填项缺失即报错，其余按声明补默认值；
    - `partial=True`（更新）：只处理传了的字段，**不补默认值**
      （否则一次改「备注」会把没传的字段全重置成默认值）。
    """
    known = spec.field_map
    for key in payload:
        if key in RESERVED_KEYS:
            continue
        if key not in known:
            raise ApiError(UNKNOWN_FIELD, f"未知字段：{key}", detail={"field": key})

    values: dict[str, Any] = {}
    for key, field in known.items():
        if not field.editable:
            continue
        if key in payload:
            values[key] = coerce(field, payload[key])
        elif not partial and field.required:
            raise ApiError(FIELD_REQUIRED, f"「{field.label}」是必填项", detail={"field": key})

    # 默认值补齐与导入预览/提交共用同一实现 —— 曾经两边不一致，
    # 出现「预览显示优先级=中、库里存的是空」这种数据错位
    return values if partial else apply_defaults(spec.fields, values)


def run_before_save(spec: TableSpec, values: dict[str, Any], session: Session, row: Any = None) -> int | None:
    """调用声明里的保存前钩子，返回钩子可能推导出的 class_id。

    钩子能把「老师填的名字」变成「程序要的 id」（见 guardian_service.link_student）。

    这里 `pop` 掉 class_id：它不进 `model(**values)`，而是由调用方按班级范围决定 ——
    否则非班级范围的表会因为多出一个 class_id 参数直接报错。
    """
    if spec.before_save is not None:
        spec.before_save(values, session, row)
    return values.pop("class_id", None)


# --------------------------------------------------------------------------- 辅助


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


# --------------------------------------------------------------------------- 工厂


def build_router(spec_provider: SpecProvider) -> APIRouter:
    """按表声明生成路由。传的是 **provider** 而不是 spec 本身 ——
    动态表的声明每次请求现取（老师加字段后立刻生效）。"""
    bootstrap_spec = spec_provider()
    router = APIRouter(prefix=f"/{bootstrap_spec.key}", tags=[bootstrap_spec.title])

    @router.get("")
    def list_items(request: Request, session: Session = Depends(get_session)):
        spec = spec_provider()
        # 筛选/排序/分页一律走 services/table_query.py —— 统计与导出用的是同一份实现
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
            attr = getattr(model, column)
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
        values = normalize(spec, body, partial=False)
        hinted_class = run_before_save(spec, values, session, None)
        if spec.class_scoped:
            # 钩子推导出的班级优先于请求参数：它来自真实的学生记录，比参数可信
            values["class_id"] = (
                hinted_class
                if hinted_class is not None
                else resolve_class_id(spec, request.query_params.get("classId") or body.get("classId"), session)
            )
        columns, payload = split_values(spec, values)
        row = spec.model(**columns)
        if payload and spec.json_column:
            setattr(row, spec.json_column, payload)
        session.add(row)
        session.flush()
        return {"ok": True, "data": serialize_row(spec, row)}

    @router.patch("/{row_id}")
    def update_one(
        row_id: int,
        body: dict[str, Any] = Body(default_factory=dict),
        session: Session = Depends(get_session),
    ):
        spec = spec_provider()
        row = _get_or_404(spec, session, row_id)
        values = normalize(spec, body, partial=True)
        # 更新时忽略钩子推导出的 class_id：改一条资料，不该把它挪到别的班
        run_before_save(spec, values, session, row)
        columns, payload = split_values(spec, values)
        for key, value in columns.items():
            setattr(row, key, value)
        if payload and spec.json_column:
            # JSON 字段是**合并**而不是覆盖：没提交的字段保持原值
            merged = dict(getattr(row, spec.json_column) or {})
            merged.update(payload)
            setattr(row, spec.json_column, merged)
        session.flush()
        return {"ok": True, "data": serialize_row(spec, row)}

    @router.delete("/{row_id}")
    def delete_one(row_id: int, session: Session = Depends(get_session)):
        spec = spec_provider()
        row = _get_or_404(spec, session, row_id)
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
                if spec.soft_delete:
                    row.deleted_at = utcnow()
                else:
                    session.delete(row)
        elif action == "update":
            patch = normalize(spec, body.get("patch") or {}, partial=True)
            if not patch:
                raise ApiError(INVALID_VALUE, "没有要修改的内容")
            for row in rows:
                row_values = dict(patch)
                run_before_save(spec, row_values, session, row)
                columns, payload = split_values(spec, row_values)
                for key, value in columns.items():
                    setattr(row, key, value)
                if payload and spec.json_column:
                    merged = dict(getattr(row, spec.json_column) or {})
                    merged.update(payload)
                    setattr(row, spec.json_column, merged)
        else:
            raise ApiError(INVALID_VALUE, "action 只能是 delete 或 update", detail={"action": action})

        session.flush()
        # 同时回报「选中多少、实际处理多少」，让界面能如实说明差异
        return {"ok": True, "data": {"requested": len(ids), "affected": len(rows)}}

    return router
