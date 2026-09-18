"""首页与数据看板的聚合接口。

**口径不在这里**：每个数都从各模块自己的口径服务取（出勤率、提交率、待跟进）。
首页与详情页显示的必须是同一个数 —— 旧应用首页那张「作业待收」卡片读的是两个
不存在的字段，所以恒为 0，而列表页另有一套算法。
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.session import db_session
from app.schemas.registry import CONTACT
from app.services.analytics_service import dashboard, followups, overview, substitute_brief, timeline
from app.services.class_scope import resolve_class_id
from app.services.params import as_date

router = APIRouter(prefix="/analytics", tags=["首页与看板"])


def _class_id(request: Request, session: Session) -> int:
    return resolve_class_id(CONTACT, request.query_params.get("classId"), session)


@router.get("/overview")
def get_overview(request: Request, session: Session = Depends(db_session)):
    """首页 KPI 与今日待办要的数。"""
    return {"ok": True, "data": overview(session, _class_id(request, session))}


@router.get("/followups")
def get_followups(request: Request, session: Session = Depends(db_session)):
    """跨模块的「需要我跟进」清单（按权重排，每条都能跳到具体记录）。"""
    try:
        limit = int(request.query_params.get("limit") or 14)
    except ValueError:
        limit = 14
    return {"ok": True, "data": followups(session, _class_id(request, session), limit)}


@router.get("/substitute")
def get_substitute(request: Request, session: Session = Depends(db_session)):
    """代课/交接简报：某一天的班级情况（考勤、体质、班委、班规、违纪、值日、座位图）。"""
    params = request.query_params
    day = as_date(params.get("date") or date.today().isoformat(), "date")
    return {"ok": True, "data": substitute_brief(session, _class_id(request, session), day)}


@router.get("/dashboard")
def get_dashboard(request: Request, session: Session = Depends(db_session)):
    """数据看板：出勤趋势、违纪分布与 Top、沟通/大事记月度走势。

    口径都从各模块自己的服务取（未登记的日子在趋势里是**空**，不是 100%）。
    """
    params = request.query_params
    try:
        days = int(params.get("days") or 14)
    except ValueError:
        days = 14
    return {"ok": True, "data": dashboard(session, _class_id(request, session), days=days)}


@router.get("/timeline")
def get_timeline(request: Request, session: Session = Depends(db_session)):
    """学期时间轴：把几类留档按日期合成一条时间线（分页取） 。"""
    params = request.query_params
    try:
        limit = int(params.get("limit") or 50)
    except ValueError:
        limit = 50
    return {
        "ok": True,
        "data": timeline(session, _class_id(request, session), limit=limit),
    }
