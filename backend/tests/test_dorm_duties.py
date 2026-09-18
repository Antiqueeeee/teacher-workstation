"""宿舍值日的端到端测试。

旧应用（`:13905`）那三处结构问题的对应用例：
- 房间下拉只是复制了一份选项、**不校验存在** → 能造出指向不存在宿舍的记录；
- 值日人只存姓名 → 学生改名这条记录就与人对不上；
- 星期按 `indexOf` 排序 → 词表里出现没见过的写法就排最前面。
"""

from __future__ import annotations

from sqlalchemy import select

from app.models.class_ import Class
from app.models.dorm import DormRoom
from app.models.student import Student


def _class_id(session) -> int:
    return session.scalar(select(Class.id).where(Class.deleted_at.is_(None)).limit(1))


def _student(session, name: str, sno: str) -> Student:
    student = Student(class_id=_class_id(session), name=name, sno=sno, extra={})
    session.add(student)
    session.commit()
    return student


def _room(client, class_id: int, room_no: str, building: str = "1号楼") -> dict:
    response = client.post(
        "/api/v1/dorm_rooms",
        json={"building": building, "room_no": room_no, "capacity": 6},
        params={"classId": class_id},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _duty(client, class_id: int, **overrides):
    # 值日学生是必填的（一条不知道谁值日的安排没有意义），所以默认给一个真实学生 ——
    # 用例里要先建一个叫「值日学生」的学生（见 _student）
    payload = {"room_no": "203", "weekday": "星期一", "task": "地面清扫", "student_name": "值日学生"}
    payload.update(overrides)
    return client.post("/api/v1/dorm_duties", json=payload, params={"classId": class_id})


def _board(client, class_id: int) -> dict:
    response = client.get("/api/v1/dorms/duties", params={"classId": class_id})
    assert response.status_code == 200, response.text
    return response.json()["data"]


# ---------- 房间必须是已有的 ----------


def test_room_must_exist(client, db_session):
    """房间必须先在「宿舍分布」里存在 —— 旧应用的下拉不校验，能造出不存在的宿舍。"""
    class_id = _class_id(db_session)
    response = _duty(client, class_id, room_no="999")
    assert response.status_code == 400, response.text
    assert "宿舍分布里没有" in response.json()["error"]["message"]
    assert "先到「宿舍分布」" in response.json()["error"]["message"]


def test_ambiguous_room_number_asks_for_the_building(client, db_session):
    class_id = _class_id(db_session)
    _student(db_session, "值日学生", "W9000")
    _room(client, class_id, "601", building="1号楼")
    _room(client, class_id, "601", building="2号楼")

    response = _duty(client, class_id, room_no="601")
    assert response.status_code == 400
    assert "请填上楼栋" in response.json()["error"]["message"]

    ok = _duty(client, class_id, room_no="601", building="2号楼")
    assert ok.status_code == 201, ok.text
    assert ok.json()["data"]["building"] == "2号楼"


# ---------- 星期 ----------


def test_weekday_is_stored_as_an_ordinal_so_sorting_is_right(client, db_session):
    """星期存序号：列表按星期排序时星期一在最前，而不是按汉字码位排。"""
    class_id = _class_id(db_session)
    _student(db_session, "值日学生", "W9000")
    _room(client, class_id, "203")
    for weekday, task in (("星期三", "垃圾清运"), ("星期一", "地面清扫"), ("星期日", "公共走廊")):
        assert _duty(client, class_id, weekday=weekday, task=task).status_code == 201

    rows = client.get("/api/v1/dorm_duties", params={"classId": class_id}).json()["data"]
    assert [row["weekday"] for row in rows] == ["星期一", "星期三", "星期日"]
    assert [row["weekday_no"] for row in rows] == [1, 3, 7]


def test_unknown_weekday_and_task_are_refused(client, db_session):
    class_id = _class_id(db_session)
    _student(db_session, "值日学生", "W9000")
    _room(client, class_id, "203")

    # 词表外星期由**字段级校验**先拦下（比钩子更早，提示也更具体）
    bad_weekday = _duty(client, class_id, weekday="周3")
    assert bad_weekday.status_code == 400
    assert "只能填：星期一" in bad_weekday.json()["error"]["message"]

    bad_task = _duty(client, class_id, task="扫地")
    assert bad_task.status_code == 400
    assert "只能填：地面清扫" in bad_task.json()["error"]["message"]


def test_defaults_are_monday_and_pass(client, db_session):
    class_id = _class_id(db_session)
    _student(db_session, "值日学生", "W9000")
    _room(client, class_id, "203")
    created = client.post(
        "/api/v1/dorm_duties",
        json={"room_no": "203", "task": "地面清扫", "student_name": "值日学生"},
        params={"classId": class_id},
    ).json()["data"]
    assert created["weekday"] == "星期一"
    assert created["result"] == "合格"


# ---------- 学生 ----------


def test_duty_student_is_linked_not_just_a_name(client, db_session):
    """值日人存的是学生引用，学生改名后这条记录仍然指着同一个人。"""
    class_id = _class_id(db_session)
    _room(client, class_id, "203")
    student = _student(db_session, "值日学生甲", "W9001")

    created = _duty(client, class_id, student_name="值日学生甲").json()["data"]
    assert created["student_id"] == student.id

    student.name = "值日学生甲（改名）"
    db_session.commit()

    rows = client.get("/api/v1/dorm_duties", params={"classId": class_id}).json()["data"]
    assert rows[0]["student_id"] == student.id  # 引用没断


def test_unknown_duty_student_is_reported(client, db_session):
    class_id = _class_id(db_session)
    _room(client, class_id, "203")
    response = _duty(client, class_id, student_name="查无此人")
    assert response.status_code == 400
    assert "查无此人" in response.json()["error"]["message"]


# ---------- 看板 ----------


def test_board_groups_by_room_and_weekday(client, db_session):
    """按房间分组、每间房列出 7 天 —— 分组在服务端做（前端分组遇到分页会缺一块）。"""
    class_id = _class_id(db_session)
    _student(db_session, "值日学生", "W9000")
    _room(client, class_id, "203")
    _room(client, class_id, "204")
    _student(db_session, "看板值日甲", "W9002")
    assert _duty(client, class_id, room_no="203", student_name="看板值日甲").status_code == 201
    assert _duty(
        client, class_id, room_no="204", weekday="星期五", task="垃圾清运"
    ).status_code == 201

    board = _board(client, class_id)
    assert board["total"] == 2
    assert board["weekdays"][0] == "星期一"
    assert len(board["tasks"]) == 7

    room = [item for item in board["rooms"] if item["roomNo"] == "203"][0]
    assert room["count"] == 1
    assert len(room["days"]) == 7
    monday = room["days"][0]
    assert monday["weekday"] == "星期一"
    assert monday["items"][0]["studentName"] == "看板值日甲"
    assert room["days"][1]["items"] == []


def test_board_reports_rooms_that_no_longer_exist(client, db_session):
    """房间被删掉之后，它的值日安排要如实列出来，不能静默消失。"""
    from app.db.base import utcnow

    class_id = _class_id(db_session)
    _student(db_session, "值日学生", "W9000")
    room = _room(client, class_id, "205")
    assert _duty(client, class_id, room_no="205").status_code == 201

    db_session.get(DormRoom, room["id"]).deleted_at = utcnow()
    db_session.commit()

    board = _board(client, class_id)
    assert [item for item in board["rooms"] if item["roomNo"] == "205"] == []
    assert board["orphanRooms"] and "205" in board["orphanRooms"][0]
    assert board["total"] == 1  # 记录还在，只是房间没了


# ---------- 导入 ----------


def test_import_preview_refuses_an_unknown_room(client, db_session):
    """导入时房间不存在也要拦下来（预览阶段就报，不用等到提交）。"""
    class_id = _class_id(db_session)
    _room(client, class_id, "203")
    csv_text = "房号,星期,值日任务,值日学生\n888,星期一,地面清扫,某人\n"

    preview = client.post(
        "/api/v1/transfer/import",
        params={"table": "dorm_duties"},
        files={"file": ("d.csv", csv_text.encode("utf-8"), "text/csv")},
    ).json()["data"]
    # 房间是否存在要查库，预览阶段不做（钩子要 DB）——所以这一行是**提交时**被拒的
    values = [row["values"] for row in preview["rows"]]
    response = client.post(
        "/api/v1/transfer/import/commit",
        params={"table": "dorm_duties", "classId": class_id},
        json={"rows": values},
    )
    assert response.status_code == 400
    assert "宿舍分布里没有" in response.json()["error"]["message"]
    assert client.get("/api/v1/dorm_duties", params={"classId": class_id}).json()["meta"]["total"] == 0
