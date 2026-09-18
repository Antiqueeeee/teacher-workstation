"""首页与看板的聚合口径。

**这里不重新实现任何算法** —— 首页上的每个数都从各模块自己的口径服务里取：
出勤率来自 `attendance_rate`、提交率来自 `homework`、待跟进来自 `contact` 的口径。
旧应用首页的问题正是「同一件事在首页和详情页各算一遍」：
「作业待收」读的是两个根本不存在的字段（`:7011`），于是那张卡片恒为 0，
而列表页的提交率是另一个算法。

跟进清单的权重与窗口曾经硬编码在计算函数里（`:7584`），这里集中在
`FOLLOWUP_RULES` 一处 —— 改一次权重不必翻三处代码。
（「让用户自己调」需要设置界面，本轮没做，记在 06 变更登记表里。）
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.attendance import Attendance
from app.models.contact import ContactLog
from app.models.homework import Homework
from app.models.media import Media
from app.models.student import Student
from app.models.todo import Todo
from app.services.attendance_rate import range_summary
from app.services.roster import count_class_students
from app.services.student_service import identity_conflicts

# 跟进清单的规则：紧急度权重 + 观察窗口。权重大的排前面。
FOLLOWUP_RULES = {
    "absent_uncontacted": {"weight": 95, "days": 7, "label": "缺席还没联系家长"},
    "discipline_open": {"weight": 80, "days": 30, "label": "违纪未结案"},
    "contact_follow_up": {"weight": 72, "days": 30, "label": "家长那边还要再联系"},
    "todo_due": {"weight": 40, "days": 0, "label": "待办到期"},
    "homework_pending": {"weight": 40, "days": 14, "label": "作业还没交齐"},
}


def _recent_days(days: int) -> date | None:
    """窗口起点（`days=0` 表示不限时间）。"""
    if not days:
        return None
    return date.today() - timedelta(days=days)


def _student_name(session: Session, student_id: int | None) -> str:
    if not student_id:
        return ""
    student = session.get(Student, student_id)
    return student.name if student else ""


def overview(session: Session, class_id: int) -> dict[str, Any]:
    """首页 KPI 与今日待办要的数。"""
    today = date.today()
    total = count_class_students(session, class_id)

    boarding = session.scalar(
        select(func.count())
        .select_from(Student)
        .where(
            Student.deleted_at.is_(None),
            Student.class_id == class_id,
            func.json_extract(Student.extra, "$.boarding") == "住校",
        )
    ) or 0

    today_attendance = range_summary(session, class_id, today, today)
    day = today_attendance.days[0]

    homework_rows = list(
        session.scalars(
            select(Homework).where(Homework.deleted_at.is_(None), Homework.class_id == class_id)
        )
    )
    rates = [row.rate for row in homework_rows if row.rate is not None]
    pending_homework = [row for row in homework_rows if row.unsubmitted_count > 0]

    open_todos = session.scalar(
        select(func.count())
        .select_from(Todo)
        .where(Todo.deleted_at.is_(None), Todo.class_id == class_id, Todo.done.is_(False))
    ) or 0

    follow_up_contacts = session.scalar(
        select(func.count())
        .select_from(ContactLog)
        .where(
            ContactLog.deleted_at.is_(None),
            ContactLog.class_id == class_id,
            ContactLog.needs_follow_up.is_(True),
        )
    ) or 0

    conflicts = identity_conflicts(session, class_id)

    attachments = session.scalar(
        select(func.count())
        .select_from(Media)
        .where(Media.deleted_at.is_(None), Media.class_id == class_id)
    ) or 0

    return {
        "date": today.isoformat(),
        "students": {
            "total": total,
            "boarding": boarding,
            "duplicateNames": len(conflicts["names"]),
        },
        "attendance": {
            "registered": day.registered,
            "rate": day.rate,
            "absent": day.absent,
            "late": day.late,
            "early": day.early,
            "absentStudents": list(day.absent_students),
        },
        "homework": {
            "count": len(homework_rows),
            "pending": len(pending_homework),
            "averageRate": round(sum(rates) / len(rates)) if rates else None,
        },
        "todos": {"open": open_todos},
        "contacts": {"followUp": follow_up_contacts},
        "attachments": attachments,
    }


def followups(session: Session, class_id: int, limit: int = 14) -> list[dict[str, Any]]:
    """跨模块的「需要我跟进」清单。

    每条都带**去哪一条记录**（`table` + `id`）与一句给人看的原因，界面据此直接跳转 ——
    旧应用这张清单点进去只到模块首页，老师还得自己找是哪一条。
    """
    today = date.today()
    items: list[dict[str, Any]] = []

    # 1. 缺席还没联系家长：跟进状态是「待联系」的考勤记录
    window = _recent_days(FOLLOWUP_RULES["absent_uncontacted"]["days"])
    absent_rows = session.scalars(
        select(Attendance).where(
            Attendance.class_id == class_id,
            Attendance.handled == "待联系",
            Attendance.date >= window if window else True,
        )
    )
    for row in absent_rows:
        items.append(
            {
                "kind": "absent_uncontacted",
                "weight": FOLLOWUP_RULES["absent_uncontacted"]["weight"],
                "date": row.date.isoformat(),
                "studentId": row.student_id,
                "studentName": row.student_name,
                "text": f"{row.student_name} {row.date.strftime('%m-%d')} {row.type}，还没联系家长",
                "table": "attendance",
                "id": row.id,
            }
        )

    # 2. 家长那边还要再联系
    window = _recent_days(FOLLOWUP_RULES["contact_follow_up"]["days"])
    contact_rows = session.scalars(
        select(ContactLog).where(
            ContactLog.deleted_at.is_(None),
            ContactLog.class_id == class_id,
            ContactLog.needs_follow_up.is_(True),
            ContactLog.date >= window if window else True,
        )
    )
    for row in contact_rows:
        items.append(
            {
                "kind": "contact_follow_up",
                "weight": FOLLOWUP_RULES["contact_follow_up"]["weight"],
                "date": row.date.isoformat(),
                "studentId": row.student_id,
                "studentName": row.student_name,
                "text": f"{row.student_name} 的家校联系还要跟进（{row.channel}·{row.result}）",
                "table": "contacts",
                "id": row.id,
            }
        )

    # 3. 作业还没交齐（最近两周内的）
    window = _recent_days(FOLLOWUP_RULES["homework_pending"]["days"])
    homework_rows = session.scalars(
        select(Homework).where(
            Homework.deleted_at.is_(None),
            Homework.class_id == class_id,
            Homework.date >= window if window else True,
        )
    )
    for row in homework_rows:
        if not row.unsubmitted_count:
            continue
        names = row.unsubmitted_names
        items.append(
            {
                "kind": "homework_pending",
                "weight": FOLLOWUP_RULES["homework_pending"]["weight"],
                "date": row.date.isoformat(),
                "studentName": "",
                "text": f"{row.date.strftime('%m-%d')} {row.subject} 有 {row.unsubmitted_count} 人没交（{names}）"
                if names
                else f"{row.date.strftime('%m-%d')} {row.subject} 还没交齐",
                "table": "homework",
                "id": row.id,
            }
        )

    # 4. 待办到期（到期日已过或没填截止日的未完成项）
    todo_rows = session.scalars(
        select(Todo).where(
            Todo.deleted_at.is_(None), Todo.class_id == class_id, Todo.done.is_(False)
        )
    )
    for row in todo_rows:
        if row.due_date and row.due_date > today:
            continue
        items.append(
            {
                "kind": "todo_due",
                "weight": FOLLOWUP_RULES["todo_due"]["weight"],
                "date": (row.due_date or row.created_at.date()).isoformat(),
                "studentName": "",
                "text": f"待办：{row.content}" + (f"（{row.due_date} 到期）" if row.due_date else ""),
                "table": "todos",
                "id": row.id,
            }
        )

    # 重的排前面；同权重按日期倒序（最近发生的先看）
    items.sort(key=lambda item: (-item["weight"], item["date"]), reverse=False)
    return items[: max(1, min(limit, 100))]
