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


# ---------- 代课简报 ----------


def test_substitute_brief_gathers_the_days_situation(client, db_session):
    """简报把「今天该知道的事」凑齐：考勤、体质、班委、值日、违纪、班规、座位。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "简报学生甲", "H9011")
    today = date.today().isoformat()

    client.post(
        "/api/v1/attendance",
        json={"date": today, "student_name": student.name, "type": "病假"},
        params={"classId": class_id},
    )
    client.post(
        "/api/v1/health_records",
        json={"student_name": student.name, "type": "哮喘", "detail": "运动后易发作", "emergency": "用随身喷雾", "level": "需重点关注"},
        params={"classId": class_id},
    )
    client.post(
        "/api/v1/cadres",
        json={"student_name": student.name, "post": "班长"},
        params={"classId": class_id},
    )
    client.post(
        "/api/v1/duty_groups",
        json={"weekday": f"星期{'一二三四五六日'[date.today().isoweekday() - 1]}", "area": "教室地面", "members_text": student.name},
        params={"classId": class_id},
    )
    client.post(
        "/api/v1/disciplines",
        json={"date": today, "student_name": student.name, "type": "课堂纪律", "detail": "上课说话"},
        params={"classId": class_id},
    )
    client.post("/api/v1/rules", json={"title": "上课不许吃东西", "content": "x"}, params={"classId": class_id})

    brief = client.get(
        "/api/v1/analytics/substitute", params={"date": today, "classId": class_id}
    ).json()["data"]

    assert brief["weekday"] == f"星期{'一二三四五六日'[date.today().isoweekday() - 1]}"
    assert brief["attendance"]["absent"] == 1
    assert brief["attendance"]["absentStudents"] == ["简报学生甲"]
    assert brief["health"][0]["type"] == "哮喘"
    assert brief["health"][0]["emergency"] == "用随身喷雾"
    assert brief["cadres"][0]["post"] == "班长"
    assert brief["duty"][0]["area"] == "教室地面"
    assert brief["discipline"][0]["studentName"] == "简报学生甲"
    assert brief["rules"][0]["title"] == "上课不许吃东西"
    assert brief["seats"]["rows"] >= 1
    # 课表已落地：这段现在从课表里取（留空则没有课）
    assert brief["todaySlots"] == []
    assert brief["missingSections"] == []


def test_substitute_brief_flags_an_unregistered_day(client, db_session):
    """没登记考勤的那天要**明说**「缺席名单可能不准」，而不是假装全员出勤。"""
    class_id = _class_id(db_session)
    _student(db_session, "简报缺勤甲", "H9012")
    brief = client.get(
        "/api/v1/analytics/substitute",
        params={"date": "2026-01-05", "classId": class_id},
    ).json()["data"]
    assert brief["attendance"]["registered"] is False
    assert brief["attendance"]["rate"] is None


def test_substitute_brief_only_lists_key_health_records(client, db_session):
    """体质只列「需重点关注」的 —— 简报要短到能一眼看完，常规关注不进这一块。"""
    class_id = _class_id(db_session)
    urgent = _student(db_session, "简报体质甲", "H9013")
    normal = _student(db_session, "简报体质乙", "H9014")
    client.post(
        "/api/v1/health_records",
        json={"student_name": urgent.name, "type": "癫痫", "detail": "x", "emergency": "y", "level": "需重点关注"},
        params={"classId": class_id},
    )
    client.post(
        "/api/v1/health_records",
        json={"student_name": normal.name, "type": "近视", "detail": "x", "emergency": "y", "level": "常规关注"},
        params={"classId": class_id},
    )

    brief = client.get("/api/v1/analytics/substitute", params={"classId": class_id}).json()["data"]
    assert [row["studentName"] for row in brief["health"]] == ["简报体质甲"]


# ---------- 数据看板 ----------


def _dashboard(client, class_id: int, days: int = 14) -> dict:
    response = client.get("/api/v1/analytics/dashboard", params={"days": days, "classId": class_id})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_dashboard_keeps_unregistered_days_empty(client, db_session):
    """未登记的日子在趋势里是**空**，不是 100%（旧应用把它画成满勤）。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "看板学生甲", "H9020")
    today = date.today().isoformat()
    client.post(
        "/api/v1/attendance",
        json={"date": today, "student_name": student.name, "type": "迟到"},
        params={"classId": class_id},
    )

    data = _dashboard(client, class_id, days=5)
    assert len(data["attendanceTrend"]) == 5
    registered = [day for day in data["attendanceTrend"] if day["registered"]]
    assert len(registered) == 1 and registered[0]["date"] == today
    assert registered[0]["rate"] == 100  # 只有迟到 → 出勤率 100%
    assert all(day["rate"] is None for day in data["attendanceTrend"] if not day["registered"])


def test_dashboard_tops_count_by_student_not_by_name(client, db_session):
    """Top 榜按 student_id 去重 —— 旧应用按姓名，重名会合并成一个人。"""
    class_id = _class_id(db_session)
    twin_a = _student(db_session, "看板同名", "H9021")
    twin_b = _student(db_session, "看板同名", "H9022")
    today = date.today().isoformat()

    # 用点名按 studentId 登记（同名走不了姓名那条路）
    client.put(
        "/api/v1/attendance/day",
        json={
            "date": today,
            "classId": class_id,
            "entries": [
                {"studentId": twin_a.id, "type": "旷课"},
                {"studentId": twin_b.id, "type": "旷课"},
            ],
        },
    )

    data = _dashboard(client, class_id, days=5)
    assert len(data["absentTop"]) == 2  # 两个人，不是「一个叫这名字的人」
    assert {row["studentId"] for row in data["absentTop"]} == {twin_a.id, twin_b.id}
    assert all(row["count"] == 1 for row in data["absentTop"])


def test_dashboard_discipline_breakdown_and_monthly(client, db_session):
    class_id = _class_id(db_session)
    student = _student(db_session, "看板违纪甲", "H9023")
    today = date.today().isoformat()
    for level, kind in (("严重", "课堂纪律"), ("轻微", "作业纪律"), ("一般", "课堂纪律")):
        client.post(
            "/api/v1/disciplines",
            json={"date": today, "student_name": student.name, "type": kind, "detail": "x", "level": level},
            params={"classId": class_id},
        )
    client.post(
        "/api/v1/talks",
        json={"date": today, "student_name": student.name, "reason": "x", "content": "y"},
        params={"classId": class_id},
    )

    data = _dashboard(client, class_id)
    assert data["discipline"]["byLevel"] == {"严重": 1, "轻微": 1, "一般": 1}
    assert data["discipline"]["byType"] == {"课堂纪律": 2, "作业纪律": 1}
    assert data["discipline"]["open"] == 3
    assert data["discipline"]["top"][0]["count"] == 3
    # 月度走势的月份按时间正序，最后一个就是这个月
    assert data["months"][-1] == today[:7]
    assert data["monthly"]["talks"][-1] == 1
    assert data["monthly"]["contacts"][-1] == 0
