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


# ------------------------------------------------------- 「清空一个班」的边界（阶段 5 评审 M1）


def _second_class(session, grade: str = "高二", class_no: str = "(4)班") -> Class:
    row = Class(grade=grade, class_no=class_no, name="")
    session.add(row)
    session.commit()
    return row


def _count(session, model) -> int:
    from sqlalchemy import func

    return session.scalar(select(func.count()).select_from(model)) or 0


def test_clear_one_class_does_not_touch_another_classes_children(client, db_session):
    """清空 A 班**不能**动 B 班的数据 —— 尤其是那些没有 `class_id` 的子表。

    这些子表的行只能靠父表判断归属：早先「没有 class_id 就整表 DELETE」的写法
    会把 B 班的未交名单、考试科目、调解参与人一起删光，而界面上完全看不出来。
    """
    from app.models.classroom import DutyGroup, DutyMember
    from app.models.communication import Conflict, ConflictParty
    from app.models.exam import ExamSubject
    from app.models.homework import HomeworkUnsubmitted

    class_a = _class_id(db_session)
    class_b = _second_class(db_session).id
    student_a = _student(db_session, "甲班学生", "S9101")
    student_b = Student(class_id=class_b, name="乙班学生", sno="S9102", extra={})
    db_session.add(student_b)
    db_session.commit()

    # A 班各来一条（会被清掉），B 班各来一条（必须留下）
    for class_id, student, tag in ((class_a, student_a, "甲"), (class_b, student_b, "乙")):
        client.post(
            "/api/v1/homework",
            json={
                "date": "2026-09-10",
                "subject": "数学",
                "content": f"{tag}班作业",
                "unsubmitted_names": student.name,
            },
            params={"classId": class_id},
        )
        client.post(
            "/api/v1/exams",
            json={"name": f"{tag}班月考", "date": "2026-09-12", "kind": "月考"},
            params={"classId": class_id},
        )
        client.post(
            "/api/v1/conflicts",
            json={
                "date": "2026-09-11",
                "parties_text": student.name,
                "reason": "借还物品纠纷",
                "detail": "x",
                "process": "y",
            },
            params={"classId": class_id},
        )
        client.post(
            "/api/v1/duty_groups",
            json={"weekday": "星期一", "area": "教室地面", "members_text": student.name},
            params={"classId": class_id},
        )

    assert _count(db_session, HomeworkUnsubmitted) == 2
    assert _count(db_session, ConflictParty) == 2
    assert _count(db_session, DutyMember) == 2
    assert _count(db_session, ExamSubject) > 1

    # 只清 A 班
    client.post("/api/v1/settings/clear", json={"confirm": "清空"}, params={"classId": class_a})

    remaining_homework = db_session.scalars(select(HomeworkUnsubmitted)).all()
    remaining_parties = db_session.scalars(select(ConflictParty)).all()
    remaining_members = db_session.scalars(select(DutyMember)).all()
    assert [row.student_name for row in remaining_homework] == ["乙班学生"]
    assert [row.student_name for row in remaining_parties] == ["乙班学生"]
    assert [row.student_name for row in remaining_members] == ["乙班学生"]
    # B 班的考试科目还在，否则那场考试的成绩一条都进不了统计
    exams_b = client.get("/api/v1/exams", params={"classId": class_b}).json()["data"]
    assert exams_b and exams_b[0]["name"] == "乙班月考"
    subjects = client.get(f"/api/v1/exams/{exams_b[0]['id']}/sheet").json()["data"]
    assert subjects["subjects"] or subjects.get("rows") is not None
    db_session.expire_all()
    assert _count(db_session, Conflict) == 1
    assert _count(db_session, DutyGroup) == 1


def test_clear_keeps_shared_tables_and_says_so(client, db_session):
    """跨班共享的表（话术模板、课程本身）不在清理范围内，而且**要在界面上说明**。"""
    class_id = _class_id(db_session)
    _student(db_session, "共享表甲", "S9103")
    client.post(
        "/api/v1/templates",
        json={"title": "期末寄语", "content": "继续加油"},
        params={"classId": class_id},
    )
    client.post("/api/v1/courses", json={"name": "数学", "subject": "数学"})

    view = client.get("/api/v1/settings", params={"classId": class_id}).json()["data"]
    counts = {item["table"]: item for item in view["tableCounts"]}
    assert counts["templates"]["kept"] is True
    assert counts["courses"]["kept"] is True
    # 表名给中文（旧版把 homework_unsubmitted 这种英文名直接摆给老师看）
    assert counts["templates"]["title"] == "话术模板库"
    assert counts["homework"]["title"] == "作业情况"

    client.post("/api/v1/settings/clear", json={"confirm": "清空"}, params={"classId": class_id})
    assert client.get("/api/v1/templates").json()["meta"]["total"] == 1
    assert client.get("/api/v1/courses").json()["meta"]["total"] == 1
    assert client.get("/api/v1/students", params={"classId": class_id}).json()["meta"]["total"] == 0


def test_every_table_has_a_clear_rule():
    """每张表都要有明确的处置规则（班级范围 / 子表带父表 / 共享保留）—— **不许有空档**。

    漏一个的后果是「清空 A 班」把 B 班或全班共享的数据一起删掉，而且不会报错。
    """
    from app.services.settings_service import unclassified_tables

    assert unclassified_tables() == set()
