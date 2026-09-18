"""首页与数据看板的聚合接口。

**口径不在这里**：每个数都从各模块自己的口径服务取（出勤率、提交率、待跟进）。
首页与详情页显示的必须是同一个数 —— 旧应用首页那张「作业待收」卡片读的是两个
不存在的字段，所以恒为 0，而列表页另有一套算法。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.schemas.registry import CONTACT
from app.services.analytics_service import followups, overview
from app.services.class_scope import resolve_class_id

router = APIRouter(prefix="/analytics", tags=["首页与看板"])


def _class_id(request: Request, session: Session) -> int:
    return resolve_class_id(CONTACT, request.query_params.get("classId"), session)


@router.get("/overview")
def get_overview(request: Request, session: Session = Depends(get_session)):
    """首页 KPI 与今日待办要的数。"""
    return {"ok": True, "data": overview(session, _class_id(request, session))}


@router.get("/followups")
def get_followups(request: Request, session: Session = Depends(get_session)):
    """跨模块的「需要我跟进」清单（按权重排，每条都能跳到具体记录）。"""
    try:
        limit = int(request.query_params.get("limit") or 14)
    except ValueError:
        limit = 14
    return {"ok": True, "data": followups(session, _class_id(request, session), limit)}
