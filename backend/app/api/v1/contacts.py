"""家长联系日志的读写接口。

通用 CRUD 已经覆盖了列表/表单/导入导出，这里只补两件它做不到的事：

1. **附件计数**：列表上要显示「2 张照片 · 1 段录音」，否则老师得逐条点进去看有没有录音；
   计数一次查完（`select(owner_id, count)` 分组），不是每条记录查一次。
2. **跟进清单**：首页「需要我跟进」读的就是「标记了待再次联系」的记录，
   与旧应用 `needsFollowUp === '是'` 的语义一致。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.models.contact import ContactLog
from app.schemas.registry import CONTACT
from app.services.class_scope import resolve_class_id

router = APIRouter(prefix="/contacts", tags=["家长联系日志"])


@router.get("/follow-ups")
def follow_ups(request: Request, session: Session = Depends(get_session)):
    """标记了「待再次联系」的记录（首页跟进清单用）。

    放在专用接口里而不是让前端筛：这条口径要与首页卡片一致，
    而前端各筛一遍就是第二套口径（旧应用首页与列表页确实各算各的）。
    """
    class_id = resolve_class_id(CONTACT, request.query_params.get("classId"), session)
    limit = max(1, min(int(request.query_params.get("limit") or 14), 100))
    rows = session.scalars(
        select(ContactLog)
        .where(
            ContactLog.deleted_at.is_(None),
            ContactLog.class_id == class_id,
            ContactLog.needs_follow_up.is_(True),
        )
        .order_by(ContactLog.date.asc(), ContactLog.id.asc())
        .limit(limit)
    ).all()
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
