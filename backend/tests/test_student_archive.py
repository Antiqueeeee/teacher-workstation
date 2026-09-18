"""一生一档的测试。

要害是**档案上的数与各页面对得上**：阶段 2 的验收就是「学生档案欠交次数、
首页待收、科目平均率三处数值一致」。这些用例都在比「两个接口给的数是不是同一个」。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.models.class_ import Class
from app.models.student import Student


def _class_id(session) -> int:
    return session.scalar(select(Class.id).where(Class.deleted_at.is_(None)).limit(1))


def _student(session, name: str, sno: str) -> Student:
    student = Student(class_id=_class_id(session), name=name, sno=sno, extra={"gender": "男"})
    session.add(student)
    session.commit()
    return student


def _archive(client, student_id: int) -> dict:
    response = client.get(f"/api/v1/students/{student_id}/archive")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_archive_gathers_every_section(client, db_session):
    class_id = _class_id(db_session)
    student = _student(db_session, "档案测试甲", "A9001")
    today = date.today().isoformat()

    # 出勤：一条旷课
    client.post(
        "/api/v1/attendance",
        json={"date": today, "student_name": student.name, "type": "旷课"},
        params={"classId": class_id},
    )
    # 作业：一条欠交
    client.post(
        "/api/v1/homework",
        json={"date": today, "subject": "数学", "content": "档案作业", "total": 2, "unsubmitted_names": student.name},
        params={"classId": class_id},
    )
    # 违纪 / 谈话 / 家访 / 沟通 / 资助 / 体质
    client.post("/api/v1/disciplines", json={"date": today, "student_name": student.name, "type": "课堂纪律", "detail": "x"}, params={"classId": class_id})
    client.post("/api/v1/talks", json={"student_name": student.name, "reason": "x", "content": "y"}, params={"classId": class_id})
    client.post("/api/v1/visits", json={"student_name": student.name, "consensus": "手机管理一致"}, params={"classId": class_id})
    contact = client.post("/api/v1/contacts", json={"student_name": student.name, "needs_follow_up": True}, params={"classId": class_id}).json()["data"]
    client.post("/api/v1/grants", json={"student_name": student.name, "type": "国家助学金", "amount_cents": "500", "reason": "x"}, params={"classId": class_id})
    client.post("/api/v1/health_records", json={"student_name": student.name, "type": "哮喘", "detail": "运动后易发作", "emergency": "用随身喷雾"}, params={"classId": class_id})
    client.post(
        "/api/v1/media",
        files={"file": ("照片.png", _png(), "image/png")},
        data={"ownerTable": "contacts", "ownerId": str(contact["id"]), "classId": str(class_id)},
    )

    data = _archive(client, student.id)
    assert data["student"]["name"] == "档案测试甲"
    assert data["attendance"]["byType"] == {"旷课": 1}
    assert data["attendance"]["absenceDays"] == 1
    assert data["homework"]["lateCount"] == 1
    assert data["discipline"]["total"] == 1 and data["discipline"]["open"] == 1
    assert data["talks"]["total"] == 1
    assert data["visits"]["total"] == 1
    assert data["contacts"]["total"] == 1 and data["contacts"]["followUp"] == 1
    assert data["grants"]["totalCents"] == 50000
    assert data["health"]["type"] == "哮喘"
    assert data["attachments"] == 1  # 附件按学生归属，不必回头 join


def _png() -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (60, 40), (30, 120, 180)).save(buffer, "PNG")
    return buffer.getvalue()


def test_archive_homework_matches_the_home_page(client, db_session):
    """档案上的欠交次数必须与首页「作业待收」读的是同一张子表 —— 阶段 2 的验收。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "档案一致甲", "A9002")
    today = date.today().isoformat()
    client.post(
        "/api/v1/homework",
        json={"date": today, "subject": "语文", "content": "档案一致测试", "total": 2, "unsubmitted_names": student.name},
        params={"classId": class_id},
    )

    archive = _archive(client, student.id)
    overview = client.get("/api/v1/analytics/overview", params={"classId": class_id}).json()["data"]
    assert archive["homework"]["lateCount"] == 1
    assert overview["homework"]["pending"] == 1  # 同一张子表：两边都是 1


def test_archive_scores_match_the_exam_report(client, db_session):
    """档案里的名次与成绩页的报表同源（后端同一个函数算的）。"""
    class_id = _class_id(db_session)
    first = _student(db_session, "档案成绩甲", "A9003")
    second = _student(db_session, "档案成绩乙", "A9004")
    exam = client.post(
        "/api/v1/exams",
        json={"name": "档案月考", "date": today_str(), "kind": "月考"},
        params={"classId": class_id},
    ).json()["data"]
    client.put(
        f"/api/v1/exams/{exam['id']}/subjects",
        json={"subjects": [{"subject": "语文", "fullMarks": 150}]},
    )
    client.put(
        f"/api/v1/exams/{exam['id']}/sheet",
        json={
            "cells": [
                {"studentId": first.id, "subject": "语文", "value": 140},
                {"studentId": second.id, "subject": "语文", "value": 120},
            ]
        },
    )

    report = client.get(f"/api/v1/exams/{exam['id']}/report").json()["data"]
    page_row = [row for row in report["rows"] if row["studentId"] == first.id][0]

    archive = _archive(client, first.id)
    entry = [row for row in archive["scores"] if row["examId"] == exam["id"]][0]
    assert entry["total"] == page_row["total"]
    assert entry["rank"] == page_row["rank"] == 1
    assert entry["scoreRate"] == page_row["scoreRate"]
    assert entry["studentCount"] == report["taken"]


def today_str() -> str:
    return date.today().isoformat()


def test_archive_attendance_rate_matches_the_attendance_page(client, db_session):
    """档案里的出勤率与出勤页同一口径：分母是**本班登记过的天数**。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "档案出勤甲", "A9005")
    today = date.today().isoformat()
    client.post(
        "/api/v1/attendance",
        json={"date": today, "student_name": student.name, "type": "病假"},
        params={"classId": class_id},
    )

    archive = _archive(client, student.id)
    summary = client.get(
        "/api/v1/attendance/summary", params={"from": today, "to": today, "classId": class_id}
    ).json()["data"]
    assert archive["attendance"]["registeredDays"] == summary["registeredDays"] == 1
    assert archive["attendance"]["rate"] == summary["rate"]


def test_archive_conflicts_match_by_student_id_not_by_name(client, db_session):
    """矛盾调解按 student_id 匹配 —— 姓名互为子串的两个人不能互相算进对方的档案。"""
    class_id = _class_id(db_session)
    short = _student(db_session, "档案张三", "A9006")
    long = _student(db_session, "档案张三丰", "A9007")
    client.post(
        "/api/v1/conflicts",
        json={"parties_text": "档案张三丰", "reason": "宿舍作息", "detail": "x", "process": "y"},
        params={"classId": class_id},
    )

    assert _archive(client, long.id)["conflicts"]["total"] == 1
    assert _archive(client, short.id)["conflicts"]["total"] == 0  # 不是「包含」就算


def test_archive_of_a_deleted_student_is_not_found(client, db_session):
    from app.db.base import utcnow

    class_id = _class_id(db_session)
    student = _student(db_session, "档案已删甲", "A9008")
    student.deleted_at = utcnow()
    db_session.commit()

    response = client.get(f"/api/v1/students/{student.id}/archive")
    assert response.status_code == 404
    assert "不存在" in response.json()["error"]["message"]


def test_archive_attendance_rate_uses_the_class_window(client, db_session):
    """出勤率的分母是**这个班登记过的日子**，不是这个学生自己的记录范围。

    第一次实现时窗口取的是学生自己的最早/最晚记录，于是「本学期只请过一次假」
    分母只有那一天，算出 0% —— 数字没算错，但意思完全反了。
    """
    class_id = _class_id(db_session)
    student = _student(db_session, "档案窗口甲", "A9009")
    other = _student(db_session, "档案窗口乙", "A9010")

    # 班里登记了三天考勤，这个学生只缺席其中一天
    for day in ("2026-09-01", "2026-09-02", "2026-09-03"):
        response = client.put(
            "/api/v1/attendance/day",
            json={
                "date": day,
                "classId": class_id,
                "entries": (
                    [{"studentId": student.id, "type": "病假"}] if day == "2026-09-02" else []
                ),
            },
        )
        assert response.status_code == 200, response.text
    # 第二天需要有别人登记过，否则那一天不算「已登记」
    client.post(
        "/api/v1/attendance",
        json={"date": "2026-09-01", "student_name": other.name, "type": "迟到"},
        params={"classId": class_id},
    )

    archive = _archive(client, student.id)
    assert archive["attendance"]["registeredDays"] == 2  # 9-01 与 9-02
    assert archive["attendance"]["absenceDays"] == 1
    assert archive["attendance"]["rate"] == 50  # (2 − 1) / 2，而不是 0%
