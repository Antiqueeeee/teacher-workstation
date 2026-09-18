"""座位安排的端到端测试。

守的是旧应用那几处确认过的毛病：
- 随机排位**清空备注**（视力/身高的关键信息全丢，`:10700`）；
- 没有「锁定座位」这个概念，想保留的安排挡不住；
- 批量操作**没有任何撤销**（直接整体替换 `DB.data.seats`，`:10704`）；
- 手工新增/编辑不校验行列冲突，造出「网格里看不见、列表里还在」的重复格（`:10792`）。
"""

from __future__ import annotations

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


def _board(client, class_id: int) -> dict:
    response = client.get("/api/v1/seats/board", params={"classId": class_id})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _cell(board: dict, row: int, col: int) -> dict:
    return board["grid"][row - 1][col - 1]


def _seat(client, class_id: int, row: int, col: int, name: str = "", **extra):
    payload = {"row": row, "col": col, "student_name": name}
    payload.update(extra)
    return client.post("/api/v1/seats", json=payload, params={"classId": class_id})


def _plan(client, class_id: int, rows: int, cols: int, rule: str | None = None):
    payload = {"rows": rows, "cols": cols}
    if rule is not None:
        payload["rule"] = rule
    return client.put("/api/v1/seats/plan", json=payload, params={"classId": class_id})


# ---------- 座位表参数 ----------


def test_plan_defaults_and_can_be_changed(client, db_session):
    class_id = _class_id(db_session)
    board = _board(client, class_id)
    assert (board["rows"], board["cols"]) == (8, 6)  # 与旧应用默认一致

    assert _plan(client, class_id, 4, 5, "按身高排").status_code == 200
    board = _board(client, class_id)
    assert (board["rows"], board["cols"]) == (4, 5)
    assert board["rule"] == "按身高排"
    assert board["cells"] == 20


def test_plan_rejects_zero_columns(client, db_session):
    """0 列在旧应用里是允许的（`:10480`），结果是一张空表 + 排位无处可放。"""
    class_id = _class_id(db_session)
    response = _plan(client, class_id, 8, 0)
    assert response.status_code == 400
    assert "列数要在 1–" in response.json()["error"]["message"]


def test_shrinking_plan_refuses_to_strand_seats(client, db_session):
    """缩小座位表会把这些座位挪出格子外 —— 拒绝，并说清是哪些。"""
    class_id = _class_id(db_session)
    _plan(client, class_id, 4, 4)
    _student(db_session, "缩表测试甲", "S9001")
    assert _seat(client, class_id, 4, 4, "缩表测试甲").status_code == 201

    response = _plan(client, class_id, 3, 3)
    assert response.status_code == 400, response.text
    assert "落到格子外面" in response.json()["error"]["message"]
    assert "缩表测试甲" in response.json()["error"]["message"]


# ---------- 位置与冲突 ----------


def test_same_cell_is_refused(client, db_session):
    """同行同列的重复格：旧应用是后写覆盖（网格里看不见、列表里还在）。"""
    class_id = _class_id(db_session)
    _student(db_session, "重复格甲", "S9002")
    _student(db_session, "重复格乙", "S9003")
    assert _seat(client, class_id, 1, 1, "重复格甲").status_code == 201

    response = _seat(client, class_id, 1, 1, "重复格乙")
    assert response.status_code == 400, response.text
    error = response.json()["error"]
    assert error["code"] == "SEAT_TAKEN"
    assert "重复格甲" in error["message"]


def test_one_student_one_seat(client, db_session):
    class_id = _class_id(db_session)
    _student(db_session, "一座测试甲", "S9004")
    assert _seat(client, class_id, 1, 1, "一座测试甲").status_code == 201

    response = _seat(client, class_id, 2, 2, "一座测试甲")
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "SEAT_STUDENT_ALREADY_SEATED"
    assert "1 排 1 列" in error["message"]


def test_position_outside_the_grid_is_refused(client, db_session):
    class_id = _class_id(db_session)
    _plan(client, class_id, 3, 3)
    _student(db_session, "越界测试甲", "S9005")

    response = _seat(client, class_id, 5, 5, "越界测试甲")
    assert response.status_code == 400
    assert "超出座位表" in response.json()["error"]["message"]
    assert "3 排 × 3 列" in response.json()["error"]["message"]


def test_group_is_derived_from_the_column(client, db_session):
    """「组」由列决定，不落库 —— 旧应用存了一份又重算，两处会漂。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "分组测试甲", "S9006")
    created = _seat(client, class_id, 1, 3, "分组测试甲").json()["data"]
    assert created["group"] == "第3组"

    moved = client.patch(
        f"/api/v1/seats/{created['id']}", json={"col": 4}
    ).json()["data"]
    assert moved["group"] == "第4组"  # 改列之后组跟着变
    assert student.id == moved["student_id"]


# ---------- 随机排位 ----------


def test_randomize_returns_everyone_and_keeps_notes_and_locks(client, db_session):
    """随机排位：备注跟着人走、锁定的座位不动 —— 旧应用会把备注清空、没有锁定。"""
    class_id = _class_id(db_session)
    _plan(client, class_id, 3, 3)
    names = [("随机甲", "S9007"), ("随机乙", "S9008"), ("随机丙", "S9009")]
    for index, (name, sno) in enumerate(names, start=1):
        _student(db_session, name, sno)
        assert _seat(client, class_id, index, 1, name).status_code == 201

    # 给「随机甲」备注 + 锁定在 1 排 1 列
    board = _board(client, class_id)
    locked_seat_id = _cell(board, 1, 1)["seatId"]
    client.patch(
        f"/api/v1/seats/{locked_seat_id}",
        json={"note": "近视 500 度，需坐前排", "locked": True},
    )

    result = client.post("/api/v1/seats/randomize", params={"classId": class_id}).json()["data"]
    assert result["placed"] == 2  # 锁定的那个不参与洗牌
    assert result["locked"] == 1

    board = _board(client, class_id)
    assert _cell(board, 1, 1)["studentName"] == "随机甲"          # 锁定座位没动
    assert _cell(board, 1, 1)["note"] == "近视 500 度，需坐前排"    # 备注还在
    assert _cell(board, 1, 1)["locked"] is True

    seated = {
        cell["studentName"]
        for line in board["grid"]
        for cell in line
        if cell["studentName"]
    }
    assert seated == {"随机甲", "随机乙", "随机丙"}  # 一个都没丢
    assert board["unseated"] == []


def test_randomize_adds_rows_when_not_enough_seats(client, db_session):
    """座位不够时自动加排，并如实报出来（旧应用会悄悄把 rows 撑大）。"""
    class_id = _class_id(db_session)
    _plan(client, class_id, 1, 2)
    for index, (name, sno) in enumerate(
        (("加排甲", "S9010"), ("加排乙", "S9011"), ("加排丙", "S9012")), start=1
    ):
        _student(db_session, name, sno)

    result = client.post("/api/v1/seats/randomize", params={"classId": class_id}).json()["data"]
    assert result["addedRows"] == 1
    assert result["rows"] == 2 and result["cols"] == 2
    assert result["placed"] == 3 and result["seated"] == 3


def test_randomize_without_students_says_so(client, db_session):
    class_id = _class_id(db_session)
    response = client.post("/api/v1/seats/randomize", params={"classId": class_id})
    assert response.status_code == 400
    assert "还没有学生" in response.json()["error"]["message"]


# ---------- 轮换 / 交换 / 回退 ----------


def test_shift_wraps_around_and_keeps_notes(client, db_session):
    class_id = _class_id(db_session)
    _plan(client, class_id, 2, 2)
    _student(db_session, "轮换甲", "S9013")
    seat = _seat(client, class_id, 1, 1, "轮换甲", note="靠窗").json()["data"]

    # 往前移一排：1 排 → 回绕到 2 排（第 1 排在最前）
    result = client.post(
        "/api/v1/seats/shift", json={"direction": "up", "step": 1}, params={"classId": class_id}
    ).json()["data"]
    assert result["moved"] == 1

    board = _board(client, class_id)
    moved = _cell(board, 2, 1)
    assert moved["studentName"] == "轮换甲"
    assert moved["note"] == "靠窗"  # 备注跟着走
    # 不断言 seatId 不变：批量操作是「算好位置再删掉重建」，id 不保证沿用
    assert seat["id"] is not None


def test_shift_permutes_a_whole_column(client, db_session):
    """一整列人整体环移 —— 这条才是置换：逐个 UPDATE 会在中途撞唯一约束。

    只有一个座位的用例看不出这个问题（真机上一次 3 人的轮换直接 500）。
    """
    class_id = _class_id(db_session)
    _plan(client, class_id, 3, 1)
    for index, (name, sno) in enumerate(
        (("置换甲", "S9025"), ("置换乙", "S9026"), ("置换丙", "S9027")), start=1
    ):
        _student(db_session, name, sno)
        assert _seat(client, class_id, index, 1, name).status_code == 201

    response = client.post(
        "/api/v1/seats/shift", json={"direction": "up", "step": 1}, params={"classId": class_id}
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["moved"] == 3

    board = response.json()["data"]
    # 往前一排：1 排 → 3 排（回绕），2 排 → 1 排，3 排 → 2 排
    assert _cell(board, 3, 1)["studentName"] == "置换甲"
    assert _cell(board, 1, 1)["studentName"] == "置换乙"
    assert _cell(board, 2, 1)["studentName"] == "置换丙"


def test_shift_steps_around_locked_seats(client, db_session):
    """锁定座位占着格子时，轮换只在剩下的位置之间循环 —— 不能转到人家头上。

    整行取模的写法会撞上唯一约束（实测会 500）：锁定座位不动，而别人被转进了它那一格。
    """
    class_id = _class_id(db_session)
    _plan(client, class_id, 2, 2)
    _student(db_session, "锁定轮换甲", "S9023")
    _student(db_session, "锁定轮换乙", "S9024")

    locked = _seat(client, class_id, 1, 1, "锁定轮换甲", locked=True).json()["data"]
    _seat(client, class_id, 2, 1, "锁定轮换乙")

    response = client.post(
        "/api/v1/seats/shift", json={"direction": "up", "step": 1}, params={"classId": class_id}
    )
    assert response.status_code == 200, response.text
    board = response.json()["data"]

    assert _cell(board, 1, 1)["studentName"] == "锁定轮换甲"  # 锁定座位没动
    assert _cell(board, 1, 1)["locked"] is True
    assert _cell(board, 1, 1)["seatId"] == locked["id"]
    # 另一人只剩 (2,1) 一个可去的格子，转完还在原地
    assert _cell(board, 2, 1)["studentName"] == "锁定轮换乙"


def test_shift_rejects_unknown_direction(client, db_session):
    class_id = _class_id(db_session)
    response = client.post(
        "/api/v1/seats/shift", json={"direction": "斜着"}, params={"classId": class_id}
    )
    assert response.status_code == 400
    assert "方向只能是" in response.json()["error"]["message"]


def test_swap_exchanges_two_seats(client, db_session):
    class_id = _class_id(db_session)
    _plan(client, class_id, 2, 2)
    _student(db_session, "换位甲", "S9014")
    _student(db_session, "换位乙", "S9015")
    first = _seat(client, class_id, 1, 1, "换位甲", note="前排").json()["data"]
    _seat(client, class_id, 1, 2, "换位乙")

    result = client.post(
        "/api/v1/seats/swap",
        json={"seatId": first["id"], "row": 1, "col": 2},
        params={"classId": class_id},
    ).json()["data"]
    assert result["swapped"] is True

    board = _board(client, class_id)
    assert _cell(board, 1, 1)["studentName"] == "换位乙"
    assert _cell(board, 1, 2)["studentName"] == "换位甲"
    assert _cell(board, 1, 2)["note"] == "前排"  # 备注跟人走


def test_swap_into_an_empty_cell_moves(client, db_session):
    class_id = _class_id(db_session)
    _plan(client, class_id, 2, 2)
    _student(db_session, "空位甲", "S9016")
    seat = _seat(client, class_id, 1, 1, "空位甲").json()["data"]

    result = client.post(
        "/api/v1/seats/swap",
        json={"seatId": seat["id"], "row": 2, "col": 2},
        params={"classId": class_id},
    ).json()["data"]
    assert result["swapped"] is False and result["moved"] == 1
    assert _cell(_board(client, class_id), 2, 2)["studentName"] == "空位甲"


def test_batch_operation_can_be_rolled_back_once(client, db_session):
    """批量操作能回退一次 —— 旧应用的随机/轮换都是直接整体替换，做错了没退路。"""
    class_id = _class_id(db_session)
    _plan(client, class_id, 3, 2)
    for index, (name, sno) in enumerate(
        (("回退甲", "S9017"), ("回退乙", "S9018"), ("回退丙", "S9019")), start=1
    ):
        _student(db_session, name, sno)
        _seat(client, class_id, index, 1, name)

    before = {
        cell["studentName"]
        for line in _board(client, class_id)["grid"]
        for cell in line
        if cell["studentName"]
    }

    client.post("/api/v1/seats/randomize", params={"classId": class_id})
    assert _board(client, class_id)["canRestore"] is True

    restored = client.post("/api/v1/seats/restore", params={"classId": class_id}).json()["data"]
    assert restored["restored"] == 3
    after = {
        cell["studentName"]
        for line in restored["grid"]
        for cell in line
        if cell["studentName"]
    }
    assert after == before
    assert restored["canRestore"] is False  # 回退只能用一次


def test_restore_without_snapshot_says_so(client, db_session):
    class_id = _class_id(db_session)
    response = client.post("/api/v1/seats/restore", params={"classId": class_id})
    assert response.status_code == 404
    assert "没有可回退的快照" in response.json()["error"]["message"]


def test_clear_removes_seats_but_keeps_the_plan(client, db_session):
    class_id = _class_id(db_session)
    _plan(client, class_id, 4, 4)
    _student(db_session, "清空座位甲", "S9020")
    _seat(client, class_id, 1, 1, "清空座位甲")

    result = client.post("/api/v1/seats/clear", params={"classId": class_id}).json()["data"]
    assert result["removed"] == 1
    assert result["seated"] == 0
    assert (result["rows"], result["cols"]) == (4, 4)  # 座位表参数留着

    # 清空也能回退
    back = client.post("/api/v1/seats/restore", params={"classId": class_id}).json()["data"]
    assert back["seated"] == 1


# ---------- 看板 ----------


def test_board_lists_cells_and_unseated_students(client, db_session):
    class_id = _class_id(db_session)
    _plan(client, class_id, 2, 2)
    _student(db_session, "看板座位甲", "S9021")
    _student(db_session, "看板座位乙", "S9022")
    _seat(client, class_id, 1, 1, "看板座位甲")

    board = _board(client, class_id)
    assert len(board["grid"]) == 2 and len(board["grid"][0]) == 2
    assert board["seated"] == 1
    assert [item["studentName"] for item in board["unseated"]] == ["看板座位乙"]

    empty = _cell(board, 1, 2)
    assert empty["seatId"] is None and empty["studentName"] == ""
    assert empty["group"] == "第2组"


def test_unknown_student_is_reported(client, db_session):
    class_id = _class_id(db_session)
    response = _seat(client, class_id, 1, 1, "座位查无此人")
    assert response.status_code == 400
    assert "座位查无此人" in response.json()["error"]["message"]


# ---------- 软删除与唯一约束（评审实测的三条 500） ----------


def test_a_cleared_seat_can_be_used_again(client, db_session):
    """腾空座位就是删掉那一行 —— 腾空过的格子必须能再排人。

    座位原来是软删除的，而 `UNIQUE(class_id,row,col)` 不带 `deleted_at` 条件，
    于是幽灵行占着格子：再排人直接 500。同类问题还有「同一个学生腾空后换位置」
    （学生唯一索引也把幽灵行算进去）。现在座位不软删，这两个入口都能用。
    """
    class_id = _class_id(db_session)
    _plan(client, class_id, 2, 2)
    _student(db_session, "腾空重排甲", "S9030")
    _student(db_session, "腾空重排乙", "S9031")
    first = _seat(client, class_id, 1, 1, "腾空重排甲").json()["data"]

    assert client.delete(f"/api/v1/seats/{first['id']}").status_code == 200
    again = _seat(client, class_id, 1, 1, "腾空重排乙")
    assert again.status_code == 201, again.text
    assert _cell(_board(client, class_id), 1, 1)["studentName"] == "腾空重排乙"


def test_a_student_can_move_after_their_seat_was_cleared(client, db_session):
    class_id = _class_id(db_session)
    _plan(client, class_id, 2, 2)
    _student(db_session, "腾空换位甲", "S9032")
    first = _seat(client, class_id, 1, 1, "腾空换位甲").json()["data"]

    assert client.delete(f"/api/v1/seats/{first['id']}").status_code == 200
    moved = _seat(client, class_id, 2, 2, "腾空换位甲")
    assert moved.status_code == 201, moved.text
    assert _cell(_board(client, class_id), 2, 2)["studentName"] == "腾空换位甲"


def test_restore_brings_back_the_plan_size_too(client, db_session):
    """回退要把座位表大小一起还原 —— 只还原座位会把人放到格子外面。

    「批量操作 → 把表改小 → 回退」这条路径下，旧写法会把座位还原到 rows 之外，
    那个人既不显示在网格里、也不在「未排座」名单里（评审实测第三人找不到）。
    """
    class_id = _class_id(db_session)
    _plan(client, class_id, 2, 2)
    _student(db_session, "回退缩表甲", "S9033")
    _student(db_session, "回退缩表乙", "S9034")
    _seat(client, class_id, 1, 1, "回退缩表甲")
    _seat(client, class_id, 2, 1, "回退缩表乙")

    # 批量操作先存快照（此刻是 2 排 × 2 列、两个人）
    assert client.post(
        "/api/v1/seats/shift", json={"direction": "up", "step": 1}, params={"classId": class_id}
    ).status_code == 200

    # 删掉 2 排那个座位（轮换是删掉重建，id 会变，所以从看板上现取），
    # 然后把表缩到 1 排（此刻没有座位在格子外，所以放行）
    row_two = _cell(_board(client, class_id), 2, 1)["seatId"]
    assert client.delete(f"/api/v1/seats/{row_two}").status_code == 200
    assert _plan(client, class_id, 1, 2).status_code == 200

    restored = client.post("/api/v1/seats/restore", params={"classId": class_id}).json()["data"]
    assert restored["rows"] == 2  # 座位表大小跟着还原
    assert restored["seated"] == 2
    seated = {
        cell["studentName"]
        for line in restored["grid"]
        for cell in line
        if cell["studentName"]
    }
    assert seated == {"回退缩表甲", "回退缩表乙"}
    assert restored["unseated"] == []


def test_shift_reports_seats_that_fall_outside_the_grid(client, db_session):
    """座位落在表格外（只可能来自手工改库）时报清楚，而不是 KeyError 500。"""
    from app.models.seat import Seat

    class_id = _class_id(db_session)
    _plan(client, class_id, 2, 2)
    _student(db_session, "越界座位甲", "S9035")
    student_id = db_session.scalar(select(Student.id).where(Student.name == "越界座位甲"))
    db_session.add(Seat(class_id=class_id, row=5, col=1, student_id=student_id, student_name="越界座位甲"))
    db_session.commit()

    response = client.post(
        "/api/v1/seats/shift", json={"direction": "up", "step": 1}, params={"classId": class_id}
    )
    assert response.status_code == 400, response.text
    assert "落在座位表外面" in response.json()["error"]["message"]
