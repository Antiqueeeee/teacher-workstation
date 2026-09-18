"""评语草稿：把学生这一学期的痕迹拼成**可编辑的初稿**。

与旧应用（`:8160` `studentCommentData` + `:8262` `genComment`）的差别在两处：

1. **生成在后端**，返回**结构化维度 + 文本**：旧应用是前端把十几张表拉下来现拼，
   于是评语里的数（缺勤次数、最弱科、最近一次考试）与详情页各算一遍、口径会漂；
2. **文字是事实陈述，不是固定的抒情模板**：旧应用的模板写死了「像春日的竹笋一节一节拔高」
   这类句子，套在每个学生身上都一样。草稿里只写数据与事实，让老师用自己的口吻改 ——
   评语是老师对学生说的话，模板腔反而帮倒忙。

末尾固定一句「请人工复核」：这些结论都来自数据，而评语要对人和家长负责。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import NOT_FOUND, ApiError
from app.models.exam import Exam
from app.models.student import Student
from app.models.welfare import HealthRecord
from app.services.score_stats import build_report
from app.services.student_service import archive

# 评语里不必写、但老师该一直盯着的：给一句提醒，并说明别写进去
TEACHER_ONLY_NOTE = "（这条是给你的提醒，不必写进评语）"


def _score_dimension(session: Session, student: Student) -> dict[str, Any]:
    """学业：最近一次考试的总分/名次/与上一次的进退，以及最强与最弱科目。"""
    exams = list(
        session.scalars(
            select(Exam)
            .where(Exam.deleted_at.is_(None), Exam.class_id == student.class_id)
            .order_by(Exam.date.desc(), Exam.id.desc())
            .limit(2)
        )
    )
    if not exams:
        return {"key": "score", "label": "学业", "text": "还没有考试记录。", "empty": True}

    reports = [build_report(session, exam, include_previous=False) for exam in exams]
    latest = reports[0]
    row = next((item for item in latest.rows if item.student_id == student.id), None)
    if row is None or not row.took_part:
        return {"key": "score", "label": "学业", "text": "最近一次考试没有成绩。", "empty": True}

    parts = [
        f"最近一次「{latest.exam_name}」总分 {row.total} 分，班级排名第 {row.rank} 名"
        + ("（并列）" if row.tied else "")
        + f"，得分率 {row.score_rate}%"
    ]
    if row.absent:
        parts.append(f"其中 {'、'.join(row.absent)} 缺考")
    if row.missing:
        parts.append(f"{'、'.join(row.missing)} 还没有成绩")

    if len(reports) > 1:
        previous = next((item for item in reports[1].rows if item.student_id == student.id), None)
        if previous is not None and previous.took_part:
            delta = round(row.total - previous.total, 1)
            if delta > 3:
                parts.append(f"比「{reports[1].exam_name}」提升 {delta} 分")
            elif delta < -3:
                parts.append(f"比「{reports[1].exam_name}」回落 {abs(delta)} 分")

    if row.values:
        best = max(row.values.items(), key=lambda item: item[1])
        worst = min(row.values.items(), key=lambda item: item[1])
        full_map = {item.subject: item.full_marks for item in latest.subjects}
        best_rate = round(best[1] / full_map.get(best[0], 1) * 100)
        worst_rate = round(worst[1] / full_map.get(worst[0], 1) * 100)
        parts.append(f"最强科是{best[0]}（{best[1]} 分，得分率 {best_rate}%）")
        if worst[0] != best[0]:
            parts.append(f"相对薄弱的是{worst[0]}（{worst[1]} 分，得分率 {worst_rate}%）")

    return {"key": "score", "label": "学业", "text": "；".join(parts) + "。", "empty": False}


def comment_draft(session: Session, student_id: int) -> dict[str, Any]:
    """拼一份评语初稿：结构化维度 + 可直接编辑的文本。"""
    student = session.get(Student, student_id)
    if student is None or student.deleted_at is not None:
        raise ApiError(NOT_FOUND, "这个学生不存在，可能已被删除", status=404, detail={"id": student_id})

    data = archive(session, student_id)
    dimensions: list[dict[str, Any]] = [_score_dimension(session, student)]

    # 出勤：只写缺席与迟到早退的次数（不写具体事由，那是隐私）
    attendance = data["attendance"]
    if attendance["byType"]:
        pieces = []
        if attendance["absenceDays"]:
            pieces.append(f"缺席 {attendance['absenceDays']} 天")
        for kind in ("迟到", "早退"):
            count = attendance["byType"].get(kind, 0)
            if count:
                pieces.append(f"{kind} {count} 次")
        rate = attendance["rate"]
        text = "、".join(pieces)
        if rate is not None:
            text += f"（本班登记过的日子里的出勤率 {rate}%）"
        dimensions.append({"key": "attendance", "label": "出勤", "text": text + "。", "empty": False})
    else:
        dimensions.append({"key": "attendance", "label": "出勤", "text": "没有缺勤记录。", "empty": True})

    # 作业
    late = data["homework"]["lateCount"]
    dimensions.append(
        {
            "key": "homework",
            "label": "作业",
            "text": f"累计欠交 {late} 次。" if late else "作业都能按时完成。",
            "empty": not late,
        }
    )

    # 纪律
    discipline = data["discipline"]
    if discipline["total"]:
        dimensions.append(
            {
                "key": "discipline",
                "label": "纪律",
                "text": f"有 {discipline['total']} 条违纪记录"
                + (f"，其中 {discipline['open']} 条还没结案。" if discipline["open"] else "，都已结案。"),
                "empty": False,
            }
        )
    else:
        dimensions.append({"key": "discipline", "label": "纪律", "text": "没有违纪记录。", "empty": True})

    # 谈话与家校沟通
    talk_total = data["talks"]["total"]
    visit_total = data["visits"]["total"]
    contact_total = data["contacts"]["total"]
    if talk_total or visit_total or contact_total:
        parts = []
        if talk_total:
            parts.append(f"个别谈话 {talk_total} 次")
        if visit_total:
            parts.append(f"家访 {visit_total} 次")
        if contact_total:
            parts.append(f"与家长沟通 {contact_total} 次")
        dimensions.append(
            {"key": "communication", "label": "沟通", "text": "、".join(parts) + "。", "empty": False}
        )

    # 资助
    if data["grants"]["recent"]:
        types = "、".join({row["type"] for row in data["grants"]["recent"]})
        dimensions.append(
            {"key": "grant", "label": "资助", "text": f"享受{types}。", "empty": False}
        )

    # 特殊体质：**不写进评语**，只给老师一句提醒
    health = session.scalars(
        select(HealthRecord).where(
            HealthRecord.deleted_at.is_(None), HealthRecord.student_id == student_id
        )
    ).first()
    if health is not None:
        dimensions.append(
            {
                "key": "health",
                "label": "提醒",
                "text": f"该生有特殊体质档案（{health.type}），评语里不必写。{TEACHER_ONLY_NOTE}",
                "empty": False,
                "teacherOnly": True,
            }
        )

    spoken = [item for item in dimensions if not item.get("teacherOnly") and not item["empty"]]
    draft = "".join(item["text"] for item in spoken) if spoken else "这位学生这一学期没有留下特别的数据记录。"

    return {
        "studentId": student_id,
        "studentName": student.name,
        "dimensions": dimensions,
        "draft": draft,
        # 最后一行固定这句：结论都来自数据，而评语要对人和家长负责
        "review": "请人工复核：以上都是按记录拼出来的事实，语气与措辞请你自己把关。",
        "emptyDimensions": [item["label"] for item in dimensions if item["empty"]],
    }
