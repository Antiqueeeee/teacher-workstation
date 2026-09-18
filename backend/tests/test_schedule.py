"""课表、倒计时、时间轴。

课表要守住的是「一格一门课」：旧应用同一格能存两门课，界面上只显示一门，
另一门等于人间蒸发。
"""

from __future__ import annotations

from datetime import date, timedelta

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


def _slot(client, class_id: int, weekday: str, period: str, subject: str, **extra):
    payload = {"weekday": weekday, "period": period, "subject": subject}
    payload.update(extra)
    return client.post("/api/v1/schedule_slots", json=payload, params={"classId": class_id})


def test_slot_cell_holds_only_one_lesson(client, db_session):
    """同一格放第二门课要被拦下并说清是谁占着 —— 旧应用能存，但界面上看不见第二门。"""
    class_id = _class_id(db_session)
    assert _slot(client, class_id, "星期一", "第1节", "数学", teacher="王老师").status_code == 201

    again = _slot(client, class_id, "星期一", "第1节", "语文")
    assert again.status_code == 400, again.text
    assert "已经有「数学」" in again.json()["error"]["message"]

    # 别的格子不受影响
    assert _slot(client, class_id, "星期一", "第2节", "语文").status_code == 201


def test_slot_rejects_unknown_weekday_and_period(client, db_session):
    class_id = _class_id(db_session)
    bad_day = _slot(client, class_id, "周1", "第1节", "数学")
    assert bad_day.status_code == 400
    assert "只能填：星期一" in bad_day.json()["error"]["message"]

    bad_period = _slot(client, class_id, "星期一", "第一节", "数学")
    assert bad_period.status_code == 400
    assert "只能填：第1节" in bad_period.json()["error"]["message"]


def test_countdown_computes_days_left(client, db_session):
    """「还有几天」由后端算 —— 界面自己减的日子在不同设备上可能差一天。"""
    class_id = _class_id(db_session)
    target = date.today() + timedelta(days=10)
    created = client.post(
        "/api/v1/countdowns",
        json={"title": "期末考试", "date": target.isoformat(), "category": "考试"},
        params={"classId": class_id},
    ).json()["data"]
    assert created["days_left"] == 10
    assert created["category"] == "考试"


def test_timeline_merges_several_modules_by_date(client, db_session):
    """时间轴在后端合并 —— 加一类留档只改一处，不必改前端。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "时间轴甲", "T9001")
    today = date.today().isoformat()
    older = (date.today() - timedelta(days=5)).isoformat()

    client.post("/api/v1/talks", json={"date": older, "student_name": student.name, "reason": "成绩下滑", "content": "x"}, params={"classId": class_id})
    client.post("/api/v1/contacts", json={"date": today, "student_name": student.name, "content": "聊了月考"}, params={"classId": class_id})
    client.post("/api/v1/class_events", json={"date": today, "title": "期中平均分年级第一", "content": "x"}, params={"classId": class_id})

    feed = client.get("/api/v1/analytics/timeline", params={"classId": class_id}).json()["data"]
    assert len(feed) == 3
    assert feed[0]["date"] == today  # 日期倒序
    assert {item["label"] for item in feed} == {"家长联系", "大事记", "谈话"}
    assert all(item["table"] and item["id"] for item in feed)  # 每条都能追到具体记录


def test_substitute_brief_includes_todays_lessons(client, db_session):
    """代课简报的「今日课表」段现在有数据了（课表模块落地后接上的）。"""
    class_id = _class_id(db_session)
    weekday = f"星期{'一二三四五六日'[date.today().isoweekday() - 1]}"
    assert _slot(client, class_id, weekday, "第1节", "数学", teacher="王老师", room="305").status_code == 201

    brief = client.get(
        "/api/v1/analytics/substitute",
        params={"date": date.today().isoformat(), "classId": class_id},
    ).json()["data"]
    assert brief["todaySlots"][0]["subject"] == "数学"
    assert brief["todaySlots"][0]["teacher"] == "王老师"
    assert brief["missingSections"] == []  # 不再有缺的段


def test_week_grid_puts_every_slot_in_its_cell(client, db_session):
    """一周网格：行是节次、列是星期，**空位也在**（界面直接铺格子，不自己推断顺序）。

    规则：「格子在哪」由后端算（`schedule_service.week_view`），
    界面只负责显示 —— 星期与节次的先后顺序不该由前端再排一遍。
    """
    class_id = _class_id(db_session)
    assert _slot(client, class_id, "星期三", "第3节", "数学", teacher="王老师").status_code == 201
    assert _slot(client, class_id, "星期一", "第1节", "语文").status_code == 201

    data = client.get("/api/v1/schedule/week", params={"classId": class_id}).json()["data"]
    assert data["weekdays"][2] == "星期三" and data["weekdays"][0] == "星期一"
    third = data["periods"].index("第3节")
    first = data["periods"].index("第1节")

    assert data["grid"][2][third]["subject"] == "数学"
    assert data["grid"][2][third]["teacher"] == "王老师"
    # 星期一第 3 节没课：格子仍在（slotId 为空），界面据此显示成空格
    assert data["grid"][0][third]["slotId"] is None
    assert data["grid"][0][first]["subject"] == "语文"
    # 删掉之后那一格回到空
    slot_id = data["grid"][0][first]["slotId"]
    client.delete(f"/api/v1/schedule_slots/{slot_id}")
    after = client.get("/api/v1/schedule/week", params={"classId": class_id}).json()["data"]
    assert after["grid"][0][first]["slotId"] is None
