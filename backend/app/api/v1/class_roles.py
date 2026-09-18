"""班级角色类的专用接口：团员与档案的一致性提示。

字段本身走通用链路，这里只补一件通用链路做不了的事 ——
**把「团员名册」与「学生档案的政治面貌」对不上的人列出来**（文档 §5 要求的双向校验）。
只提示、不改写：两份数据都可能是事实（刚入团还没更新档案、或刚退团），
系统替老师选一个是最容易出怪事的设计。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.schemas.registry import YOUTH
from app.services.class_scope import resolve_class_id
from app.services.classroom_service import youth_consistency

router = APIRouter(prefix="/youth_members", tags=["团员名册"])


@router.get("/consistency")
def consistency(request: Request, session: Session = Depends(get_session)):
    class_id = resolve_class_id(YOUTH, request.query_params.get("classId"), session)
    return {"ok": True, "data": youth_consistency(session, class_id)}
