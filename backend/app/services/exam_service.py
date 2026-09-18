"""考试的写入规则：科目的维护、成绩录入表、以及本场成绩的清理。

两条与「不静默丢数据」有关的纪律：

1. **移出一个科目之前先看它有没有成绩**：有成绩就拒绝并说清有多少条，
   而不是连成绩一起删掉（旧应用删考试是直接连带删成绩，且不问一声）。
2. **分数与「缺考」互斥、分数不能超过本场满分**：这两条都在写入时校验。
   旧应用的单科输入框把 `max` 硬编码成 150（`:14721`），100 分制的科目也能填 200，
   而及格线按比例算 —— 于是「考得越高越离谱」这种错它自己发现不了。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, NOT_FOUND, ApiError
from app.models.exam import Exam, ExamSubject, Score
from app.models.vocab import DEFAULT_FULL_MARKS, SUBJECTS, subject_order
from app.services.params import as_int
from app.services.roster import list_class_students
from app.services.score_stats import exam_subject_map, subject_sheet


def apply_exam(values: dict[str, Any], session: Session, row: Any = None) -> Callable[[Any], None] | None:
    """新建考试时把科目表建出来。

    这场考试考哪几科、每科满分多少，必须**在考试创建的那一刻就确定**，
    所以默认按词表建全 9 科（沿用旧应用的 DEFAULT_FULL），老师再按实际删减。
    没有这一步，「本场满分」就只能靠遍历学生成绩的 key 去猜 —— 旧应用就是这么做的。
    """
    if row is not None:
        return None

    def after_save(saved: Any) -> None:
        for subject in SUBJECTS:
            session.add(
                ExamSubject(
                    exam_id=saved.id,
                    subject=subject,
                    full_marks=DEFAULT_FULL_MARKS[subject],
                )
            )
        session.flush()

    return after_save


def get_exam(session: Session, exam_id: int) -> Exam:
    """按 id 取一场未删除的考试，取不到给一句能看懂的话（不是 500）。"""
    exam = session.get(Exam, exam_id)
    if exam is None or exam.deleted_at is not None:
        raise ApiError(NOT_FOUND, "这场考试不存在，可能已被删除", status=404, detail={"examId": exam_id})
    return exam


def set_subjects(session: Session, exam: Exam, raw_items: Any) -> list[dict[str, Any]]:
    """整批设置这场考试的科目与满分。

    已有成绩的科目**不能直接移出**：先让老师知道会连带删掉多少条成绩，
    确认后再调 `clear` 或先把成绩挪走。静默删成绩是旧应用最贵的一类 bug。
    """
    if not isinstance(raw_items, list) or not raw_items:
        raise ApiError(INVALID_VALUE, "至少要有科目", detail={"field": "subjects"})

    wanted: dict[str, int] = {}
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            raise ApiError(INVALID_VALUE, f"第 {index} 项不是一条科目设置", detail={"index": index})
        subject = str(item.get("subject") or "").strip()
        if subject not in SUBJECTS:
            raise ApiError(
                INVALID_VALUE,
                f"认不出的科目「{subject}」，只能是{'、'.join(SUBJECTS)}",
                detail={"index": index, "field": "subject"},
            )
        full_marks = as_int(item.get("fullMarks"), f"{subject}的满分")
        if not 1 <= full_marks <= 1000:
            raise ApiError(
                INVALID_VALUE, f"{subject}的满分要在 1–1000 之间", detail={"field": "fullMarks"}
            )
        wanted[subject] = full_marks

    existing = {row.subject: row for row in session.scalars(
        select(ExamSubject).where(ExamSubject.exam_id == exam.id)
    )}

    # 先检查再动手：移出科目的同时会丢掉它的成绩，所以要拦在这里
    dropped = [subject for subject in existing if subject not in wanted]
    if dropped:
        counts = dict(
            session.execute(
                select(Score.subject, func.count())
                .where(Score.exam_id == exam.id, Score.subject.in_(dropped))
                .group_by(Score.subject)
            ).all()
        )
        if counts:
            detail = "、".join(f"{subject} {count} 条" for subject, count in counts.items())
            raise ApiError(
                INVALID_VALUE,
                f"这些科目已经有成绩了：{detail}。移出科目会连带删掉成绩，"
                "请先在成绩录入表里清掉，或确认后再改。",
                detail={"subjects": list(counts)},
            )

    for subject in dropped:
        session.delete(existing[subject])
    for subject, full_marks in wanted.items():
        row = existing.get(subject)
        if row is None:
            session.add(ExamSubject(exam_id=exam.id, subject=subject, full_marks=full_marks))
        else:
            row.full_marks = full_marks
    session.flush()
    return subject_sheet(session, exam)


def clear_scores(session: Session, exam: Exam) -> int:
    """清空本场成绩（考试本身留着）。返回删掉的条数。"""
    removed = session.execute(delete(Score).where(Score.exam_id == exam.id)).rowcount or 0
    session.flush()
    return removed


@dataclass
class CellInput:
    student_id: int
    subject: str
    value: float | None
    absent: bool


def parse_cells(raw: Any) -> list[CellInput]:
    """解析成绩录入表的提交体。形状不对时给说得清的错误，而不是 500。"""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ApiError(INVALID_VALUE, "成绩数据需要是一个数组", detail={"field": "cells"})

    cells: list[CellInput] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ApiError(INVALID_VALUE, f"第 {index} 项不是一格成绩", detail={"index": index})
        subject = str(item.get("subject") or "").strip()
        absent = bool(item.get("absent"))
        raw_value = item.get("value")
        value: float | None = None
        if raw_value not in (None, ""):
            try:
                value = round(float(str(raw_value).strip()), 1)
            except (TypeError, ValueError):
                raise ApiError(
                    INVALID_VALUE, f"第 {index} 项的分数不是数字", detail={"index": index}
                ) from None
        cells.append(
            CellInput(
                student_id=as_int(item.get("studentId"), f"第 {index} 项的学生"),
                subject=subject,
                value=value,
                absent=absent,
            )
        )
    return cells


def save_cells(session: Session, exam: Exam, cells: list[CellInput]) -> dict[str, int]:
    """按格覆盖提交成绩。

    语义是**按格修改**（而不是整天覆盖）：老师填哪格就改哪格，
    没提到的格原样不动 —— 成绩表有几十行几十列，全量覆盖太容易因为界面没滚动到
    而把别的格子清掉。清空某一格用 `value=null, absent=false` 明确表达。

    班级取自考试本身（`exam.class_id`），不接受客户端指定 ——
    否则会出现「往 A 班的考试里写 B 班学生的成绩」。
    """
    full_map = exam_subject_map(session, exam.id)
    roster = {student.id: student for student in list_class_students(session, exam.class_id)}

    existing = {
        (row.student_id, row.subject): row
        for row in session.scalars(select(Score).where(Score.exam_id == exam.id))
    }

    created = updated = removed = 0
    for cell in cells:
        if cell.subject not in full_map:
            raise ApiError(
                INVALID_VALUE,
                f"「{cell.subject}」不在本场考试的科目里，请先在考试管理里加上这一科",
                detail={"field": "subject"},
            )
        if cell.student_id not in roster:
            raise ApiError(
                INVALID_VALUE,
                "名单里有学生不在本班（可能刚转班或已被删除），请刷新页面后重试",
                detail={"studentId": cell.student_id},
            )
        if cell.absent and cell.value is not None:
            raise ApiError(
                INVALID_VALUE,
                "缺考与分数不能同时有：缺考的格子不该填分",
                detail={"studentId": cell.student_id, "subject": cell.subject},
            )

        full_marks = full_map[cell.subject]
        if cell.value is not None and not 0 <= cell.value <= full_marks:
            raise ApiError(
                INVALID_VALUE,
                f"分数要在 0–{full_marks} 之间（{cell.subject}的满分是 {full_marks}）",
                detail={"studentId": cell.student_id, "subject": cell.subject, "value": cell.value},
            )

        key = (cell.student_id, cell.subject)
        row = existing.get(key)

        if cell.value is None and not cell.absent:
            # 明确清空这一格
            if row is not None:
                session.delete(row)
                removed += 1
            continue

        if row is None:
            session.add(
                Score(
                    class_id=exam.class_id,
                    exam_id=exam.id,
                    student_id=cell.student_id,
                    student_name=roster[cell.student_id].name,
                    subject=cell.subject,
                    value=cell.value,
                    absent=cell.absent,
                )
            )
            created += 1
        else:
            row.value = cell.value
            row.absent = cell.absent
            row.student_name = roster[cell.student_id].name
            updated += 1

    session.flush()
    return {"created": created, "updated": updated, "removed": removed}


def sheet_view(session: Session, exam: Exam) -> dict[str, Any]:
    """成绩录入表：科目列 + 每个学生的每一格。

    一次给全，界面不必自己拼 —— 「这场考了哪几科」只能有一个来源，
    否则录入表的列和统计的分母会漂成两套。
    """
    subjects = subject_sheet(session, exam)
    subject_names = [item["subject"] for item in subjects]

    students = sorted(
        list_class_students(session, exam.class_id),
        key=lambda student: (student.sno, student.name, student.id),
    )
    cells: dict[tuple[int, str], dict[str, Any]] = {}
    for row in session.scalars(select(Score).where(Score.exam_id == exam.id)):
        if row.subject in subject_names:
            cells[(row.student_id, row.subject)] = {
                "value": row.value,
                "absent": row.absent,
            }

    return {
        "examId": exam.id,
        "examName": exam.name,
        "examDate": exam.date.isoformat(),
        "classId": exam.class_id,
        "subjects": subjects,
        # 全部可选科目：界面上的「科目与满分」要能把删掉的科目加回来，
        # 而前端不该自己维护一份词表（那就是两处描述同一件事）
        "allSubjects": list(SUBJECTS),
        "students": [
            {
                "studentId": student.id,
                "studentName": student.name,
                "sno": student.sno,
                "cells": {
                    subject: cells.get((student.id, subject), {"value": None, "absent": False})
                    for subject in subject_names
                },
            }
            for student in students
        ],
    }


def students_without_scores(session: Session, exam: Exam) -> list[str]:
    """这场考试一条成绩都没有的学生姓名 —— 录入表顶部的提醒用。

    旧应用在这里是「没建 scores 记录的学生不计入参考人数」，于是参考人数不等于
    全班人数，而界面上看不出少了谁。
    """
    scored = set(session.scalars(select(Score.student_id).where(Score.exam_id == exam.id)))
    return [student.name for student in list_class_students(session, exam.class_id) if student.id not in scored]
