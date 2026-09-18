"""首页与看板聚合的测试。

要害是**口径一致**：首页上的出勤率必须与出勤页算出来的一样、平均提交率与作业列表
显示的一样。旧应用首页那张「作业待收」卡片读的是两个不存在的字段（恒为 0），
而列表页另有一套算法 —— 所以这些用例都在比「两个接口给的数是不是同一个」。
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from app.models.class_ import Class
from app.models.student import Student


def _class_id(session) -> int:
    return session.scalar(select(Class.id).where(Class.deleted_at.is_(None)).limit(1))


def _student(session, name: str, sno: str, *, boarding: str = "住校") -> Student:
    student = Student(class_id=_class_id(session), name=name, sno=sno, extra={"boarding": boarding})
    session.add(student)
    session.commit()
    return student


def _overview(client, class_id: int) -> dict:
    response = client.get("/api/v1/analytics/overview", params={"classId": class_id})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _followups(client, class_id: int, limit: int = 14) -> list[dict]:
    response = client.get(
        "/api/v1/analytics/followups", params={"classId": class_id, "limit": limit}
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_overview_counts_from_the_class(client, db_session):
    class_id = _class_id(db_session)
    _student(db_session, "首页学生甲", "H9001")
    _student(db_session, "首页学生乙", "H9002", boarding="走读")

    data = _overview(client, class_id)
    assert data["students"]["total"] == 2
    assert data["students"]["boarding"] == 1
    assert data["date"] == date.today().isoformat()
    # 还没登记考勤：registered 为假、出勤率为空（**不是 100%**）
    assert data["attendance"]["registered"] is False
    assert data["attendance"]["rate"] is None


def test_overview_attendance_matches_the_attendance_page(client, db_session):
    """首页的出勤率与出勤页的必须是同一个数（同一个服务函数算出来的）。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "首页出勤甲", "H9003")
    today = date.today().isoformat()
    assert (
        client.post(
            "/api/v1/attendance",
            json={"date": today, "student_name": student.name, "type": "旷课"},
            params={"classId": class_id},
        ).status_code
        == 201
    )

    home = _overview(client, class_id)["attendance"]
    page = client.get(
        "/api/v1/attendance/summary", params={"from": today, "to": today, "classId": class_id}
    ).json()["data"]
    assert home["rate"] == page["rate"]
    assert home["absent"] == page["absent"] == 1
    assert home["registered"] is True
    assert home["absentStudents"] == ["首页出勤甲"]


def test_overview_homework_matches_the_homework_list(client, db_session):
    """「作业待收」接的是新的提交率口径，不是两个不存在的字段。"""
    class_id = _class_id(db_session)
    _student(db_session, "首页作业甲", "H9004")
    created = client.post(
        "/api/v1/homework",
        json={
            "date": date.today().isoformat(),
            "subject": "数学",
            "content": "首页作业测试",
            "total": 4,
            "unsubmitted_names": "首页作业甲",
        },
        params={"classId": class_id},
    ).json()["data"]
    client.post(
        "/api/v1/homework",
        json={
            "date": date.today().isoformat(),
            "subject": "语文",
            "content": "首页作业测试2",
            "total": 4,
        },
        params={"classId": class_id},
    )

    data = _overview(client, class_id)["homework"]
    assert data["count"] == 2
    assert data["pending"] == 1  # 只有一条有未交名单
    # 平均提交率与作业列表里那个 rate 同源：(75 + 100) / 2 = 88
    assert data["averageRate"] == round((created["rate"] + 100) / 2)


def test_overview_counts_todos_contacts_and_attachments(client, db_session):
    class_id = _class_id(db_session)
    student = _student(db_session, "首页统计甲", "H9005")
    client.post(
        "/api/v1/todos", json={"content": "首页待办"}, params={"classId": class_id}
    )
    contact = client.post(
        "/api/v1/contacts",
        json={
            "date": date.today().isoformat(),
            "student_name": student.name,
            "needs_follow_up": True,
        },
        params={"classId": class_id},
    ).json()["data"]
    client.post(
        "/api/v1/media",
        files={"file": ("照片.png", _png(), "image/png")},
        data={"ownerTable": "contacts", "ownerId": str(contact["id"]), "classId": str(class_id)},
    )

    data = _overview(client, class_id)
    assert data["todos"]["open"] == 1
    assert data["contacts"]["followUp"] == 1
    assert data["attachments"] == 1


def _png() -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (80, 60), (30, 90, 160)).save(buffer, "PNG")
    return buffer.getvalue()


def test_overview_reports_duplicate_names(client, db_session):
    class_id = _class_id(db_session)
    _student(db_session, "首页同名甲", "H9006")
    _student(db_session, "首页同名甲", "H9007")
    assert _overview(client, class_id)["students"]["duplicateNames"] == 1


# ---------- 跟进清单 ----------


def test_followups_sorts_by_urgency_and_links_to_the_record(client, db_session):
    """清单按紧急度排，而且每条都能跳到**具体那条记录**（旧应用只跳到模块首页）。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "跟进清单甲", "H9008")
    today = date.today().isoformat()

    # 权重 40：待办到期
    client.post("/api/v1/todos", json={"content": "跟进待办"}, params={"classId": class_id})
    # 权重 72：家长那边还要再联系
    client.post(
        "/api/v1/contacts",
        json={"date": today, "student_name": student.name, "needs_follow_up": True},
        params={"classId": class_id},
    )
    # 权重 95：缺席还没联系家长（跟进状态默认「待联系」的就是旷课）
    client.post(
        "/api/v1/attendance",
        json={"date": today, "student_name": student.name, "type": "旷课"},
        params={"classId": class_id},
    )

    items = _followups(client, class_id)
    assert [item["kind"] for item in items] == [
        "absent_uncontacted",
        "contact_follow_up",
        "todo_due",
    ]
    assert [item["weight"] for item in items] == [95, 72, 40]
    assert all(item["table"] and item["id"] for item in items)
    assert "还没联系家长" in items[0]["text"]
    assert items[0]["studentName"] == "跟进清单甲"


def test_followups_respects_the_window_and_the_limit(client, db_session):
    """窗口外的不进清单；`limit` 也真的生效（前端一屏只放得下那么多）。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "跟进窗口甲", "H9009")
    old = (date.today() - timedelta(days=60)).isoformat()

    client.post(
        "/api/v1/contacts",
        json={"date": old, "student_name": student.name, "needs_follow_up": True},
        params={"classId": class_id},
    )
    assert _followups(client, class_id) == []

    for index in range(3):
        client.post(
            "/api/v1/todos", json={"content": f"跟进待办{index}"}, params={"classId": class_id}
        )
    assert len(_followups(client, class_id, limit=2)) == 2


def test_followups_skip_contacted_absence(client, db_session):
    """已经联系过的缺勤不该再进清单（跟进状态标了「已通知」）。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "跟进已联系甲", "H9010")
    created = client.post(
        "/api/v1/attendance",
        json={"date": date.today().isoformat(), "student_name": student.name, "type": "旷课"},
        params={"classId": class_id},
    ).json()["data"]
    client.patch(f"/api/v1/attendance/{created['id']}", json={"handled": "已通知"})

    items = [item for item in _followups(client, class_id) if item["kind"] == "absent_uncontacted"]
    assert items == []
