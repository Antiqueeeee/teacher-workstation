"""家长联系日志的读写接口。

通用 CRUD 已经覆盖了列表/表单/导入导出，这里只补一件它做不到的事：
**跟进清单** —— 首页「需要我跟进」与这个接口读的是同一个
`services/contact_service.follow_ups`（只是首页多给一个时间窗），
不让两边各筛一遍（旧应用首页与列表页确实各算各的）。

（附件计数早就收敛到 `media_service.attach_counts` 了，不在这里。）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.schemas.registry import CONTACT
from app.services.class_scope import resolve_class_id
from app.services.contact_service import follow_ups as list_follow_ups

router = APIRouter(prefix="/contacts", tags=["家长联系日志"])


@router.get("/follow-ups")
def follow_ups(request: Request, session: Session = Depends(get_session)):
    """标记了「待再次联系」的记录（首页跟进清单用同一个函数）。

    放在专用接口里而不是让前端筛：这条口径要与首页卡片一致。
    """
    class_id = resolve_class_id(CONTACT, request.query_params.get("classId"), session)
    limit = max(1, min(int(request.query_params.get("limit") or 14), 100))
    rows = list_follow_ups(session, class_id, limit=limit)
    return {
        "ok": True,
        "data": [
            {
                "id": row.id,
                "date": row.date.isoformat(),
                "studentId": row.student_id,
                "studentName": row.student_name,
                "channel": row.channel,
                "category": row.category,
                "result": row.result,
                "content": row.content,
            }
            for row in rows
        ],
    }
