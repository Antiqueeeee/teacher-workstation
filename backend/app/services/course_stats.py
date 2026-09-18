"""学科与成绩的**统计与看板**：各场考试的统计与分析、成绩生长曲线、课程看板。

与 `course_service.py` 的分工：那边是「取记录 + 名称解析 + 保存钩子」（写入口），
这里是**只读**的聚合（看板卡片、课程详情、成绩分析）。拆开是因为两边都在长：
写入口要跟着字段声明走，聚合要跟着界面要的数走。

两个口径上的要害（在这一处实现，界面只显示）：

- **及格按满分算的得分率**：`models/course.py:score_passed` —— 旧应用写死 60 分，
  150 分制的科目全错；分析文字的阈值（80%/40 分）同样改成作用在得分率上。
- **名次用 `score_stats.rank_of`**：与考试报表同一份「同分并列」实现，
  旧应用按数组顺序给名次，换个顺序同一个班的排名就变了。
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.class_ import Class
from app.models.course import Course, CourseClass, CourseScore, CourseStudent
from app.models.exam import PASS_RATIO
from app.models.homework import Homework
from app.services.course_service import class_labels, course_class_ids, get_course
from app.services.score_stats import rank_of

# 分析文字的阈值，**都作用在得分率上**（旧应用写死 80% 与 40 分，见模块说明）
WEAK_PASS_RATE = 80.0  # 及格率低于它 → 提醒重点帮扶
GOOD_AVG_RATE = 80.0
MID_AVG_RATE = 60.0
WIDE_GAP_RATE = 40.0  # 最高与最低得分率相差这么多 → 两极分化明显

__all__ = [
    "analysis_notes",
    "course_detail",
    "course_overview",
    "exam_analysis",
    "exam_stat",
    "growth_series",
]



def _score_rows(session: Session, course_id: int, class_id: int | None = None) -> list[CourseScore]:
    stmt = select(CourseScore).where(
        CourseScore.course_id == course_id, CourseScore.deleted_at.is_(None)
    )
    if class_id:
        stmt = stmt.where(CourseScore.class_id == class_id)
    return list(session.scalars(stmt.order_by(CourseScore.exam_date, CourseScore.id)))


def _exam_groups(rows: list[CourseScore]) -> list[tuple[str, list[CourseScore]]]:
    """按考试名分组，**按考试日期排**（同一天按录入顺序）。

    旧应用按数组顺序分组，会把「最近一场」取成更早的那一场，进步/退步的方向整个反过来。
    """
    groups: dict[str, list[CourseScore]] = {}
    for row in rows:
        groups.setdefault(row.exam_name, []).append(row)
    return sorted(groups.items(), key=lambda item: (item[1][0].exam_date, item[0]))


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _ranked(rows: list[CourseScore]) -> list[tuple[CourseScore, int | None]]:
    """按**得分率**排名（同一场里满分不一致时，按原始分会把 150 分制的学生排到第一）。

    满分缺失（算不出得分率）的行不占名次 —— 与考试报表「缺考不排名」同一条规矩。
    """
    scored = [row for row in rows if row.rate is not None]
    ranks = rank_of([float(row.rate) for row in scored])
    pairs = list(zip(scored, ranks)) + [(row, None) for row in rows if row.rate is None]
    pairs.sort(key=lambda item: (item[1] is None, item[1] or 0, item[0].student_name))
    return pairs


def exam_stat(
    session: Session,
    exam_name: str,
    rows: list[CourseScore],
    labels: dict[int, str] | None = None,
) -> dict[str, Any]:
    """一场课程考试的统计：平均分、平均得分率、及格率、名次、分析文字。"""
    labels = labels if labels is not None else class_labels(session)
    pairs = _ranked(rows)
    counts = Counter(rank for _row, rank in pairs if rank is not None)
    rates = [row.rate for row, _rank in pairs if row.rate is not None]
    scores = [row.score for row, _rank in pairs]
    dates = [row.exam_date for row, _rank in pairs]
    full_marks = {row.full_marks for row, _rank in pairs}
    pass_count = sum(1 for row, _rank in pairs if row.passed)

    ranked = [
        {
            "id": row.id,
            "studentId": row.student_id,
            "studentName": row.student_name,
            "sno": row.sno,
            "className": labels.get(row.class_id, ""),
            "score": row.score,
            "fullMarks": row.full_marks,
            "rate": row.rate,
            "rank": rank,
            "tied": bool(rank is not None and counts[rank] > 1),
            "passed": row.passed,
            # 界面上要能直接编辑这一条（编辑表单要日期与备注）
            "examName": row.exam_name,
            "examDate": row.exam_date.isoformat(),
            "note": row.note,
        }
        for row, rank in pairs
    ]
    stat: dict[str, Any] = {
        "examName": exam_name,
        "examDate": min(dates).isoformat() if dates else None,
        "dates": sorted({day.isoformat() for day in dates}),
        "taken": len(rates),
        "rows": len(pairs),
        # 满分在整场一致时给一个数；不一致（个别录错）时给 None，界面按行显示各自的满分
        "fullMarks": next(iter(full_marks)) if len(full_marks) == 1 else None,
        "mixedFullMarks": len(full_marks) > 1,
        "avg": _mean([float(score) for score in scores]),
        "avgRate": _mean([float(rate) for rate in rates]),
        "highest": max(scores) if scores else None,
        "lowest": min(scores) if scores else None,
        "passCount": pass_count,
        "passRate": round(pass_count / len(rates) * 100, 1) if rates else None,
        "ranked": ranked,
    }
    stat["notes"] = analysis_notes(stat)
    return stat


def analysis_notes(stat: dict[str, Any]) -> list[str]:
    """按本场数据生成的文字分析（阈值都作用在得分率上，见模块说明）。"""
    if not stat["taken"]:
        return ["这一场还没有能算得分率的成绩"]
    notes = [
        f"参考 {stat['taken']} 人次 · 平均 {stat['avg']} 分 · "
        f"最高 {stat['highest']} 分 · 最低 {stat['lowest']} 分",
        f"平均得分率 {stat['avgRate']}% · 及格率 {stat['passRate']}%",
    ]
    if stat["mixedFullMarks"]:
        notes.append("这一场里有不同的满分：得分率与及格都按各自满分算，请核对是否录错")
    if stat["passRate"] is not None and stat["passRate"] < WEAK_PASS_RATE:
        notes.append("及格率偏低，建议重点帮扶后进生、安排结对辅导")
    avg_rate = stat["avgRate"]
    if avg_rate is not None:
        if avg_rate >= GOOD_AVG_RATE:
            notes.append("整体水平良好，可适当提高训练难度")
        elif avg_rate >= MID_AVG_RATE:
            notes.append("整体中等，课堂巩固与错题复盘有提升空间")
        else:
            notes.append("整体偏弱，建议放缓节奏、夯实基础并加强个别辅导")
    rates = [item["rate"] for item in stat["ranked"] if item["rate"] is not None]
    if len(rates) > 1 and max(rates) - min(rates) >= WIDE_GAP_RATE:
        notes.append("两极分化较明显，建议分层作业、以强带弱")
    ranked = [item for item in stat["ranked"] if item["rank"] is not None]
    if len(ranked) > 1:
        notes.append(f"榜首 {ranked[0]['studentName']}，需加油的是 {ranked[-1]['studentName']}")
    return notes


def growth_series(exam_stats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """每个学生的成绩生长曲线：横轴是考试场次，纵轴是**得分率**（不是原始分）。

    旧应用画的是原始分（`:14963`），150 分制与 100 分制画在同一张图上没有可比性，
    而且纵轴被写死在 100，150 分制的点全落在框外。
    """
    by_student: dict[int, dict[str, Any]] = {}
    for stat in exam_stats:
        for item in stat["ranked"]:
            if item["rate"] is None:
                continue
            entry = by_student.setdefault(
                item["studentId"],
                {
                    "studentId": item["studentId"],
                    "studentName": item["studentName"],
                    "className": item["className"],
                    "points": [],
                },
            )
            entry["points"].append(
                {
                    "label": stat["examName"],
                    "date": stat["examDate"],
                    "value": item["rate"],
                    "score": item["score"],
                    "fullMarks": item["fullMarks"],
                    "rank": item["rank"],
                }
            )
    for entry in by_student.values():
        values = [point["value"] for point in entry["points"]]
        entry["latest"] = values[-1] if values else None
        entry["delta"] = round(values[-1] - values[-2], 1) if len(values) > 1 else None
    series = [entry for entry in by_student.values() if entry["points"]]
    series.sort(key=lambda entry: (-(entry["latest"] or 0), entry["studentName"]))
    return series


def exam_analysis(session: Session, course_id: int, class_id: int | None = None) -> dict[str, Any]:
    """课程成绩页要的全部东西：各场统计、分析文字、生长曲线。"""
    course = get_course(session, course_id)
    rows = _score_rows(session, course.id, class_id)
    labels = class_labels(session)
    stats = [exam_stat(session, name, group, labels) for name, group in _exam_groups(rows)]
    return {
        "courseId": course.id,
        "courseName": course.name,
        "subject": course.subject,
        "passRatio": PASS_RATIO,
        "exams": stats,
        # 只有一场考试时不给曲线：一个点连不成趋势，硬画出来会让人以为「一直持平」
        "series": growth_series(stats) if len(stats) > 1 else [],
    }


def course_overview(session: Session) -> dict[str, Any]:
    """课程看板的卡片数据：每门课的班级数/人数/课时/作业与提交率/最近一场成绩。"""
    courses = list(
        session.scalars(select(Course).where(Course.deleted_at.is_(None)).order_by(Course.id))
    )
    labels = class_labels(session)
    cards = []
    for course in courses:
        stats = [
            exam_stat(session, name, group, labels)
            for name, group in _exam_groups(_score_rows(session, course.id))
        ]
        latest = stats[-1] if stats else None
        cards.append(
            {
                "id": course.id,
                "name": course.name,
                "subject": course.subject,
                "teacher": course.teacher,
                "term": course.term,
                "hours": course.hours,
                "classCount": len(course_class_ids(session, course.id)),
                "studentCount": _course_student_count(session, course.id),
                "homeworkCount": _course_homework(session, course.id)[0],
                # 提交率均值只统计**算得出提交率**的作业（应交 0 人时是 null，不拉低均值）
                "homeworkRate": _course_homework(session, course.id)[1],
                "scoreCount": _course_score_count(session, course.id),
                "examCount": len(stats),
                "latestExam": (
                    {
                        "examName": latest["examName"],
                        "examDate": latest["examDate"],
                        "taken": latest["taken"],
                        "avg": latest["avg"],
                        "avgRate": latest["avgRate"],
                        "passRate": latest["passRate"],
                    }
                    if latest
                    else None
                ),
            }
        )
    return {
        "courses": cards,
        "totals": {
            "courseCount": len(cards),
            "classCount": sum(card["classCount"] for card in cards),
            "homeworkCount": sum(card["homeworkCount"] for card in cards),
            "scoreCount": sum(card["scoreCount"] for card in cards),
        },
    }


def _course_student_count(session: Session, course_id: int) -> int:
    """这门课名单上的**去重人数**（一个学生可能同时挂在两门课的名单里，那不算两个人）。"""
    return int(
        session.scalar(
            select(func.count(func.distinct(CourseStudent.student_id)))
            .select_from(CourseStudent)
            .join(CourseClass, CourseClass.id == CourseStudent.course_class_id)
            .where(
                CourseClass.course_id == course_id,
                CourseClass.deleted_at.is_(None),
                CourseStudent.deleted_at.is_(None),
            )
        )
        or 0
    )


def _course_homework(session: Session, course_id: int) -> tuple[int, float | None]:
    """这门课的作业数与提交率均值 —— 提交率读 `homework.rate`（唯一那份口径算出来的）。"""
    count, rate = session.execute(
        select(func.count(), func.avg(Homework.rate)).where(
            Homework.course_id == course_id, Homework.deleted_at.is_(None)
        )
    ).one()
    return int(count or 0), (round(rate, 1) if rate is not None else None)


def _course_score_count(session: Session, course_id: int) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(CourseScore).where(
                CourseScore.course_id == course_id, CourseScore.deleted_at.is_(None)
            )
        )
        or 0
    )


def course_detail(session: Session, course_id: int) -> dict[str, Any]:
    """课程页要的班级块、名单、每班作业与成绩概览（一次查完，不逐条查）。"""
    course = get_course(session, course_id)
    blocks = list(
        session.scalars(
            select(CourseClass)
            .where(CourseClass.course_id == course.id, CourseClass.deleted_at.is_(None))
            .order_by(CourseClass.id)
        )
    )
    block_ids = [block.id for block in blocks]
    students: dict[int, list[CourseStudent]] = {block_id: [] for block_id in block_ids}
    if block_ids:
        for row in session.scalars(
            select(CourseStudent)
            .where(CourseStudent.course_class_id.in_(block_ids), CourseStudent.deleted_at.is_(None))
            .order_by(CourseStudent.id)
        ):
            students.setdefault(row.course_class_id, []).append(row)

    homework: dict[int, tuple[int, float | None]] = {}
    for class_id, count, rate in session.execute(
        select(Homework.class_id, func.count(), func.avg(Homework.rate))
        .where(Homework.course_id == course.id, Homework.deleted_at.is_(None))
        .group_by(Homework.class_id)
    ):
        homework[class_id] = (int(count or 0), round(rate, 1) if rate is not None else None)

    score_counts: dict[int, int] = {}
    for class_id, count in session.execute(
        select(CourseScore.class_id, func.count())
        .where(CourseScore.course_id == course.id, CourseScore.deleted_at.is_(None))
        .group_by(CourseScore.class_id)
    ):
        score_counts[class_id] = int(count or 0)

    labels = class_labels(session)
    return {
        "course": {
            "id": course.id,
            "name": course.name,
            "subject": course.subject,
            "teacher": course.teacher,
            "hours": course.hours,
            "term": course.term,
            "note": course.note,
        },
        "classes": [
            {
                "id": block.id,
                "classId": block.class_id,
                "className": block.class_name or labels.get(block.class_id, ""),
                "headTeacher": block.head_teacher,
                "headTeacherPhone": block.head_teacher_phone,
                "representative": block.representative,
                "repPhone": block.rep_phone,
                "progress": block.progress,
                "studentCount": len(students.get(block.id, [])),
                "homeworkCount": homework.get(block.class_id, (0, None))[0],
                "homeworkRate": homework.get(block.class_id, (0, None))[1],
                "scoreCount": score_counts.get(block.class_id, 0),
                "students": [
                    {
                        "id": row.id,
                        "studentId": row.student_id,
                        "studentName": row.student_name,
                        "sno": row.sno,
                    }
                    for row in students.get(block.id, [])
                ],
            }
            for block in blocks
        ],
    }
