"""班级费用的规则：状态推导、类别汇总、应缴快照与回填。

**唯一口径**：缴费状态（已缴/部分/未缴/免缴）由 `status_of` 一处算出来，
列表、导出、筛选、汇总都读它。旧应用的 `feeStatus()` 只活在前端 ——
导出文件里没有这一列，导入回来也认不出来，两边迟早对不上。

金额一律是**分**（整数），进出都走 `services/money.py`。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, NOT_FOUND, ApiError
from app.models.fee import FEE_STATUSES, LEDGER_KINDS, FeeCategory, FeeLedger, FeeRecord
from app.models.student import Student
from app.services.params import as_int
from app.services.roster import find_student


def status_of(should_pay_cents: int, paid_cents: int) -> str:
    """缴费状态（唯一实现）。

    - 应缴 0 → 免缴（旧应用把「应缴 0 且实缴 0」叫免缴，语义一致）
    - 实缴 ≥ 应缴 → 已缴
    - 实缴 > 0 → 部分
    - 否则 → 未缴
    """
    should = max(0, should_pay_cents or 0)
    paid = max(0, paid_cents or 0)
    if should == 0:
        return "免缴"
    if paid >= should:
        return "已缴"
    if paid > 0:
        return "部分"
    return "未缴"


def get_category(session: Session, category_id: int) -> FeeCategory:
    category = session.get(FeeCategory, category_id)
    if category is None or category.deleted_at is not None:
        raise ApiError(
            NOT_FOUND,
            "这个收费项目不存在，可能已被删除",
            status=404,
            detail={"id": category_id},
        )
    return category


def apply_category(values: dict[str, Any], session: Session, row: Any = None) -> None:
    """收费项目：名称必填、金额在字段层已转成分。"""
    name = str(values.get("name") or (getattr(row, "name", "") if row else "") or "").strip()
    if not name:
        raise ApiError(INVALID_VALUE, "「费用名称」是必填项", detail={"field": "name"})
    values["name"] = name


def apply_record(values: dict[str, Any], session: Session, row: Any = None) -> None:
    """缴费记录：解析学生、应缴留空时取类别标准（**存成快照**）。

    应缴是收钱那一刻的约定：后来把类别标准从 50 改成 60，不该把上学期已经收过的
    记录全部改写（旧应用就是快照，文档也要求保持这个语义）。
    """
    class_id = values.get("class_id") or (getattr(row, "class_id", None) if row else None)
    category_id = values.get("category_id") or (getattr(row, "category_id", None) if row else None)
    if not category_id:
        raise ApiError(INVALID_VALUE, "必须选一个收费项目", detail={"field": "category_id"})
    category = get_category(session, int(category_id))
    values["category_id"] = category.id
    values["class_id"] = category.class_id
    if category.class_id != class_id and class_id is not None:
        raise ApiError(INVALID_VALUE, "这条记录与收费项目不属于同一个班", detail={"field": "category_id"})

    name = str(
        values.get("student_name") or (getattr(row, "student_name", "") if row else "") or ""
    ).strip()
    if not name:
        raise ApiError(INVALID_VALUE, "必须填写学生姓名", detail={"field": "student_name"})
    student, problem, _kind = find_student(session, name=name, class_id=category.class_id)
    if problem is not None:
        raise ApiError(INVALID_VALUE, problem, detail={"field": "student_name"})
    values["student_id"] = student.id
    values["student_name"] = student.name

    if row is None and values.get("should_pay_cents") in (None, ""):
        values["should_pay_cents"] = category.amount_cents
    if values.get("date") in (None, ""):
        values["date"] = date.today()


def apply_ledger(values: dict[str, Any], session: Session, row: Any = None) -> None:
    """流水：方向必须是显式枚举（旧应用把「不是支出」一律当收入）。"""
    category_id = values.get("category_id") or (getattr(row, "category_id", None) if row else None)
    if not category_id:
        raise ApiError(INVALID_VALUE, "必须选一个收费项目", detail={"field": "category_id"})
    category = get_category(session, int(category_id))
    values["category_id"] = category.id
    values["class_id"] = category.class_id

    kind = str(values.get("kind") or (getattr(row, "kind", "") if row else "") or "").strip()
    if kind not in LEDGER_KINDS:
        raise ApiError(
            INVALID_VALUE,
            f"收支方向只能是{'、'.join(LEDGER_KINDS)}",
            detail={"field": "kind", "value": kind},
        )
    values["kind"] = kind
    if not str(values.get("item") or "").strip():
        raise ApiError(INVALID_VALUE, "「项目」是必填项", detail={"field": "item"})
    if values.get("date") in (None, ""):
        values["date"] = date.today()


def category_summary(session: Session, category: FeeCategory) -> dict[str, Any]:
    """一个收费项目的全部数字：应缴/已收/未收 + 各状态人数 + 流水收支与余额。

    后端算，界面只显示 —— 旧应用是前端在页面里现算的，导出与打印各算一遍。
    """
    records = list(
        session.scalars(
            select(FeeRecord).where(
                FeeRecord.deleted_at.is_(None), FeeRecord.category_id == category.id
            )
        )
    )
    expected = sum(row.should_pay_cents for row in records)
    collected = sum(row.paid_cents for row in records)
    counts = {status: 0 for status in FEE_STATUSES}
    for row in records:
        counts[row.status] += 1

    ledger = session.scalars(
        select(FeeLedger)
        .where(FeeLedger.deleted_at.is_(None), FeeLedger.category_id == category.id)
        # 同日流水按**录入顺序**排（旧应用只按日期字符串排，同一天顺序随机）
        .order_by(FeeLedger.date.asc(), FeeLedger.id.asc())
    ).all()
    income = sum(row.amount_cents for row in ledger if row.kind == "收入")
    expense = sum(row.amount_cents for row in ledger if row.kind == "支出")

    return {
        "categoryId": category.id,
        "name": category.name,
        "amountCents": category.amount_cents,
        "amountYuan": category.amount_yuan,
        "note": category.note,
        "studentCount": len(records),
        "expectedCents": expected,
        "collectedCents": collected,
        "owedCents": max(0, expected - collected),
        "counts": counts,
        "ledger": {
            "incomeCents": income,
            "expenseCents": expense,
            "balanceCents": income - expense,
        },
    }


def overview(session: Session, class_id: int) -> dict[str, Any]:
    """整个班的费用概览（首页卡片与费用页看板用）。"""
    categories = list(
        session.scalars(
            select(FeeCategory)
            .where(FeeCategory.deleted_at.is_(None), FeeCategory.class_id == class_id)
            .order_by(FeeCategory.id)
        )
    )
    items = [category_summary(session, category) for category in categories]
    return {
        "classId": class_id,
        "categories": items,
        "totals": {
            "expectedCents": sum(item["expectedCents"] for item in items),
            "collectedCents": sum(item["collectedCents"] for item in items),
            "owedCents": sum(item["owedCents"] for item in items),
            "balanceCents": sum(item["ledger"]["balanceCents"] for item in items),
        },
    }


def update_category_amount(
    session: Session, category_id: int, amount_cents: int, *, backfill: bool = False
) -> dict[str, Any]:
    """改应缴标准。默认**不回填**历史记录（应缴是收钱那一刻的约定）。

    要回填得显式说明（`backfill=true`），并且只回填**还没缴过钱**的记录 ——
    已经缴过的记录改了会变成「已缴」变「部分」这类莫名其妙的结论。
    """
    category = get_category(session, category_id)
    amount = as_int(amount_cents, "金额（分）")
    if amount < 0:
        raise ApiError(INVALID_VALUE, "金额不能是负数", detail={"field": "amount_cents"})
    category.amount_cents = amount

    backfilled = 0
    if backfill:
        records = session.scalars(
            select(FeeRecord).where(
                FeeRecord.deleted_at.is_(None),
                FeeRecord.category_id == category.id,
                FeeRecord.paid_cents == 0,  # 只有一分钱没收过的才回填
            )
        )
        for record in records:
            record.should_pay_cents = amount
            backfilled += 1
    session.flush()
    return {"categoryId": category.id, "amountCents": amount, "backfilled": backfilled}


def student_owing(session: Session, category_id: int) -> list[dict[str, Any]]:
    """还没缴齐的学生（催缴用）—— 按欠额降序。"""
    records = session.scalars(
        select(FeeRecord).where(
            FeeRecord.deleted_at.is_(None), FeeRecord.category_id == category_id
        )
    )
    owing = [
        {
            "recordId": row.id,
            "studentId": row.student_id,
            "studentName": row.student_name,
            "shouldPayCents": row.should_pay_cents,
            "paidCents": row.paid_cents,
            "owedCents": row.owed_cents,
            "status": row.status,
        }
        for row in records
        if row.owed_cents > 0
    ]
    return sorted(owing, key=lambda item: (-item["owedCents"], item["studentName"]))


def class_students_missing_records(session: Session, category: FeeCategory) -> list[str]:
    """这个收费项目里一条记录都没有的在册学生 —— 漏收要先发现。"""
    recorded = {
        row.student_id
        for row in session.scalars(
            select(FeeRecord).where(
                FeeRecord.deleted_at.is_(None), FeeRecord.category_id == category.id
            )
        )
    }
    students = session.scalars(
        select(Student).where(
            Student.deleted_at.is_(None), Student.class_id == category.class_id
        )
    )
    return [student.name for student in students if student.id not in recorded]


def create_records(
    session: Session, category: FeeCategory, names: list[str] | None = None
) -> dict[str, Any]:
    """给一批学生各建一条应缴记录（应缴按项目当前标准，存成快照）。

    默认给**还没建记录的**学生建 —— 收班费时的常规动作是「全班一次建齐，
    之后逐个登记实缴」。也可以指定姓名；认不出的整批不建（与别处的名单解析同一条规矩）。
    """
    if names:
        targets: list[Student] = []
        problems: list[str] = []
        for name in names:
            student, problem, _kind = find_student(
                session, name=name, class_id=category.class_id, label="学生"
            )
            if problem is not None:
                problems.append(problem)
            else:
                targets.append(student)
        if problems:
            raise ApiError(
                INVALID_VALUE,
                "名单里有认不出的学生：" + "；".join(problems),
                detail={"field": "names"},
            )
    else:
        missing = set(class_students_missing_records(session, category))
        targets = [
            student
            for student in session.scalars(
                select(Student).where(
                    Student.deleted_at.is_(None), Student.class_id == category.class_id
                )
            )
            if student.name in missing
        ]

    for student in targets:
        session.add(
            FeeRecord(
                class_id=category.class_id,
                category_id=category.id,
                student_id=student.id,
                student_name=student.name,
                # 应缴是**快照**：之后改类别标准不该改写已经建好的记录
                should_pay_cents=category.amount_cents,
                paid_cents=0,
            )
        )
    session.flush()
    return {
        "categoryId": category.id,
        "created": len(targets),
        "studentNames": [student.name for student in targets],
    }


def totals_for_status(session: Session, class_id: int) -> dict[str, int]:
    """全班各状态的记录数（KPI 用）。"""
    counts = {status: 0 for status in FEE_STATUSES}
    rows = session.scalars(
        select(FeeRecord).where(FeeRecord.deleted_at.is_(None), FeeRecord.class_id == class_id)
    )
    for row in rows:
        counts[row.status] += 1
    return counts
