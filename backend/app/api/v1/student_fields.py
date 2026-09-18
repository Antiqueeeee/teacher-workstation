"""学生档案的**字段管理**接口。

学生档案与其它表的区别就在这里：字段是数据，不是代码。老师可以增删字段 ——
这是旧应用的真实能力，也是它比「一堆写死的列」好用的地方。

两条纪律（实现都在 `services/student_fields.py`，这里只做序列化与转发）：
1. **删字段不删数据**：只删定义，`extra` 里的值原样保留；把同名字段加回来，值还在。
   所以删除时要跟用户说清楚这一点，而不是让他以为数据没了。
2. **身份字段（姓名/学号）不可删**：记录之间对得上全靠它们。

注意：本路由必须**先于**通用的 `/students/{id}` 注册，否则 `/students/fields`
会被那条泛化路由先吃掉（`fields` 会被当成 id 解析而报错）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.models.student import StudentFieldDef
from app.services.student_fields import (
    create_def,
    delete_def,
    get_def,
    list_defs,
    update_def,
)

# 前缀是**相对**的：会被父级 `/api/v1` 再拼一次（写成绝对路径会变成 /api/v1/api/v1/...）
router = APIRouter(prefix="/students", tags=["学生档案"])


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


@router.get("/fields")
def list_fields(session: Session = Depends(get_session)) -> dict:
    return {"ok": True, "data": [_serialize(row) for row in list_defs(session)]}


@router.post("/fields", status_code=201)
def create_field(body: dict[str, Any] = Body(...), session: Session = Depends(get_session)) -> dict:
    return {"ok": True, "data": _serialize(create_def(session, body))}


@router.patch("/fields/{field_id}")
def update_field(
    field_id: int, body: dict[str, Any] = Body(...), session: Session = Depends(get_session)
) -> dict:
    return {"ok": True, "data": _serialize(update_def(session, field_id, body))}


@router.delete("/fields/{field_id}")
def delete_field(field_id: int, session: Session = Depends(get_session)) -> dict:
    get_def(session, field_id)  # 不存在就 404（与其余接口一致）
    key = delete_def(session, field_id)
    return {
        "ok": True,
        "data": {
            "key": key,
            # 说清楚数据还在，免得老师以为删掉就丢了
            "note": "已删除字段定义；该字段已有的数据仍保留在库里，把同名字段加回来即可恢复显示。",
        },
    }
