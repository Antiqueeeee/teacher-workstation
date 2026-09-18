"""设置：班级信息与清空数据。

清空数据是全项目唯一的破坏性操作，所以用例盯的是**它的边界**：
确认字必须对、班级与字段定义要留下、媒体默认不动。
"""

from __future__ import annotations

from sqlalchemy import select

from app.models.class_ import Class
from app.models.student import Student, StudentFieldDef


def _class_id(session) -> int:
    return session.scalar(select(Class.id).where(Class.deleted_at.is_(None)).limit(1))


def _student(session, name: str, sno: str) -> Student:
    student = Student(class_id=_class_id(session), name=name, sno=sno, extra={})
    session.add(student)
    session.commit()
    return student


def test_class_info_can_be_updated(client, db_session):
    class_id = _class_id(db_session)
    updated = client.put(
        "/api/v1/settings/class",
        json={"name": "高二(3)班", "grade": "高二", "classNo": "3", "headTeacherName": "王老师"},
        params={"classId": class_id},
    ).json()["data"]
    assert updated["name"] == "高二(3)班" and updated["headTeacherName"] == "王老师"

    view = client.get("/api/v1/settings", params={"classId": class_id}).json()["data"]
    assert view["class"]["name"] == "高二(3)班"
    assert "storage" in view and "tableCounts" in view


def test_empty_class_name_is_refused(client, db_session):
    """班级名会显示在首页与简报上，留空要说清楚而不是悄悄变成空串。"""
    response = client.put(
        "/api/v1/settings/class", json={"name": ""}, params={"classId": _class_id(db_session)}
    )
    assert response.status_code == 400
    assert "不能为空" in response.json()["error"]["message"]


def test_settings_lists_table_counts(client, db_session):
    class_id = _class_id(db_session)
    _student(db_session, "设置统计甲", "S9001")
    view = client.get("/api/v1/settings", params={"classId": class_id}).json()["data"]
    counts = {item["table"]: item["rows"] for item in view["tableCounts"]}
    assert counts["students"] >= 1
    # 班级与字段定义是骨架，不该出现在「会被清掉」的清单里
    assert "classes" not in counts and "student_field_def" not in counts


def test_clear_requires_the_confirmation_word(client, db_session):
    class_id = _class_id(db_session)
    _student(db_session, "清空确认甲", "S9002")

    for wrong in ("", "确定", "clear"):
        response = client.post(
            "/api/v1/settings/clear", json={"confirm": wrong}, params={"classId": class_id}
        )
        assert response.status_code == 400, response.text
        assert "清空" in response.json()["error"]["message"]
    # 没通过确认 → 一条都没删
    assert client.get("/api/v1/students", params={"classId": class_id}).json()["meta"]["total"] == 1


def test_clear_removes_business_data_and_keeps_the_class(client, db_session):
    class_id = _class_id(db_session)
    student = _student(db_session, "清空测试甲", "S9003")
    client.post(
        "/api/v1/attendance",
        json={"date": "2026-09-10", "student_name": student.name, "type": "旷课"},
        params={"classId": class_id},
    )
    client.post("/api/v1/todos", json={"content": "清空前的待办"}, params={"classId": class_id})

    result = client.post(
        "/api/v1/settings/clear", json={"confirm": "清空"}, params={"classId": class_id}
    ).json()["data"]
    assert result["removed"] >= 3  # 学生 + 考勤 + 待办
    assert result["mediaKept"] is True

    assert client.get("/api/v1/students", params={"classId": class_id}).json()["meta"]["total"] == 0
    assert client.get("/api/v1/attendance", params={"classId": class_id}).json()["meta"]["total"] == 0
    assert client.get("/api/v1/todos", params={"classId": class_id}).json()["meta"]["total"] == 0
    # 班级还在（骨架），字段定义也还在 —— 否则学生档案会突然「没有字段」
    assert client.get("/api/v1/settings", params={"classId": class_id}).status_code == 200
    assert db_session.scalar(select(Class.id).where(Class.id == class_id)) == class_id
    assert db_session.scalar(select(StudentFieldDef.id).limit(1)) is not None


def test_clear_keeps_media_files_by_default(client, db_session):
    """照片与录音默认**不动** —— 几千张照片删了找不回来，不该混在这个按钮里。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "清空媒体甲", "S9004")
    contact = client.post(
        "/api/v1/contacts",
        json={"student_name": student.name},
        params={"classId": class_id},
    ).json()["data"]
    client.post(
        "/api/v1/media",
        files={"file": ("照片.png", _png(), "image/png")},
        data={"ownerTable": "contacts", "ownerId": str(contact["id"]), "classId": str(class_id)},
    )

    client.post("/api/v1/settings/clear", json={"confirm": "清空"}, params={"classId": class_id})
    # 附件记录留着（它是媒体库的东西，有专门的清理入口）
    assert client.get("/api/v1/media", params={"classId": class_id}).json()["data"]


def _png() -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (50, 40), (10, 90, 150)).save(buffer, "PNG")
    return buffer.getvalue()
