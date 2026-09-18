"""班级角色与学生事务六张表的测试（班委 / 团员 / 值日 / 违纪 / 特殊体质 / 助学金）。

这些页面本身是通用链路，所以用例只盯**它们各自特有的那点规则**：
学生引用解析、值日成员子表、金额存分、一人一条体质档案、团员与档案的一致性提示。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.models.class_ import Class
from app.models.student import Student


def _class_id(session) -> int:
    return session.scalar(select(Class.id).where(Class.deleted_at.is_(None)).limit(1))


def _student(session, name: str, sno: str, *, politics: str = "") -> Student:
    student = Student(
        class_id=_class_id(session),
        name=name,
        sno=sno,
        extra={"politics": politics} if politics else {},
    )
    session.add(student)
    session.commit()
    return student


# ---------- 班委 / 团员 / 违纪：学生引用 ----------


def test_cadre_links_the_student_and_reads_phone_from_the_archive(client, db_session):
    """电话取自学生档案（旧应用是保存时回填一次的快照，学生换号就过期了）。"""
    class_id = _class_id(db_session)
    student = Student(
        class_id=class_id, name="班委测试甲", sno="C9001", extra={"phone": "13800000001"}
    )
    db_session.add(student)
    db_session.commit()

    created = client.post(
        "/api/v1/cadres",
        json={"student_name": "班委测试甲", "post": "班长", "appraise": "优秀"},
        params={"classId": class_id},
    )
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    assert data["student_id"] == student.id
    assert data["phone"] == "13800000001"

    # 档案里换了号，列表里立刻是新号（不是快照）
    student.extra = {"phone": "13900000002"}
    db_session.commit()
    rows = client.get("/api/v1/cadres", params={"classId": class_id}).json()["data"]
    assert rows[0]["phone"] == "13900000002"


def test_discipline_counts_by_student_not_by_name(client, db_session):
    """违纪按学生统计 —— 旧应用按姓名，重名会合并成一个人。"""
    class_id = _class_id(db_session)
    _student(db_session, "违纪同名甲", "C9002")
    _student(db_session, "违纪同名甲", "C9003")
    for sno in ("C9002", "C9003"):
        student = db_session.scalar(select(Student).where(Student.sno == sno))
        response = client.post(
            "/api/v1/disciplines",
            json={
                "date": "2026-09-10",
                "student_name": student.name,
                "type": "课堂纪律",
                "detail": "上课说话",
                "level": "轻微",
            },
            params={"classId": class_id},
        )
        # 同名会被明确拒绝（不猜是谁）
        assert response.status_code == 400
        assert "都叫" in response.json()["error"]["message"]

    # 用学号指定也不行 —— 这张表只收姓名，所以给了「去档案里区分」的出路
    assert client.get("/api/v1/disciplines", params={"classId": class_id}).json()["meta"]["total"] == 0


def test_youth_member_and_archive_consistency_report(client, db_session):
    """团员名册与档案「政治面貌」对不上的两类人都要列出来 —— **不自动改写任何一边**。"""
    class_id = _class_id(db_session)
    _student(db_session, "团员一致甲", "C9004", politics="共青团员")
    _student(db_session, "团员缺档甲", "C9005", politics="群众")
    _student(db_session, "档案说甲", "C9006", politics="共青团员")
    _student(db_session, "团员无关甲", "C9007")

    for name in ("团员一致甲", "团员缺档甲"):
        assert (
            client.post(
                "/api/v1/youth_members",
                json={"student_name": name, "join_date": "2026-05-04"},
                params={"classId": class_id},
            ).status_code
            == 201
        )

    report = client.get("/api/v1/youth_members/consistency", params={"classId": class_id}).json()["data"]
    assert [item["studentName"] for item in report["inRosterNotInArchive"]] == ["团员缺档甲"]
    assert [item["studentName"] for item in report["inArchiveNotInRoster"]] == ["档案说甲"]


def test_youth_defaults_join_date_to_today(client, db_session):
    class_id = _class_id(db_session)
    _student(db_session, "团员默认甲", "C9008")
    created = client.post(
        "/api/v1/youth_members",
        json={"student_name": "团员默认甲"},
        params={"classId": class_id},
    ).json()["data"]
    assert created["join_date"] == date.today().isoformat()
    assert created["post"] == "团员" and created["fee"] == "已缴"


# ---------- 值日：成员子表 ----------


def test_duty_members_are_linked_students(client, db_session):
    """值日成员是学生关联（旧应用是顿号分隔的自由文本，统计不出个人次数）。"""
    class_id = _class_id(db_session)
    _student(db_session, "值日成员甲", "C9009")
    _student(db_session, "值日成员乙", "C9010")
    _student(db_session, "值日组长甲", "C9011")

    created = client.post(
        "/api/v1/duty_groups",
        json={
            "weekday": "星期三",
            "area": "教室地面",
            "group_name": "第1组",
            "members_text": "值日成员甲、值日成员乙",
            "leader_name": "值日组长甲",
        },
        params={"classId": class_id},
    )
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    assert data["weekday_no"] == 3
    assert data["members_text"] == "值日成员甲、值日成员乙"
    assert data["member_count"] == 2
    assert data["leader_name"] == "值日组长甲"

    # 搜索按成员姓名（走的是那列冗余串）
    found = client.get("/api/v1/duty_groups", params={"classId": class_id, "q": "值日成员乙"}).json()
    assert found["meta"]["total"] == 1

    # 改成员：整批覆盖
    updated = client.patch(
        f"/api/v1/duty_groups/{data['id']}",
        json={"members_text": "值日成员乙"},
    ).json()["data"]
    assert updated["members_text"] == "值日成员乙" and updated["member_count"] == 1


def test_duty_rejects_unknown_member_and_area(client, db_session):
    class_id = _class_id(db_session)
    _student(db_session, "值日成员丙", "C9012")

    bad_member = client.post(
        "/api/v1/duty_groups",
        json={"weekday": "星期一", "area": "教室地面", "members_text": "查无此人"},
        params={"classId": class_id},
    )
    assert bad_member.status_code == 400
    assert "查无此人" in bad_member.json()["error"]["message"]

    bad_area = client.post(
        "/api/v1/duty_groups",
        json={"weekday": "星期一", "area": "操场地", "members_text": "值日成员丙"},
        params={"classId": class_id},
    )
    assert bad_area.status_code == 400
    # 词表外的值由字段级校验先拦下（比钩子更早，提示也更具体）
    assert "只能填：教室地面" in bad_area.json()["error"]["message"]


# ---------- 特殊体质与助学金 ----------


def test_health_record_is_one_per_student(client, db_session):
    """一人一条：旧应用可以给同一个人建多条，应急时看到互相矛盾的两条。"""
    class_id = _class_id(db_session)
    _student(db_session, "体质测试甲", "C9013")
    payload = {
        "student_name": "体质测试甲",
        "type": "哮喘",
        "detail": "运动后易发作",
        "emergency": "立即使用随身喷雾并联系家长",
    }
    assert client.post("/api/v1/health_records", json=payload, params={"classId": class_id}).status_code == 201

    again = client.post("/api/v1/health_records", json=payload, params={"classId": class_id})
    assert again.status_code == 400, again.text
    assert "已经有一条特殊体质档案" in again.json()["error"]["message"]
    assert client.get("/api/v1/health_records", params={"classId": class_id}).json()["meta"]["total"] == 1


def test_grant_amount_is_stored_in_cents(client, db_session):
    """金额以分存整数：输入元、库里存分、展示回元 —— 浮点算钱会出现尾数。"""
    class_id = _class_id(db_session)
    _student(db_session, "助学金甲", "C9014")

    created = client.post(
        "/api/v1/grants",
        json={
            "student_name": "助学金甲",
            "type": "国家助学金",
            "amount_cents": "1200.50",
            "semester": "2026学年第一学期",
            "reason": "家庭经济困难",
        },
        params={"classId": class_id},
    ).json()["data"]
    assert created["amount_cents"] == 120050
    assert created["amount_yuan"] == "1200.50"
    assert created["amount_display"] == "1200.50"
    assert created["status"] == "申请中" and created["pending"] is True

    zero = client.post(
        "/api/v1/grants",
        json={
            "student_name": "助学金甲",
            "type": "免学杂费",
            "amount_cents": 0,
            "reason": "减免",
            "semester": "2026学年第一学期",
        },
        params={"classId": class_id},
    ).json()["data"]
    assert zero["amount_display"] == "减免"


def test_grant_rejects_bad_status_and_amount(client, db_session):
    class_id = _class_id(db_session)
    _student(db_session, "助学金乙", "C9015")

    bad_status = client.post(
        "/api/v1/grants",
        json={
            "student_name": "助学金乙",
            "type": "社会捐助",
            "reason": "x",
            "status": "随便写的状态",
        },
        params={"classId": class_id},
    )
    assert bad_status.status_code == 400
    assert "只能填：申请中" in bad_status.json()["error"]["message"]

    bad_amount = client.post(
        "/api/v1/grants",
        json={"student_name": "助学金乙", "type": "社会捐助", "reason": "x", "amount_cents": "一千"},
        params={"classId": class_id},
    )
    assert bad_amount.status_code == 400
    assert "要填数字（元）" in bad_amount.json()["error"]["message"]

    # 金额按元填、库里存分：小数不能丢
    created = client.post(
        "/api/v1/grants",
        json={"student_name": "助学金乙", "type": "社会捐助", "reason": "x", "amount_cents": "1200.50"},
        params={"classId": class_id},
    ).json()["data"]
    assert created["amount_cents"] == 120050
