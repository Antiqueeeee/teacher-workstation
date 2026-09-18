"""班级费用的测试。

要害是**金额与状态**：金额以分存整数（浮点算钱会出现小数尾数）、
状态由一处推导（旧应用只在前端算，导出文件里没有这一列）、
应缴是快照（改类别标准不该改写历史）、收支是显式枚举（旧应用「不是支出就当收入」）。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.models.class_ import Class
from app.models.student import Student


def _class_id(session) -> int:
    return session.scalar(select(Class.id).where(Class.deleted_at.is_(None)).limit(1))


def _student(session, name: str, sno: str) -> Student:
    student = Student(class_id=_class_id(session), name=name, sno=sno, extra={})
    session.add(student)
    session.commit()
    return student


def _category(client, class_id: int, name: str = "班费", amount: str = "50") -> dict:
    response = client.post(
        "/api/v1/fee_categories",
        json={"name": name, "amount_cents": amount},
        params={"classId": class_id},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _record(client, class_id: int, category_id: int, name: str, **overrides) -> dict:
    payload = {"category_id": category_id, "student_name": name}
    payload.update(overrides)
    response = client.post(
        "/api/v1/fee_records", json=payload, params={"classId": class_id}
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_amount_is_stored_in_cents_and_status_is_derived(client, db_session):
    class_id = _class_id(db_session)
    _student(db_session, "费用学生甲", "F9001")
    category = _category(client, class_id, amount="49.90")
    assert category["amount_cents"] == 4990
    assert category["amount_yuan"] == "49.90"

    # 应缴留空 → 取类别标准（快照）
    unpaid = _record(client, class_id, category["id"], "费用学生甲")
    assert unpaid["should_pay_cents"] == 4990
    assert unpaid["status"] == "未缴" and unpaid["owed_cents"] == 4990

    # 缴一半 → 部分
    partial = client.patch(
        f"/api/v1/fee_records/{unpaid['id']}", json={"paid_cents": "20"}
    ).json()["data"]
    assert partial["status"] == "部分" and partial["owed_cents"] == 2990

    # 缴齐 → 已缴；再多缴也还是已缴，不会出现负欠额
    paid = client.patch(
        f"/api/v1/fee_records/{unpaid['id']}", json={"paid_cents": "60"}
    ).json()["data"]
    assert paid["status"] == "已缴" and paid["owed_cents"] == 0


def test_zero_amount_means_free(client, db_session):
    class_id = _class_id(db_session)
    _student(db_session, "费用学生乙", "F9002")
    category = _category(client, class_id, name="免收项目", amount="0")
    record = _record(client, class_id, category["id"], "费用学生乙")
    assert record["status"] == "免缴"


def test_should_pay_is_a_snapshot(client, db_session):
    """改类别标准**默认不改写**历史记录 —— 应缴是收钱那一刻的约定。"""
    class_id = _class_id(db_session)
    _student(db_session, "费用快照甲", "F9003")
    category = _category(client, class_id, amount="50")
    record = _record(client, class_id, category["id"], "费用快照甲")
    assert record["should_pay_cents"] == 5000

    changed = client.put(
        f"/api/v1/fees/categories/{category['id']}/amount",
        json={"amountCents": 6000},
    ).json()["data"]
    assert changed["backfilled"] == 0

    again = client.get(f"/api/v1/fee_records/{record['id']}").json()["data"]
    assert again["should_pay_cents"] == 5000  # 历史记录没被改写
    assert again["status"] == "未缴"

    # 显式要求回填：只回填一分钱没缴过的
    client.patch(f"/api/v1/fee_records/{record['id']}", json={"paid_cents": "10"})
    backfilled = client.put(
        f"/api/v1/fees/categories/{category['id']}/amount",
        json={"amountCents": 7000, "backfill": True},
    ).json()["data"]
    assert backfilled["backfilled"] == 0  # 缴过钱的不动
    assert client.get(f"/api/v1/fee_records/{record['id']}").json()["data"]["should_pay_cents"] == 5000


def test_category_overview_and_owing_list(client, db_session):
    """汇总在服务端算：应收/已收/未收 + 各状态人数 + 流水余额。"""
    class_id = _class_id(db_session)
    a = _student(db_session, "费用汇总甲", "F9004")
    b = _student(db_session, "费用汇总乙", "F9005")
    c = _student(db_session, "费用汇总丙", "F9006")
    category = _category(client, class_id, amount="50")
    _record(client, class_id, category["id"], a.name)
    _record(client, class_id, category["id"], b.name, paid_cents="50")
    _record(client, class_id, category["id"], c.name, paid_cents="20")

    # 一笔收入一笔支出
    for kind, item, amount in (("收入", "班费收缴", "100"), ("支出", "买扫除工具", "30")):
        assert (
            client.post(
                "/api/v1/fee_ledger",
                json={"category_id": category["id"], "kind": kind, "item": item, "amount_cents": amount},
                params={"classId": class_id},
            ).status_code
            == 201
        )

    overview = client.get("/api/v1/fees/overview", params={"classId": class_id}).json()["data"]
    item = overview["categories"][0]
    assert item["expectedCents"] == 15000  # 3 × 50
    assert item["collectedCents"] == 7000  # 0 + 50 + 20
    assert item["owedCents"] == 8000
    assert item["counts"] == {"已缴": 1, "部分": 1, "未缴": 1, "免缴": 0}
    assert item["ledger"] == {"incomeCents": 10000, "expenseCents": 3000, "balanceCents": 7000}
    assert overview["totals"]["owedCents"] == 8000
    assert overview["statusCounts"]["未缴"] == 1

    detail = client.get(f"/api/v1/fees/categories/{category['id']}").json()["data"]
    assert [row["studentName"] for row in detail["owing"]] == ["费用汇总甲", "费用汇总丙"]  # 欠额降序
    # 全班三个人都有记录 → 没有「漏收」的
    assert detail["missing"] == []


def test_ledger_kind_is_an_explicit_enum(client, db_session):
    """方向必须是显式枚举 —— 旧应用把「不是支出」一律当收入，一个错别字就记成进账。"""
    class_id = _class_id(db_session)
    category = _category(client, class_id)
    bad = client.post(
        "/api/v1/fee_ledger",
        json={"category_id": category["id"], "kind": "支", "item": "买扫除工具", "amount_cents": "30"},
        params={"classId": class_id},
    )
    assert bad.status_code == 400
    # 词表外的值由**字段级校验**先拦下（比钩子更早，提示也更具体）
    assert "只能填：收入、支出" in bad.json()["error"]["message"]


def test_missing_records_are_listed(client, db_session):
    """一条记录都没有的在册学生要列出来 —— 漏收要先发现。"""
    class_id = _class_id(db_session)
    _student(db_session, "费用漏收甲", "F9007")
    _student(db_session, "费用漏收乙", "F9008")
    category = _category(client, class_id)
    _record(client, class_id, category["id"], "费用漏收甲")

    detail = client.get(f"/api/v1/fees/categories/{category['id']}").json()["data"]
    assert detail["missing"] == ["费用漏收乙"]


def test_records_and_ledger_default_the_date_to_today(client, db_session):
    class_id = _class_id(db_session)
    _student(db_session, "费用日期甲", "F9009")
    category = _category(client, class_id)
    record = _record(client, class_id, category["id"], "费用日期甲")
    ledger = client.post(
        "/api/v1/fee_ledger",
        json={"category_id": category["id"], "item": "班费收缴", "amount_cents": "10"},
        params={"classId": class_id},
    ).json()["data"]
    assert record["date"] == date.today().isoformat()
    assert ledger["date"] == date.today().isoformat()
    assert ledger["kind"] == "收入"  # 默认方向
