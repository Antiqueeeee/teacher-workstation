"""学生档案：把「字段定义」变成「表声明」。

学生档案的字段是**运行时可变的**（老师能自己加字段），所以它的 `TableSpec` 不是写死的常量，
而是每次请求按库里的字段定义现算 —— 这就是「动态表」的含义（见 `schemas/registry.py`
的 `DYNAMIC_TABLES`）。

好处是它照样走**通用链路**：列表、表单、导入、导出、统计、软删除全部复用同一套实现，
不必为学生档案写一套特例 —— 特例正是「同一规则多处实现」的温床。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, NOT_FOUND, ApiError
from app.db.engine import SessionLocal
from app.models.student import Student, StudentFieldDef
from app.schemas.registry import DYNAMIC_TABLES, ColumnSpec, FieldSpec, TableSpec
from app.services.student_fields import build_defs_from_template

# 这两个是**真实列**（身份字段：列表、搜索、导入判重、点名都靠它），其余都在 extra JSON 里
COLUMN_KEYS = ("name", "sno")

DEFAULT_SORT = ("sno", 1)  # 按学号排，与旧应用一致


def load_defs(session: Session) -> list[StudentFieldDef]:
    return list(
        session.scalars(
            select(StudentFieldDef).order_by(StudentFieldDef.sort_order, StudentFieldDef.id)
        )
    )


def build_spec_from_defs(defs: list[StudentFieldDef]) -> TableSpec:
    columns = tuple(
        ColumnSpec(definition.key, definition.label) for definition in defs if definition.in_list
    )
    fields = tuple(
        FieldSpec(
            definition.key,
            definition.label,
            type=definition.type,
            # 姓名必须填（模型也是 NOT NULL）；其余按定义。学号允许为空（转学生可能还没有）
            required=definition.required or definition.key == "name",
            options=tuple(definition.options or ()),
            full=definition.type == "textarea",
            hint=definition.hint,
            aliases=tuple(definition.aliases or ()),
        )
        for definition in defs
        if definition.in_form
    )
    searchable = tuple(
        definition.key
        for definition in defs
        if definition.searchable and definition.key not in COLUMN_KEYS
    )
    return TableSpec(
        key="students",
        model=Student,
        title="学生档案",
        entity="学生",
        columns=columns,
        fields=fields,
        # 姓名与学号永远可搜 —— 老师找学生就是按这两个
        search_keys=COLUMN_KEYS + searchable,
        filter_keys=tuple(definition.key for definition in defs if definition.filterable),
        default_sort=DEFAULT_SORT,
        class_scoped=True,
        dedupe_keys=("sno",),  # 同学号即同一名学生，重复导入不翻倍
        json_column="extra",
        json_fields=frozenset(
            definition.key for definition in defs if definition.key not in COLUMN_KEYS
        ),
        before_save=check_unique_sno,
    )


def students_spec() -> TableSpec:
    """动态表声明：每次调用按当前字段定义现算（老师加完字段立即生效，不用重启）。

    迁移还没跑（表还不存在）时退回默认模板 —— 表声明因此**始终可描述**，
    不会因为「谁先谁后」在启动早期或测试收集阶段炸掉。
    """
    try:
        with SessionLocal() as session:
            defs = load_defs(session)
    except OperationalError:
        defs = build_defs_from_template()
    return build_spec_from_defs(defs)


def check_unique_sno(values: dict[str, Any], session: Session, row: Any = None) -> None:
    """学号在班内唯一。

    数据库有部分唯一索引兜底，但撞上时只会抛 IntegrityError（500），
    对老师来说等于「出错了」。这里提前查一次，给出能看懂、能照做的提示。
    """
    sno = str(values.get("sno") or "").strip()
    if not sno:
        return

    class_id = values.get("classId") or getattr(row, "class_id", None)
    query = select(Student).where(Student.deleted_at.is_(None), Student.sno == sno)
    if class_id:
        query = query.where(Student.class_id == class_id)
    if row is not None:
        query = query.where(Student.id != row.id)

    if session.scalar(query) is not None:
        raise ApiError(
            INVALID_VALUE,
            f"学号「{sno}」在这个班里已经有了，请检查是否重复导入或学号填错",
            detail={"field": "sno", "value": sno},
        )


def identity_conflicts(session: Session, class_id: int | None) -> dict[str, list[dict]]:
    """本班里「靠姓名对不上人」的分组：同名。

    判据与写入口的解析规则一致（`services/roster.resolve_names`、
    `services/guardian_service.link_student`）—— 报告说没冲突、录数据却被拦下来，
    那种前后不一致比不做报告还糟。

    **学号不在这里报告，因为它不可能冲突**：`students` 上有一个部分唯一索引
    `uq_students_class_sno(class_id, sno) WHERE sno <> ''`（空学号不算 ——
    还没编学号是常态），写入口还会把冲突转成一句中文说明。
    所以「学号冲突」是靠结构保证的，不需要报告让人去裁决。
    """
    query = select(Student).where(Student.deleted_at.is_(None))
    if class_id:
        query = query.where(Student.class_id == class_id)
    students = list(session.scalars(query.order_by(Student.name, Student.sno)))

    by_name: dict[str, list[Student]] = {}
    for student in students:
        by_name.setdefault(student.name.strip(), []).append(student)

    return {
        "names": [
            {
                "name": name,
                "count": len(items),
                "students": [
                    {"id": item.id, "name": item.name, "sno": item.sno} for item in items
                ],
            }
            for name, items in by_name.items()
            if len(items) > 1 and name
        ]
    }


def register_dynamic_tables() -> None:
    """把动态表注册进注册表。

    应用启动、工具脚本、测试都调用它 —— 注册只此一处。
    漏掉一处的表现是「表不见了」（`get_spec("students")` 返回 None），很难往这里想。
    """
    DYNAMIC_TABLES["students"] = students_spec
def archive(session: Session, student_id: int, *, recent: int = 5) -> dict[str, Any]:
    """一生一档：一个学生在这套系统里的全部痕迹。

    **每个数字都从它所属模块的口径服务取**（出勤率、成绩名次、作业欠交），
    所以档案上的数与各页面对得上 —— 阶段 2 的验收就是「学生档案欠交次数、
    首页待收、科目平均率三处数值一致」，那三处读的正是这里的同一份关系与口径。

    各段只取最近 `recent` 条：档案是拿来「一眼看完」的，明细在各模块自己的页面里。
    """
    from app.models.attendance import Attendance
    from app.models.communication import Conflict, Talk, Visit
    from app.models.contact import ContactLog
    from app.models.discipline import Discipline
    from app.models.exam import Exam
    from app.models.homework import Homework, HomeworkUnsubmitted
    from app.models.media import Media
    from app.models.welfare import Grant, HealthRecord
    from app.services.attendance_rate import (
        absence_day_count,
        compute_rate,
        registered_day_count,
    )
    from app.services.score_stats import build_report

    student = session.get(Student, student_id)
    if student is None or student.deleted_at is not None:
        raise ApiError(NOT_FOUND, "这个学生不存在，可能已被删除", status=404, detail={"id": student_id})

    def count(model, *conditions) -> int:
        return session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0

    def latest(model, *conditions, order, limit: int | None = None):
        query = select(model).where(*conditions).order_by(order)
        return list(session.scalars(query.limit(limit if limit is not None else recent)))

    # ---- 出勤：按类型计数 + 出勤率 ----
    # 出勤率的分母是**这个班登记过的天数**（与出勤页同一口径、同一个 compute_rate）：
    # 没登记的日子不算满勤，缺席也只在登记过的日子上才有意义。
    # 两个数都用 SQL 现算，**不取最近 N 条再数** —— 数总量时被截断是静默少算。
    attendance_rows = latest(
        Attendance, Attendance.student_id == student_id, order=Attendance.date.desc()
    )
    by_type = {
        row_type: count
        for row_type, count in session.execute(
            select(Attendance.type, func.count())
            .where(Attendance.student_id == student_id)
            .group_by(Attendance.type)
        )
    }
    absence_days = absence_day_count(session, student.class_id, student_id)
    registered_days = registered_day_count(session, student.class_id)
    attendance_rate = compute_rate(registered_days, absence_days)

    # ---- 作业：欠交次数（与首页「作业待收」、作业页读的是同一张子表）----
    # 已软删的作业不算欠交（与作业页一致）；总数也现算，不看窗口
    late_count = session.scalar(
        select(func.count())
        .select_from(HomeworkUnsubmitted)
        .join(Homework, Homework.id == HomeworkUnsubmitted.homework_id)
        .where(
            HomeworkUnsubmitted.student_id == student_id,
            Homework.deleted_at.is_(None),
            Homework.class_id == student.class_id,
        )
    ) or 0
    late_links = latest(
        HomeworkUnsubmitted,
        HomeworkUnsubmitted.student_id == student_id,
        order=HomeworkUnsubmitted.id.desc(),
        limit=200,
    )
    late_recent: list[dict[str, Any]] = []
    for link in late_links:
        homework = session.get(Homework, link.homework_id)
        if homework is None or homework.deleted_at is not None:
            continue
        late_recent.append(
            {
                "id": homework.id,
                "date": homework.date.isoformat(),
                "subject": homework.subject,
                "content": homework.content,
            }
        )
        if len(late_recent) >= recent:
            break

    # ---- 成绩：最近几场的总分与名次（名次由 score_stats 现算，不落库）----
    score_rows: list[dict[str, Any]] = []
    for exam in latest(
        Exam,
        Exam.deleted_at.is_(None),
        Exam.class_id == student.class_id,
        order=Exam.date.desc(),
        limit=recent,
    ):
        report = build_report(session, exam, include_previous=False)
        match = [item for item in report.rows if item.student_id == student_id]
        if not match:
            continue
        row = match[0]
        score_rows.append(
            {
                "examId": exam.id,
                "examName": exam.name,
                "examDate": exam.date.isoformat(),
                "total": row.total,
                "rank": row.rank,
                "tied": row.tied,
                "scoreRate": row.score_rate,
                "absent": row.absent,
                "missing": row.missing,
                "studentCount": len([item for item in report.rows if item.took_part]),
            }
        )

    # ---- 矛盾调解：这个学生牵涉其中的（按子表的 student_id 匹配，不用姓名）----
    involved = [
        row
        for row in session.scalars(
            select(Conflict)
            .where(Conflict.deleted_at.is_(None), Conflict.class_id == student.class_id)
            .order_by(Conflict.date.desc())
        )
        if any(party.student_id == student_id for party in row.parties)
    ]

    # 助学金：总额现算（不看窗口 —— 截断 200 条会让「一共资助了多少」少算），
    # 已软删的不算；列表仍只取最近几条
    grant_total_cents = int(
        session.scalar(
            select(func.coalesce(func.sum(Grant.amount_cents), 0)).where(
                Grant.student_id == student_id, Grant.deleted_at.is_(None)
            )
        )
        or 0
    )
    grants_all = latest(
        Grant,
        Grant.student_id == student_id,
        Grant.deleted_at.is_(None),
        order=Grant.apply_date.desc(),
        limit=200,
    )
    health = session.scalars(
        select(HealthRecord).where(
            HealthRecord.deleted_at.is_(None), HealthRecord.student_id == student_id
        )
    ).first()

    return {
        "student": {
            "id": student.id,
            "name": student.name,
            "sno": student.sno,
            "extra": student.extra or {},
        },
        "attendance": {
            "byType": by_type,
            "absenceDays": absence_days,
            "registeredDays": registered_days,
            "rate": attendance_rate,
            "recent": [
                {
                    "id": row.id,
                    "date": row.date.isoformat(),
                    "type": row.type,
                    "period": row.period,
                    "reason": row.reason,
                    "handled": row.handled,
                }
                for row in attendance_rows[:recent]
            ],
        },
        "homework": {"lateCount": late_count, "recent": late_recent},
        "scores": score_rows,
        "discipline": {
            "total": count(
                Discipline, Discipline.student_id == student_id, Discipline.deleted_at.is_(None)
            ),
            "open": count(
                Discipline,
                Discipline.student_id == student_id,
                Discipline.status != "已结案",
                Discipline.deleted_at.is_(None),
            ),
            "recent": [
                {
                    "id": row.id,
                    "date": row.date.isoformat(),
                    "type": row.type,
                    "level": row.level,
                    "status": row.status,
                    "detail": row.detail,
                }
                for row in latest(
                    Discipline,
                    Discipline.student_id == student_id,
                    Discipline.deleted_at.is_(None),
                    order=Discipline.date.desc(),
                )
            ],
        },
        "talks": {
            "total": count(Talk, Talk.student_id == student_id, Talk.deleted_at.is_(None)),
            "recent": [
                {
                    "id": row.id,
                    "date": row.date.isoformat(),
                    "type": row.type,
                    "reason": row.reason,
                }
                for row in latest(
                    Talk,
                    Talk.student_id == student_id,
                    Talk.deleted_at.is_(None),
                    order=Talk.date.desc(),
                )
            ],
        },
        "visits": {
            "total": count(Visit, Visit.student_id == student_id, Visit.deleted_at.is_(None)),
            "recent": [
                {
                    "id": row.id,
                    "date": row.date.isoformat(),
                    "teacher": row.teacher,
                    "consensus": row.consensus,
                }
                for row in latest(
                    Visit,
                    Visit.student_id == student_id,
                    Visit.deleted_at.is_(None),
                    order=Visit.date.desc(),
                )
            ],
        },
        "contacts": {
            "total": count(
                ContactLog, ContactLog.student_id == student_id, ContactLog.deleted_at.is_(None)
            ),
            "followUp": count(
                ContactLog,
                ContactLog.student_id == student_id,
                ContactLog.needs_follow_up.is_(True),
                ContactLog.deleted_at.is_(None),
            ),
            "recent": [
                {
                    "id": row.id,
                    "date": row.date.isoformat(),
                    "channel": row.channel,
                    "result": row.result,
                    "content": row.content,
                }
                for row in latest(
                    ContactLog,
                    ContactLog.student_id == student_id,
                    ContactLog.deleted_at.is_(None),
                    order=ContactLog.date.desc(),
                )
            ],
        },
        "conflicts": {
            "total": len(involved),
            "recent": [
                {
                    "id": row.id,
                    "date": row.date.isoformat(),
                    "reason": row.reason,
                    "level": row.level,
                    "status": row.status,
                }
                for row in involved[:recent]
            ],
        },
        "grants": {
            "totalCents": grant_total_cents,
            "recent": [
                {
                    "id": row.id,
                    "date": row.apply_date.isoformat() if row.apply_date else "",
                    "type": row.type,
                    "amount": row.amount_display,
                    "status": row.status,
                }
                for row in grants_all[:recent]
            ],
        },
        "health": (
            {
                "id": health.id,
                "type": health.type,
                "level": health.level,
                "detail": health.detail,
                "emergency": health.emergency,
                "contact": health.contact,
                "phone": health.phone,
                "limit": health.limit_note,
            }
            if health is not None
            else None
        ),
        "attachments": count(Media, Media.deleted_at.is_(None), Media.student_id == student_id),
    }
