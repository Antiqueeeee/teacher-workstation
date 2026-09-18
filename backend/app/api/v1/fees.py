"""班级费用的专用接口：概览、改应缴标准、催缴名单。

三张表的增删改查走通用链路；这里补的是**汇总**（状态是推导值，通用统计按列分组
算不出来）与两个需要跨表计算的入口。
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.schemas.registry import FEE_CATEGORY
from app.services.class_scope import resolve_class_id
from app.services.fee_service import (
    category_summary,
    class_students_missing_records,
    get_category,
    overview,
    student_owing,
    totals_for_status,
    update_category_amount,
)
from app.services.params import as_int

router = APIRouter(prefix="/fees", tags=["班级费用"])


@router.get("/overview")
def get_overview(request: Request, session: Session = Depends(get_session)):
    """全班费用概览：每个项目的应收/已收/未收 + 流水收支余额 + 合计。"""
    class_id = resolve_class_id(FEE_CATEGORY, request.query_params.get("classId"), session)
    data = overview(session, class_id)
    data["statusCounts"] = totals_for_status(session, class_id)
    return {"ok": True, "data": data}


@router.get("/categories/{category_id}")
def get_category_detail(category_id: int, session: Session = Depends(get_session)):
    """一个项目的明细数字 + 催缴名单 + 「一条记录都没有」的学生名单。"""
    category = get_category(session, category_id)
    return {
        "ok": True,
        "data": {
            **category_summary(session, category),
            "owing": student_owing(session, category.id),
            "missing": class_students_missing_records(session, category),
        },
    }


@router.put("/categories/{category_id}/amount")
def put_amount(category_id: int, body: dict = Body(default_factory=dict), session: Session = Depends(get_session)):
    """改每人应缴标准。

    **默认不回填历史记录** —— 应缴是收钱那一刻的约定。要回填得显式传 `backfill=true`，
    而且只回填一分钱都没缴过的记录（已缴过的改了会凭空变成「部分缴纳」）。
    """
    result = update_category_amount(
        session,
        category_id,
        as_int(body.get("amountCents"), "金额（分）"),
        backfill=bool(body.get("backfill")),
    )
    return {"ok": True, "data": result}
