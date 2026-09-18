"""学生档案的**字段管理**接口。

学生档案与其它表的区别就在这里：字段是数据，不是代码。老师可以增删字段 ——
这是旧应用的真实能力，也是它比「一堆写死的列」好用的地方。

两条纪律：
1. **删字段不删数据**：只删定义，`extra` 里的值原样保留；把同名字段加回来，值还在。
   所以删除时要跟用户说清楚这一点，而不是让他以为数据没了。
2. **身份字段（姓名/学号）不可删**：记录之间对得上全靠它们。

注意：本路由必须**先于**通用的 `/students/{id}` 注册，否则 `/students/fields`
会被那条泛化路由先吃掉（`fields` 会被当成 id 解析而报错）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, NOT_FOUND, ApiError
from app.db.engine import get_session
from app.models.student import StudentFieldDef
from app.schemas.registry import FIELD_TYPES

# 前缀是**相对**的：会被父级 `/api/v1` 再拼一次（写成绝对路径会变成 /api/v1/api/v1/...）
router = APIRouter(prefix="/students", tags=["学生档案"])

EDITABLE_ATTRS = (
    "label",
    "type",
    "options",
    "required",
    "in_list",
    "in_form",
    "in_detail",
    "searchable",
    "filterable",
    "sort_order",
    "aliases",
    "hint",
)


def _serialize(definition: StudentFieldDef) -> dict[str, Any]:
    return {
        "id": definition.id,
        "key": definition.key,
        "label": definition.label,
        "type": definition.type,
        "options": definition.options or [],
        "required": definition.required,
        "identity": definition.identity,
        "in_list": definition.in_list,
        "in_form": definition.in_form,
        "in_detail": definition.in_detail,
        "searchable": definition.searchable,
        "filterable": definition.filterable,
        "sort_order": definition.sort_order,
        "aliases": definition.aliases or [],
        "hint": definition.hint,
    }


def _get(session: Session, field_id: int) -> StudentFieldDef:
    definition = session.get(StudentFieldDef, field_id)
    if definition is None:
        raise ApiError(NOT_FOUND, "这个字段不存在，可能已被删除", status=404, detail={"id": field_id})
    return definition


def _check_type(value: Any) -> str:
    if value not in FIELD_TYPES:
        raise ApiError(
            INVALID_VALUE,
            f"字段类型只能是：{'、'.join(FIELD_TYPES)}",
            detail={"field": "type", "value": value},
        )
    return str(value)


@router.get("/fields")
def list_fields(session: Session = Depends(get_session)) -> dict:
    rows = session.scalars(
        select(StudentFieldDef).order_by(StudentFieldDef.sort_order, StudentFieldDef.id)
    )
    return {"ok": True, "data": [_serialize(row) for row in rows]}


@router.post("/fields", status_code=201)
def create_field(body: dict[str, Any] = Body(...), session: Session = Depends(get_session)) -> dict:
    key = str(body.get("key") or "").strip()
    label = str(body.get("label") or "").strip()
    if not key or not label:
        raise ApiError(INVALID_VALUE, "字段标识与名称都必填", detail={"field": "key"})
    if not key.isascii() or not key.replace("_", "").isalnum():
        raise ApiError(
            INVALID_VALUE,
            "字段标识请用英文字母/数字/下划线（它同时是 Excel 列名匹配与数据存储用的键）",
            detail={"field": "key", "value": key},
        )
    if session.scalar(select(StudentFieldDef).where(StudentFieldDef.key == key)) is not None:
        raise ApiError(INVALID_VALUE, f"已经有一个字段叫「{key}」了", detail={"field": "key"})

    field_type = _check_type(body.get("type") or "text")
    max_order = session.scalar(
        select(StudentFieldDef.sort_order).order_by(StudentFieldDef.sort_order.desc()).limit(1)
    )
    definition = StudentFieldDef(
        key=key,
        label=label,
        type=field_type,
        options=list(body.get("options") or []),
        required=bool(body.get("required")),
        in_list=bool(body.get("in_list", True)),
        in_form=bool(body.get("in_form", True)),
        in_detail=bool(body.get("in_detail", True)),
        searchable=bool(body.get("searchable")),
        filterable=bool(body.get("filterable")),
        sort_order=int(body.get("sort_order") or (max_order or 0) + 1),
        aliases=list(body.get("aliases") or []),
        hint=str(body.get("hint") or ""),
    )
    session.add(definition)
    session.flush()
    return {"ok": True, "data": _serialize(definition)}


@router.patch("/fields/{field_id}")
def update_field(
    field_id: int, body: dict[str, Any] = Body(...), session: Session = Depends(get_session)
) -> dict:
    definition = _get(session, field_id)
    if "key" in body and str(body["key"]).strip() != definition.key:
        # 改 key 等于让历史数据失去归属：extra 里存的是旧 key
        raise ApiError(
            INVALID_VALUE,
            "字段标识不能改（数据是按它存的）。可以改名称，或删掉这个字段再新建一个。",
            detail={"field": "key"},
        )
    if "type" in body:
        body["type"] = _check_type(body["type"])
    for attr in EDITABLE_ATTRS:
        if attr in body:
            setattr(definition, attr, body[attr])
    session.flush()
    return {"ok": True, "data": _serialize(definition)}


@router.delete("/fields/{field_id}")
def delete_field(field_id: int, session: Session = Depends(get_session)) -> dict:
    definition = _get(session, field_id)
    if definition.identity:
        raise ApiError(
            INVALID_VALUE,
            f"「{definition.label}」是身份字段，不能删除（记录之间对得上全靠它）",
            detail={"field": "key", "value": definition.key},
        )
    key = definition.key
    session.delete(definition)
    session.flush()
    return {
        "ok": True,
        "data": {
            "key": key,
            # 说清楚数据还在，免得老师以为删掉就丢了
            "note": "已删除字段定义；该字段已有的数据仍保留在库里，把同名字段加回来即可恢复显示。",
        },
    }
