"""学生档案的冲突报告与「学号唯一」这条结构保证。

为什么这些用例值得单独存在：学生姓名既不是唯一标识、又是老师唯一的输入方式。
写入口撞到重名会报错让人确认，但那是**一条一条**发现的 ——
所以需要一份一次列全的报告，让老师能主动去改。
报告说没冲突、录数据却被拦下来，比不做报告更糟，因此两者必须用同一套判据。
"""

from __future__ import annotations

from sqlalchemy import select

from app.db.base import utcnow
from app.models.class_ import Class
from app.models.student import Student


def _class_id(session) -> int:
    return session.scalar(select(Class.id).where(Class.deleted_at.is_(None)).limit(1))


def _student(session, name: str, sno: str, *, deleted: bool = False) -> Student:
    student = Student(class_id=_class_id(session), name=name, sno=sno, extra={})
    if deleted:
        student.deleted_at = utcnow()
    session.add(student)
    session.commit()
    return student


def _conflicts(client) -> dict:
    response = client.get("/api/v1/students/name-conflicts")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_conflicts_lists_duplicate_names(client, db_session):
    _student(db_session, "冲突报告甲", "C9001")
    _student(db_session, "冲突报告甲", "C9002")

    group = [item for item in _conflicts(client)["names"] if item["name"] == "冲突报告甲"]
    assert len(group) == 1
    assert group[0]["count"] == 2
    assert {item["sno"] for item in group[0]["students"]} == {"C9001", "C9002"}


def test_unique_students_are_not_reported(client, db_session):
    _student(db_session, "冲突唯一甲", "C9004")
    _student(db_session, "冲突唯一乙", "C9005")

    assert "冲突唯一甲" not in [item["name"] for item in _conflicts(client)["names"]]


def test_deleted_students_are_ignored(client, db_session):
    """已删除的学生不再制造冲突（保留他还会让老师看到一个查不到的「重复」）。"""
    _student(db_session, "冲突已删甲", "C9006")
    _student(db_session, "冲突已删甲", "C9007", deleted=True)

    assert "冲突已删甲" not in [item["name"] for item in _conflicts(client)["names"]]


def test_report_agrees_with_what_the_write_path_rejects(client, db_session):
    """报告说有冲突，写入口就必须真的拒绝 —— 两边的判据不能漂。"""
    _student(db_session, "冲突一致甲", "C9008")
    _student(db_session, "冲突一致甲", "C9009")

    assert [item for item in _conflicts(client)["names"] if item["name"] == "冲突一致甲"]

    response = client.post(
        "/api/v1/guardians",
        json={"student_name": "冲突一致甲", "name": "家长"},
    )
    assert response.status_code == 400
    assert "都叫" in response.json()["error"]["message"]


def test_duplicate_sno_is_blocked_structurally(client, db_session):
    """学号**不可能**冲突，所以它不需要「报告」：结构上就写不进去，写入口还给了中文说明。

    `students` 上有一个部分唯一索引 `uq_students_class_sno(class_id, sno) WHERE sno <> ''`
    （空学号不算 —— 还没编学号是常态），所以 `02` §2 验收里的「学号冲突进报告」
    是由结构保证的，不是靠事后检测。
    """
    class_id = _class_id(db_session)
    first = client.post(
        "/api/v1/students",
        json={"name": "学号唯一甲", "sno": "C9010"},
        params={"classId": class_id},
    )
    assert first.status_code == 201, first.text

    second = client.post(
        "/api/v1/students",
        json={"name": "学号唯一乙", "sno": "C9010"},
        params={"classId": class_id},
    )
    assert second.status_code == 400, second.text
    assert "已经有了" in second.json()["error"]["message"]

    # 空学号可以有多人：还没编学号不是错误
    for name in ("学号空号甲", "学号空号乙"):
        response = client.post(
            "/api/v1/students", json={"name": name, "sno": ""}, params={"classId": class_id}
        )
        assert response.status_code == 201, response.text
