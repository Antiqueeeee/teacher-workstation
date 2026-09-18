"""学科与成绩的专用接口：课程看板、课程详情、成绩分析、批名单。

四张表（课程/课程班级/课程名单/课程成绩）的增删改查走通用链路；这里补的是
**跨表聚合**（看板卡片、课程详情、成绩分析）与一个批量入口（按姓名一次加一批学生）。
课程作业不单独开口子 —— 它就是 `homework` 表里带 `course_id` 的行，
新增作业直接 POST `/homework` 并带上「所属课程」即可（见 `services/homework_service.py`）。

**路由顺序**：`/courses/overview` 必须在通用的 `/courses/{row_id}` 之前注册，
否则 `overview` 会被当成 id 解析（与 `/fees/overview` 同一条规矩，见 `api/router.py`）。
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, ApiError
from app.api.session import db_session
from app.services.course_service import add_students, get_course, get_course_class
from app.services.course_stats import course_detail, course_overview, exam_analysis
from app.services.params import as_int

router = APIRouter(prefix="/courses", tags=["学科与成绩"])


@router.get("/overview")
def get_overview(session: Session = Depends(db_session)):
    """课程看板：每门课的班级数/人数/课时/作业与提交率/最近一场考试。"""
    return {"ok": True, "data": course_overview(session)}


@router.get("/{course_id}/detail")
def get_detail(course_id: int, session: Session = Depends(db_session)):
    """课程详情：班级块（含班主任/课代表联系方式与进度）+ 每块的名单。"""
    return {"ok": True, "data": course_detail(session, course_id)}


@router.get("/{course_id}/analysis")
def get_analysis(
    course_id: int,
    request: Request,
    session: Session = Depends(db_session),
):
    """课程成绩分析：各场统计（含名次、及格率）、分析文字、成绩生长曲线。

    可选 `classId` 只看某个班 —— 课程可能同时教几个班。
    """
    raw = request.query_params.get("classId")
    class_id = as_int(raw, "classId") if raw not in (None, "") else None
    return {"ok": True, "data": exam_analysis(session, course_id, class_id)}


@router.post("/{course_id}/students")
def post_students(
    course_id: int,
    body: dict = Body(default_factory=dict),
    session: Session = Depends(db_session),
):
    """一次加一批学生到这个课程的某个班里（填姓名，顿号分隔）。

    与逐个新增走**同一个落库形状**（`services/course_service.add_students`）：
    认不出的人名整批不写，已在名单里的如实报出跳过几个。
    """
    block = get_course_class(session, body.get("courseClassId"))
    get_course(session, course_id)  # 课程不存在就报 404，而不是照 body 里的班级块往上加
    if block.course_id != course_id:
        raise ApiError(INVALID_VALUE, "这个班级块不属于这门课程", detail={"courseClassId": block.id})
    result = add_students(session, block, str(body.get("names") or ""))
    return {"ok": True, "data": result}
