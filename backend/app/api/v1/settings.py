"""设置接口：班级信息、存储占用与分表行数、清空数据。

`classId` 一律由调用方给（设置页必须知道在改哪个班）——
用 `resolve_class_id` 的单班回退会让「多班时默认改第一个班」，那太危险。
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.schemas.registry import CONTACT
from app.services.class_scope import resolve_class_id
from app.services.settings_service import clear_business_data, get_class, settings_view, update_class

router = APIRouter(prefix="/settings", tags=["设置"])


def _class_id(request: Request, session: Session) -> int:
    return resolve_class_id(CONTACT, request.query_params.get("classId"), session)


@router.get("")
def read_settings(request: Request, session: Session = Depends(get_session)):
    """班级信息 + 存储占用 + 每张业务表的行数。"""
    return {"ok": True, "data": settings_view(session, _class_id(request, session))}


@router.put("/class")
def put_class(request: Request, body: dict = Body(default_factory=dict), session: Session = Depends(get_session)):
    """改班级信息（名称、年级、班主任、教室名、团支部名）。"""
    class_id = _class_id(request, session)
    row = update_class(session, class_id, body)
    return {
        "ok": True,
        "data": {
            "id": row.id,
            "grade": row.grade,
            "classNo": row.class_no,
            "name": row.name,
            "headTeacherName": row.head_teacher_name,
            "roomName": row.room_name,
            "youthBranchName": row.youth_branch_name,
        },
    }


@router.post("/clear")
def post_clear(request: Request, body: dict = Body(default_factory=dict), session: Session = Depends(get_session)):
    """清空这个班的业务数据（班级本身与字段定义保留）。

    要传 `confirm="清空"` —— 这是不可撤销的操作，不能让一次误点就把一学期的数据清掉。
    媒体文件默认不动（它有专门的清理入口）。
    """
    class_id = _class_id(request, session)
    result = clear_business_data(
        session,
        class_id,
        confirm=str(body.get("confirm") or ""),
        keep_media=bool(body.get("keepMedia", True)),
    )
    return {"ok": True, "data": result}


@router.get("/class")
def read_class(request: Request, session: Session = Depends(get_session)):
    row = get_class(session, _class_id(request, session))
    return {
        "ok": True,
        "data": {"id": row.id, "name": row.name, "grade": row.grade, "classNo": row.class_no},
    }
