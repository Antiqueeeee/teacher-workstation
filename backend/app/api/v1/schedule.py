"""课程表的专用接口：一周的网格视图。

一格一门课（`UNIQUE(class_id, weekday_no, period)`），这里把它排成星期 × 节次的
二维表给界面直接渲染 —— 排格子这件事在后端做，界面不必知道 PERIODS 的顺序。
课表本身的增删改查走通用链路（`/schedule_slots`）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.session import db_session
from app.schemas.registry import SLOT
from app.services.class_scope import resolve_class_id
from app.services.schedule_service import week_view

router = APIRouter(prefix="/schedule", tags=["课程表"])


@router.get("/week")
def get_week(request: Request, session: Session = Depends(db_session)):
    """一周的课表（空位也在，界面直接铺格子）。"""
    class_id = resolve_class_id(SLOT, request.query_params.get("classId"), session)
    return {"ok": True, "data": week_view(session, class_id)}
