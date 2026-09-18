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


def substitute_brief(session: Session, class_id: int, day: date) -> dict[str, Any]:
    """代课/交接简报：某一天的班级情况，给临时来代的老师看。

    **只汇总已有模块的数据**，不重新算：考勤来自 `attendance_rate`、座位来自 `seat_service`。
    特殊体质排在最前面 —— 那是安全信息（发作怎么处理、打给谁），代课老师第一时间要知道。

    还没做的一段是**今日课表**：那要等「课程表」模块落地（`course` + `schedule_slot`）。
    这里如实说明缺了它，而不是留一块空白让人猜。
    """
    from app.models.classroom import Cadre, DutyGroup
    from app.models.discipline import Discipline
    from app.models.rule import Rule
    from app.models.welfare import HealthRecord
    from app.services.attendance_rate import day_summary
    from app.services.seat_service import board as seat_board

    day_attendance = day_summary(session, class_id, day)

    health = list(
        session.scalars(
            select(HealthRecord)
            .where(
                HealthRecord.deleted_at.is_(None),
                HealthRecord.class_id == class_id,
                HealthRecord.level == "需重点关注",
            )
            .order_by(HealthRecord.id)
        )
    )

    cadres = list(
        session.scalars(
            select(Cadre)
            .where(Cadre.deleted_at.is_(None), Cadre.class_id == class_id)
            .order_by(Cadre.id)
        )
    )

    rules = list(
        session.scalars(
            select(Rule)
            .where(Rule.deleted_at.is_(None), Rule.class_id == class_id)
            .order_by(Rule.id)
            .limit(6)
        )
    )

    # 还没结案且程度不轻的违纪 —— 代课老师需要知道「这几个要多留意」
    open_disciplines = list(
        session.scalars(
            select(Discipline)
            .where(
                Discipline.deleted_at.is_(None),
                Discipline.class_id == class_id,
                Discipline.status != "已结案",
            )
            .order_by(Discipline.date.desc())
            .limit(6)
        )
    )

    weekday_no = day.isoweekday()
    duty = list(
        session.scalars(
            select(DutyGroup)
            .where(
                DutyGroup.deleted_at.is_(None),
                DutyGroup.class_id == class_id,
                DutyGroup.weekday_no == weekday_no,
            )
            .order_by(DutyGroup.id)
        )
    )

    seats = seat_board(session, class_id)
    from app.services.schedule_service import today_slots

    slots = today_slots(session, class_id, weekday_no)

    return {
        "date": day.isoformat(),
        "weekday": f"星期{'一二三四五六日'[weekday_no - 1]}",
        "attendance": day_attendance.to_dict(),
        "health": [
            {
                "studentName": row.student_name,
                "type": row.type,
                "detail": row.detail,
                "emergency": row.emergency,
                "limit": row.limit_note,
                "contact": row.contact,
                "phone": row.phone,
            }
            for row in health
        ],
        "cadres": [
            {"post": row.post, "studentName": row.student_name, "phone": row.phone} for row in cadres
        ],
        "rules": [
            {"category": row.category, "title": row.title, "content": row.content} for row in rules
        ],
        "discipline": [
            {
                "studentName": row.student_name,
                "date": row.date.isoformat(),
                "type": row.type,
                "level": row.level,
                "status": row.status,
            }
            for row in open_disciplines
        ],
        "duty": [
            {"area": row.area, "members": row.members_text, "leader": row.leader_name} for row in duty
        ],
        "seats": {
            "rows": seats["rows"],
            "cols": seats["cols"],
            "grid": [
                [
                    {"row": cell["row"], "col": cell["col"], "studentName": cell["studentName"]}
                    for cell in line
                ]
                for line in seats["grid"]
            ],
        },
        "todaySlots": slots,
        # 缺的段如实写出来，而不是留一块空白让人猜（课表已落地，这一项现在是空的）
        "missingSections": [],
    }


def dashboard(session: Session, class_id: int, *, days: int = 14, months: int = 6) -> dict[str, Any]:
    """数据看板要的数：出勤趋势、违纪分布与 Top、沟通/大事记月度走势。

    **口径一律从各模块自己的服务取**：出勤率来自 `attendance_rate`（未登记的天是空，
    不是 100%）、违纪与沟通按 **student_id 去重**（旧应用按姓名，重名会合并成一个人 —— `01` §7.3）。
    """
    from app.models.communication import ClassEvent, Talk
    from app.models.contact import ContactLog
    from app.models.discipline import Discipline
    from app.services.attendance_rate import range_summary

    today = date.today()
    start = today - timedelta(days=max(1, days) - 1)
    summary = range_summary(session, class_id, start, today)

    discipline_rows = list(
        session.scalars(
            select(Discipline).where(
                Discipline.deleted_at.is_(None), Discipline.class_id == class_id
            )
        )
    )
    by_level: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_student: dict[int, dict[str, Any]] = {}
    for row in discipline_rows:
        by_level[row.level] = by_level.get(row.level, 0) + 1
        by_type[row.type] = by_type.get(row.type, 0) + 1
        if row.student_id:
            item = by_student.setdefault(
                row.student_id, {"studentId": row.student_id, "studentName": row.student_name, "count": 0}
            )
            item["count"] += 1

    # 缺席 Top：按 **student_id** 去重（日小结里给的是姓名，重名会合并成一个人）
    absent_top: dict[int, dict[str, Any]] = {}
    absent_records = session.scalars(
        select(Attendance).where(
            Attendance.class_id == class_id,
            Attendance.date >= start,
            Attendance.date <= today,
            Attendance.type.in_(("病假", "事假", "旷课")),
        )
    )
    for row in absent_records:
        item = absent_top.setdefault(
            row.student_id,
            {"studentId": row.student_id, "studentName": row.student_name, "count": 0},
        )
        item["count"] += 1

    # 月度走势：联系 / 谈话 / 大事记各按月计数（近 months 个月）
    month_keys: list[str] = []
    cursor = date(today.year, today.month, 1)
    for _ in range(max(1, months)):
        month_keys.append(f"{cursor.year:04d}-{cursor.month:02d}")
        cursor = date(cursor.year - 1, 12, 1) if cursor.month == 1 else date(cursor.year, cursor.month - 1, 1)
    month_keys.reverse()

    def month_counts(model, column, extra=None) -> list[int]:
        query = select(model).where(model.deleted_at.is_(None), model.class_id == class_id)
        if extra is not None:
            query = query.where(extra)
        counts = {key: 0 for key in month_keys}
        for row in session.scalars(query):
            value = getattr(row, column)
            key = value.strftime("%Y-%m") if hasattr(value, "strftime") else str(value)[:7]
            if key in counts:
                counts[key] += 1
        return [counts[key] for key in month_keys]

    return {
        "days": max(1, days),
        "attendanceTrend": [day.to_dict() for day in summary.days],
        "discipline": {
            "total": len(discipline_rows),
            "open": sum(1 for row in discipline_rows if row.open_case),
            "byLevel": by_level,
            "byType": by_type,
            "top": sorted(by_student.values(), key=lambda item: -item["count"])[:5],
        },
        "absentTop": sorted(absent_top.values(), key=lambda item: -item["count"])[:5],
        "months": month_keys,
        "monthly": {
            "contacts": month_counts(ContactLog, "date"),
            "talks": month_counts(Talk, "date"),
            "events": month_counts(ClassEvent, "date"),
        },
    }


def timeline(session: Session, class_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
    """学期时间轴：把几类留档按日期合成一条时间线。

    旧应用的时间轴是前端把 6 张表拉下来合并的（`timelineAll`），表一多就得改前端；
    这里在后端合，加一类留档只改这一处。
    """
    from app.models.communication import ClassActivity, ClassEvent, Conflict, Meeting, Talk, Visit
    from app.models.contact import ContactLog
    from app.models.discipline import Discipline

    sources = (
        ("contacts", "家长联系", ContactLog, "content", "id"),
        ("talks", "谈话", Talk, "reason", "id"),
        ("visits", "家访", Visit, "consensus", "id"),
        ("meetings", "主题班会", Meeting, "theme", "id"),
        ("class_activities", "班级活动", ClassActivity, "title", "id"),
        ("class_events", "大事记", ClassEvent, "title", "id"),
        ("conflicts", "矛盾调解", Conflict, "reason", "id"),
        ("disciplines", "违纪", Discipline, "detail", "id"),
    )

    items: list[dict[str, Any]] = []
    for key, label, model, text_column, _ in sources:
        for row in session.scalars(
            select(model).where(model.deleted_at.is_(None), model.class_id == class_id)
        ):
            text = str(getattr(row, text_column) or "").strip()
            items.append(
                {
                    "table": key,
                    "label": label,
                    "id": row.id,
                    "date": row.date.isoformat(),
                    "studentName": getattr(row, "student_name", ""),
                    "text": text[:60],
                }
            )
    # 日期倒序；同一天按表名分组，保证同一份数据每次顺序一致
    items.sort(key=lambda item: (item["date"], item["table"], item["id"]), reverse=True)
    return items[: max(1, min(limit, 200))]
