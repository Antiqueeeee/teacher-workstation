"""出勤的两个专用接口：**按天点名**（整体覆盖）与**区间小结**。

为什么不能只靠通用 CRUD：
1. 点名是「一天一次、整批提交」的动作，逐条增删改会在中途失败时留下半天的数据；
2. 出勤率必须由后端算（见 `services/attendance_rate.py`），界面不能自己数记录条数 ——
   旧应用的三处出勤率就是这么漂掉的。

**注册顺序**：本路由必须在 `/{key}/{row_id}` 之前挂载，否则 `/attendance/day` 里的
`day` 会被当成 id 去解析（`student_fields` 踩过同一个坑）。
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy.orm import Session

from app.api.session import db_session
from app.schemas.registry import ATTENDANCE
from app.services.attendance_rate import range_summary
from app.services.attendance_service import day_view, parse_entries, roll_call
from app.services.class_scope import resolve_class_id
from app.services.params import as_date

router = APIRouter(prefix="/attendance", tags=["出勤记录"])


@router.get("/day")
def get_day(request: Request, session: Session = Depends(db_session)):
    """某天的点名表：全班名单 + 每人当天状态 + 当天小结。"""
    params = request.query_params
    day = as_date(params.get("date"), "date")
    class_id = resolve_class_id(ATTENDANCE, params.get("classId"), session)
    return {"ok": True, "data": day_view(session, class_id, day)}


@router.put("/day")
def put_day(
    body: dict = Body(default_factory=dict), session: Session = Depends(db_session)
):
    """按天整体提交点名结果：当天状态以这次提交为准（含被改回「正常」的）。"""
    day = as_date(body.get("date"), "date")
    class_id = resolve_class_id(ATTENDANCE, body.get("classId"), session)
    changes = roll_call(session, class_id, day, parse_entries(body.get("entries")))
    # 返回提交后的完整状态：界面不用再猜自己刚写完的数据长什么样
    return {"ok": True, "data": {"changes": changes.to_dict(), **day_view(session, class_id, day)}}


@router.get("/summary")
def summary(request: Request, session: Session = Depends(db_session)):
    """区间小结：看板、趋势图、代课简报、首页卡片读的都是这一个结果。"""
    params = request.query_params
    start = as_date(params.get("from"), "from")
    end = as_date(params.get("to") or params.get("from"), "to")
    class_id = resolve_class_id(ATTENDANCE, params.get("classId"), session)
    return {"ok": True, "data": range_summary(session, class_id, start, end).to_dict()}
