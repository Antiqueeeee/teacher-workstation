"""班级归属解析：编辑接口与导入接口共用同一份逻辑。

单班级场景下前端**不需要传 classId**（老师自己部署，通常就一个班，不该被班级概念打扰）；
多班又没指定时明确报错，而不是静默写错班 —— 这是「多班」这个需求最容易翻车的地方。

（依赖 `app.api.errors` 是刻意的：那个模块不含任何 FastAPI 依赖，服务层仍然可以脱离
HTTP 单测，符合 CONTRIBUTING §2 的约束。）
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import CLASS_ID_REQUIRED, INVALID_VALUE, ApiError
from app.models.class_ import Class
from app.schemas.registry import TableSpec
from app.services.params import as_int


def resolve_class_id(spec: TableSpec, raw: Any, session: Session) -> int | None:
    """返回本次操作应归属的班级 id；非班级范围的表返回 None。"""
    if not spec.class_scoped:
        return None

    if raw not in ("", None):
        class_id = as_int(raw, "classId")
        if session.get(Class, class_id) is None:
            raise ApiError(INVALID_VALUE, "指定的班级不存在", detail={"classId": class_id})
        return class_id

    ids = list(session.scalars(select(Class.id).where(Class.deleted_at.is_(None))))
    if not ids:
        raise ApiError(CLASS_ID_REQUIRED, "还没有班级，请先创建班级", status=409)
    if len(ids) > 1:
        # 界面上暂时没有班级切换器（多班在后续阶段），所以这句话必须说实话，
        # 不能让用户去找一个不存在的东西
        raise ApiError(
            CLASS_ID_REQUIRED,
            "这份数据里有多个班级，而当前版本还没有班级切换界面（多班在后续阶段）。",
            status=409,
        )
    return ids[0]
