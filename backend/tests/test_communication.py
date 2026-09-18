"""沟通留档六张表的测试（家访 / 谈话 / 班会 / 活动 / 大事记 / 矛盾调解）。

它们的共同点是「都能挂附件」，所以用例盯三件事：与学生关联（家访/谈话/矛盾调解）、
各自的特殊规则（班会的出席人数、矛盾调解的多人子表）、以及附件确实能挂上去。
"""

from __future__ import annotations

import io
from datetime import date

from PIL import Image
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


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (120, 90), (90, 140, 200)).save(buffer, "PNG")
    return buffer.getvalue()


def _attach(client, class_id: int, table: str, record_id: int, name: str = "现场.png") -> dict:
    response = client.post(
        "/api/v1/media",
        files={"file": (name, _png(), "image/png")},
        data={"ownerTable": table, "ownerId": str(record_id), "classId": str(class_id)},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


# ---------- 与学生关联 ----------


def test_visit_and_talk_link_the_student(client, db_session):
    class_id = _class_id(db_session)
    student = _student(db_session, "留档家访甲", "V9001")

    visit = client.post(
        "/api/v1/visits",
        json={"date": "2026-09-12", "student_name": student.name, "teacher": "王老师",
              "consensus": "手机管理达成一致"},
        params={"classId": class_id},
    ).json()["data"]
    assert visit["student_id"] == student.id and visit["sno"] == "V9001"

    talk = client.post(
        "/api/v1/talks",
        json={"date": "2026-09-13", "student_name": student.name, "type": "心理疏导",
              "reason": "最近情绪低落", "content": "聊了一节课"},
        params={"classId": class_id},
    ).json()["data"]
    assert talk["student_id"] == student.id
    assert talk["type"] == "心理疏导" and talk["place"] == "办公室"


def test_absent_missing_student_is_reported(client, db_session):
    class_id = _class_id(db_session)
    response = client.post(
        "/api/v1/talks",
        json={"date": "2026-09-13", "student_name": "查无此人", "reason": "x", "content": "y"},
        params={"classId": class_id},
    )
    assert response.status_code == 400
    assert "查无此人" in response.json()["error"]["message"]


# ---------- 班会：出席人数 ----------


def test_meeting_attend_cannot_exceed_expected(client, db_session):
    """旧应用是一个「45/45」的自由文本框 —— 统计不出来，也拦不住写错的数。"""
    class_id = _class_id(db_session)
    created = client.post(
        "/api/v1/meetings",
        json={"date": "2026-09-14", "theme": "诚信考试", "attend_actual": 45,
              "attend_expected": 45, "content": "组织学习考试纪律"},
        params={"classId": class_id},
    ).json()["data"]
    assert created["attend_text"] == "45/45"

    bad = client.post(
        "/api/v1/meetings",
        json={"date": "2026-09-15", "theme": "感恩教育", "attend_actual": 50,
              "attend_expected": 45, "content": "x"},
        params={"classId": class_id},
    )
    assert bad.status_code == 400
    assert "不可能超过" in bad.json()["error"]["message"]


def test_meeting_date_defaults_to_today(client, db_session):
    class_id = _class_id(db_session)
    created = client.post(
        "/api/v1/meetings",
        json={"theme": "安全教育", "content": "x"},
        params={"classId": class_id},
    ).json()["data"]
    assert created["date"] == date.today().isoformat()


# ---------- 矛盾调解：多人子表 ----------


def test_conflict_parties_are_linked_students(client, db_session):
    """涉及学生是**多人**子表 —— 旧应用把姓名串存在一个字段里，
    一生一档用 `parties.includes(name)` 匹配，姓名互为子串时会挂错人（文档 §31）。"""
    class_id = _class_id(db_session)
    _student(db_session, "矛盾张三", "V9002")
    _student(db_session, "矛盾张三丰", "V9003")

    created = client.post(
        "/api/v1/conflicts",
        json={
            "date": "2026-09-16",
            "parties_text": "矛盾张三、矛盾张三丰",
            "reason": "宿舍作息冲突",
            "detail": "熄灯后说话",
            "process": "分别了解诉求 → 面对面沟通",
            "level": "一般",
        },
        params={"classId": class_id},
    )
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    assert data["parties_cache"] == "矛盾张三、矛盾张三丰"
    assert data["status"] == "跟踪中" and data["resolved"] is False

    # 搜「矛盾张三」只该命中这条（子串误匹配的根源就在这里被消掉了：走的是学生 id）
    found = client.get("/api/v1/conflicts", params={"classId": class_id, "q": "矛盾张三丰"}).json()
    assert found["meta"]["total"] == 1


def test_conflict_rejects_unknown_party(client, db_session):
    class_id = _class_id(db_session)
    _student(db_session, "矛盾李四", "V9004")
    response = client.post(
        "/api/v1/conflicts",
        json={"date": "2026-09-16", "parties_text": "矛盾李四、查无此人", "reason": "x",
              "detail": "y", "process": "z"},
        params={"classId": class_id},
    )
    assert response.status_code == 400
    assert "认不出的" in response.json()["error"]["message"]


# ---------- 附件（六张表都能挂） ----------


def test_every_communication_table_can_hold_attachments(client, db_session):
    """照片与录音统一走媒体库 —— 六张表都声明了 media_owner，列表上就有「附件」入口。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "留档附件甲", "V9005")

    records = {
        "visits": client.post("/api/v1/visits", json={"student_name": student.name}, params={"classId": class_id}).json()["data"],
        "talks": client.post("/api/v1/talks", json={"student_name": student.name, "reason": "x", "content": "y"}, params={"classId": class_id}).json()["data"],
        "meetings": client.post("/api/v1/meetings", json={"theme": "主题", "content": "x"}, params={"classId": class_id}).json()["data"],
        "class_activities": client.post("/api/v1/class_activities", json={"title": "活动", "content": "x"}, params={"classId": class_id}).json()["data"],
        "class_events": client.post("/api/v1/class_events", json={"title": "事件", "content": "x"}, params={"classId": class_id}).json()["data"],
        "conflicts": client.post("/api/v1/conflicts", json={"parties_text": student.name, "reason": "x", "detail": "y", "process": "z"}, params={"classId": class_id}).json()["data"],
    }

    for table, record in records.items():
        media = _attach(client, class_id, table, record["id"])
        assert media["kind"] == "image"
        listed = client.get(
            "/api/v1/media", params={"ownerTable": table, "ownerId": record["id"]}
        ).json()["data"]
        assert len(listed) == 1

        # 通用列表里也数得出来（一次查询，不是每条记录查一次）
        rows = client.get(f"/api/v1/{table}", params={"classId": class_id}).json()["data"]
        assert rows[0]["attachment_count"] == 1


def test_activity_and_event_are_plain_records(client, db_session):
    class_id = _class_id(db_session)
    activity = client.post(
        "/api/v1/class_activities",
        json={"title": "春季趣味运动会", "type": "文体活动", "organizer": "班委", "content": "x"},
        params={"classId": class_id},
    ).json()["data"]
    assert activity["type"] == "文体活动" and activity["date"] == date.today().isoformat()

    event = client.post(
        "/api/v1/class_events",
        json={"title": "期中平均分年级第一", "category": "荣誉", "content": "x"},
        params={"classId": class_id},
    ).json()["data"]
    assert event["category"] == "荣誉"
    assert event["participants"] == "全班"  # 默认值
    assert event["honored"] is True  # 荣誉/竞赛标记（看板按它筛）
