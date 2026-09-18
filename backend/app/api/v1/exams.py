"""成绩分析的专用接口：考试的科目、成绩录入表、报表。

为什么不能只靠通用 CRUD：
1. 成绩是一张**二维表**（学生 × 科目），逐条增删改的接口撑不起录入，而且中途失败
   会留下半场数据；
2. 名次与及格率必须由后端算（见 `services/score_stats.py`）——
   旧应用三处各算一遍，名次还会因为数组顺序不同而不同；
3. 报表要一次给全（科目统计 + 每生行 + 与上一场对比），前端只负责显示。

**注册顺序**：本路由必须在 `/{key}/{row_id}` 之前挂载，否则 `/exams/{id}/sheet`
会被 `/{key}/{row_id}` 先匹配掉（`student_fields` 踩过同一个坑）。
注意这里**不注册 `GET /exams`**：考试清单走通用 CRUD，两处都注册会让后者被静默遮蔽。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.services.exam_service import (
    clear_scores,
    get_exam,
    parse_cells,
    save_cells,
    set_subjects,
    sheet_view,
    students_without_scores,
)
from app.services.score_stats import build_report, ordered_subjects

router = APIRouter(prefix="/exams", tags=["成绩分析"])


@router.get("/{exam_id}/sheet")
def get_sheet(exam_id: int, session: Session = Depends(get_session)):
    """成绩录入表：科目列（含本场满分）+ 全班每一格。"""
    exam = get_exam(session, exam_id)
    data = sheet_view(session, exam)
    # 一条成绩都没有的学生要点名提醒 —— 参考人数不等于全班人数这件事必须让人看见
    data["withoutScores"] = students_without_scores(session, exam)
    return {"ok": True, "data": data}


@router.put("/{exam_id}/sheet")
def put_sheet(
    exam_id: int, body: dict = Body(default_factory=dict), session: Session = Depends(get_session)
):
    """按格提交成绩：只改传过来的格子，没提到的格原样不动。"""
    exam = get_exam(session, exam_id)
    cells = parse_cells(body.get("cells"))
    changes = save_cells(session, exam, cells)
    return {"ok": True, "data": {"changes": changes, **sheet_view(session, exam)}}


@router.get("/{exam_id}/report")
def get_report(exam_id: int, session: Session = Depends(get_session)):
    """本场报表：名次（同分并列）、及格/优秀、单科统计、与上一场对比。

    **唯一口径**：界面、导出、首页卡片读的都是这一个结果。
    """
    exam = get_exam(session, exam_id)
    return {"ok": True, "data": build_report(session, exam).to_dict()}


@router.get("/{exam_id}/subjects")
def get_subjects(exam_id: int, session: Session = Depends(get_session)):
    exam = get_exam(session, exam_id)
    return {"ok": True, "data": ordered_subjects(session, exam.id)}


@router.put("/{exam_id}/subjects")
def put_subjects(
    exam_id: int, body: dict = Body(default_factory=dict), session: Session = Depends(get_session)
):
    """设置这场考试考哪几科、每科满分。

    改满分不需要「重算」任何东西 —— 名次与及格率都是现算的，不落库；
    旧应用把 rank/total 存在成绩行里，所以改了满分还得记得去重算（`:13251` 就是漏了这一步）。
    """
    exam = get_exam(session, exam_id)
    subjects: Any = body.get("subjects")
    return {"ok": True, "data": set_subjects(session, exam, subjects)}


@router.post("/{exam_id}/clear-scores")
def clear(exam_id: int, session: Session = Depends(get_session)):
    """清空本场成绩（考试本身留着）。返回删掉的条数。"""
    exam = get_exam(session, exam_id)
    return {"ok": True, "data": {"removed": clear_scores(session, exam)}}
