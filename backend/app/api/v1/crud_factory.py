"""通用 CRUD 路由工厂：按 `TableSpec` 生成一整套 REST 接口。

一个表只需要在 `schemas/registry.py` 里声明一次，路由、校验、分页、筛选、软删除
全部由这里生成 —— 避免旧应用那种「每个模块手写一遍列表/表单/校验」的重复。

接口（见 `docs/改造方案/03` §5.1）：
    GET    /{key}              列表：q / sort / dir / page / pageSize / classId / filter.<列>
    GET    /{key}/schema       该表的声明（前端可直接当 cfg 用）
    GET    /{key}/stats        计数统计（KPI 卡片用）
    GET    /{key}/{id}         单条
    POST   /{key}              新增
    PATCH  /{key}/{id}         局部更新
    DELETE /{key}/{id}         软删除
    POST   /{key}/batch        批量：{"action": "delete"|"update", "ids": [...], "patch": {...}}
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.errors import (
    CLASS_ID_REQUIRED,
    FIELD_REQUIRED,
    INVALID_VALUE,
    NOT_FOUND,
    UNKNOWN_FIELD,
    ApiError,
)
from app.db.base import utcnow
from app.db.engine import get_session
from app.models.class_ import Class
from app.schemas.common import page_meta, resolve_paging, serialize
from app.schemas.registry import FieldSpec, TableSpec

# 前端传字符串的布尔写法（表单 / Excel 导入都会遇到）
TRUE_WORDS = {"1", "true", "True", "是", "已完成", "已缴"}
FALSE_WORDS = {"0", "false", "False", "否", "未完成", "未缴", ""}
DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日")


# --------------------------------------------------------------------------- 校验


def _as_int(raw: Any, label: str) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError(INVALID_VALUE, f"「{label}」需要是整数", detail={"value": raw}) from None


def _as_bool(raw: Any, label: str) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    text = str(raw).strip()
    if text in TRUE_WORDS:
        return True
    if text in FALSE_WORDS:
        return False
    raise ApiError(INVALID_VALUE, f"「{label}」只能是是/否", detail={"value": raw})


def _as_date(raw: Any, label: str) -> date | None:
    if raw in ("", None):
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ApiError(INVALID_VALUE, f"「{label}」日期格式不正确（应为 2026-09-01）", detail={"value": text})


def coerce(field: FieldSpec, raw: Any) -> Any:
    """按声明把入参转成模型能存的值；不合法就抛带中文说明的 ApiError。"""
    if field.type == "checkbox":
        return _as_bool(raw, field.label)

    if field.type == "number":
        if raw in ("", None):
            if field.required:
                raise ApiError(FIELD_REQUIRED, f"「{field.label}」是必填项", detail={"field": field.k})
            return None
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            raise ApiError(
                INVALID_VALUE, f"「{field.label}」需要是数字", detail={"field": field.k, "value": raw}
            ) from None

    if field.type == "date":
        value = _as_date(raw, field.label)
        if value is None and field.required:
            raise ApiError(FIELD_REQUIRED, f"「{field.label}」是必填项", detail={"field": field.k})
        return value

    # text / textarea / select
    text = "" if raw is None else str(raw).strip()
    if not text and field.required:
        raise ApiError(FIELD_REQUIRED, f"「{field.label}」是必填项", detail={"field": field.k})
    if text and field.options and text not in field.options:
        raise ApiError(
            INVALID_VALUE,
            f"「{field.label}」只能选：{'、'.join(field.options)}",
            detail={"field": field.k, "value": text},
        )
    return text


def normalize(spec: TableSpec, payload: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    """校验整个提交体，返回可直接赋给模型的值。

    - `partial=False`（新增）：必填项缺失即报错，其余字段落声明里的默认值；
    - `partial=True`（更新）：只处理传了的字段。
    """
    known = spec.field_map
    for key in payload:
        if key in {"id", "class_id", "classId", "created_at", "updated_at"}:
            continue
        if key not in known:
            raise ApiError(UNKNOWN_FIELD, f"未知字段：{key}", detail={"field": key})

    values: dict[str, Any] = {}
    for key, field in known.items():
        if not field.editable:
            continue
        if key in payload:
            values[key] = coerce(field, payload[key])
        elif not partial:
            if field.required:
                raise ApiError(FIELD_REQUIRED, f"「{field.label}」是必填项", detail={"field": key})
            if field.default is not None:
                values[key] = field.default
    return values


# --------------------------------------------------------------------------- 辅助


def _resolve_class_id(spec: TableSpec, raw: Any, session: Session) -> int | None:
    """确定本次操作属于哪个班级。

    单班场景下不需要前端传 `classId`（老师自己部署，通常就一个班）；
    多班且未指定时明确报错，而不是静默写错班。
    """
    if not spec.class_scoped:
        return None
    if raw not in ("", None):
        class_id = _as_int(raw, "classId")
        if session.get(Class, class_id) is None:
            raise ApiError(INVALID_VALUE, "指定的班级不存在", detail={"classId": class_id})
        return class_id

    ids = list(session.scalars(select(Class.id).where(Class.deleted_at.is_(None))))
    if not ids:
        raise ApiError(CLASS_ID_REQUIRED, "还没有班级，请先创建班级", status=409)
    if len(ids) > 1:
        raise ApiError(CLASS_ID_REQUIRED, "存在多个班级，请指定 classId", status=409)
    return ids[0]


def _truthy(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "y"}


def _query_int(params: Any, key: str) -> int | None:
    raw = params.get(key)
    return None if raw in ("", None) else _as_int(raw, key)


def _get_or_404(spec: TableSpec, session: Session, row_id: int):
    row = session.get(spec.model, row_id)
    if row is None or (spec.soft_delete and getattr(row, "deleted_at", None) is not None):
        raise ApiError(NOT_FOUND, f"这条{spec.entity}不存在，可能已被删除", status=404, detail={"id": row_id})
    return row


# --------------------------------------------------------------------------- 工厂


def build_router(spec: TableSpec) -> APIRouter:
    model = spec.model
    router = APIRouter(prefix=f"/{spec.key}", tags=[spec.title])

    def visible(stmt):
        return stmt.where(model.deleted_at.is_(None)) if spec.soft_delete else stmt

    @router.get("")
    def list_items(request: Request, session: Session = Depends(get_session)):
        params = request.query_params
        stmt = visible(select(model))

        class_id = _resolve_class_id(spec, params.get("classId"), session) if spec.class_scoped else None
        if class_id is not None:
            stmt = stmt.where(model.class_id == class_id)

        keyword = (params.get("q") or "").strip()
        if keyword and spec.search_keys:
            like = f"%{keyword}%"
            stmt = stmt.where(or_(*[getattr(model, key).like(like) for key in spec.search_keys]))

        for raw_key, raw_value in params.items():
            if not raw_key.startswith("filter.") or raw_value == "":
                continue
            column = raw_key[len("filter.") :]
            if column not in spec.filter_keys:
                continue
            field = spec.field_map.get(column)
            value: Any = raw_value
            if field is not None:
                value = coerce(field, raw_value) if field.type != "select" else raw_value
            stmt = stmt.where(getattr(model, column) == value)

        sort_key = params.get("sort") or spec.default_sort[0]
        if sort_key not in spec.sortable_keys:
            sort_key = spec.default_sort[0]
        default_dir = "desc" if spec.default_sort[1] < 0 else "asc"
        direction = (params.get("dir") or default_dir).strip().lower()
        column = getattr(model, sort_key)
        stmt = stmt.order_by(column.desc() if direction.startswith("d") else column.asc(), model.id.desc())

        total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
        page, page_size = resolve_paging(_query_int(params, "page"), _query_int(params, "pageSize"))
        rows = session.scalars(stmt.limit(page_size).offset((page - 1) * page_size)).all()
        return {
            "ok": True,
            "data": [serialize(row, spec.output_keys) for row in rows],
            "meta": page_meta(total, page, page_size),
        }

    @router.get("/stats")
    def stats(request: Request, session: Session = Depends(get_session)):
        """KPI 用：总数 + 各筛选列的分布（前端统计一律读这里，不再遍历全表算）。"""
        params = request.query_params
        conditions = []
        if spec.soft_delete:
            conditions.append(model.deleted_at.is_(None))
        if spec.class_scoped:
            class_id = _resolve_class_id(spec, params.get("classId"), session)
            if class_id is not None:
                conditions.append(model.class_id == class_id)

        total = session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
        groups: dict[str, dict[str, int]] = {}
        for column in spec.filter_keys:
            attr = getattr(model, column)
            rows = session.execute(
                select(attr, func.count()).select_from(model).where(*conditions).group_by(attr)
            ).all()
            groups[column] = {str(key): count for key, count in rows}
        return {"ok": True, "data": {"total": total, "groups": groups}}

    @router.get("/schema")
    def schema():
        return {"ok": True, "data": spec.to_dict()}

    @router.get("/{row_id}")
    def get_one(row_id: int, session: Session = Depends(get_session)):
        return {"ok": True, "data": serialize(_get_or_404(spec, session, row_id), spec.output_keys)}

    @router.post("", status_code=201)
    def create_one(
        request: Request, body: dict[str, Any] = Body(default_factory=dict), session: Session = Depends(get_session)
    ):
        class_id = _resolve_class_id(spec, request.query_params.get("classId") or body.get("classId"), session)
        values = normalize(spec, body, partial=False)
        row = model(**values)
        if class_id is not None:
            row.class_id = class_id
        session.add(row)
        session.flush()
        return {"ok": True, "data": serialize(row, spec.output_keys)}

    @router.patch("/{row_id}")
    def update_one(row_id: int, body: dict[str, Any] = Body(default_factory=dict), session: Session = Depends(get_session)):
        row = _get_or_404(spec, session, row_id)
        for key, value in normalize(spec, body, partial=True).items():
            setattr(row, key, value)
        session.flush()
        return {"ok": True, "data": serialize(row, spec.output_keys)}

    @router.delete("/{row_id}")
    def delete_one(row_id: int, session: Session = Depends(get_session)):
        row = _get_or_404(spec, session, row_id)
        if spec.soft_delete:
            row.deleted_at = utcnow()
        else:
            session.delete(row)
        session.flush()
        return {"ok": True, "data": {"id": row_id}}

    @router.post("/batch")
    def batch(body: dict[str, Any] = Body(...), session: Session = Depends(get_session)):
        action = (body.get("action") or "").strip()
        ids = [_as_int(raw, "ids") for raw in (body.get("ids") or [])]
        if not ids:
            raise ApiError(INVALID_VALUE, "没有选中任何记录")
        rows = [row for row in (session.get(model, i) for i in ids) if row is not None]
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
                for key, value in patch.items():
                    setattr(row, key, value)
        else:
            raise ApiError(INVALID_VALUE, "action 只能是 delete 或 update", detail={"action": action})
        session.flush()
        return {"ok": True, "data": {"affected": len(rows)}}

    return router
