"""成绩口径的端到端测试。

守住的是旧应用那几处确认过的错：
- 名次按数组顺序给（同分不同名次）；
- 及格线用「全部科目并集满分」，某场只考 3 科时全班都不及格；
- 空值当 0 分，缺考与考 0 分分不出来；
- 名次/总分是持久化字段，改了满分设置不重算。

这些用例在改造前都会失败 —— 不是形式上的断言，是那几处错的复现。
"""

from __future__ import annotations

from sqlalchemy import select

from app.models.class_ import Class
from app.models.exam import Score
from app.models.student import Student
from app.models.vocab import SUBJECTS


def _class_id(session) -> int:
    return session.scalar(select(Class.id).where(Class.deleted_at.is_(None)).limit(1))


def _student(session, name: str, sno: str) -> Student:
    student = Student(class_id=_class_id(session), name=name, sno=sno, extra={})
    session.add(student)
    session.commit()
    return student


def _exam(client, class_id: int, *, name: str, date: str, kind: str = "月考") -> dict:
    response = client.post(
        "/api/v1/exams",
        json={"name": name, "date": date, "kind": kind},
        params={"classId": class_id},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _subjects(client, exam_id: int, items: list[tuple[str, int]]):
    return client.put(
        f"/api/v1/exams/{exam_id}/subjects",
        json={"subjects": [{"subject": s, "fullMarks": f} for s, f in items]},
    )


def _cells(client, exam_id: int, cells: list[dict]):
    return client.put(f"/api/v1/exams/{exam_id}/sheet", json={"cells": cells})


def _report(client, exam_id: int) -> dict:
    response = client.get(f"/api/v1/exams/{exam_id}/report")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _row(report: dict, student: Student) -> dict:
    match = [row for row in report["rows"] if row["studentId"] == student.id]
    assert match, f"报表里没有 {student.name}"
    return match[0]


def _three_subjects() -> list[tuple[str, int]]:
    # 语数英，各 150：本场满分 450（旧应用会拿全部 9 科的 1350 当分母）
    return [("语文", 150), ("数学", 150), ("英语", 150)]


# ---------- 考试与科目 ----------


def test_new_exam_gets_all_subjects_with_default_full_marks(client, db_session):
    exam = _exam(client, _class_id(db_session), name="科目默认测试", date="2026-06-01")
    sheet = client.get(f"/api/v1/exams/{exam['id']}/sheet").json()["data"]
    full = {item["subject"]: item["fullMarks"] for item in sheet["subjects"]}

    assert len(full) == 9  # 词表里的 9 科，老师再按实际删减
    assert full["语文"] == 150 and full["数学"] == 150 and full["英语"] == 150
    assert full["地理"] == 100


def test_sheet_lists_all_selectable_subjects(client, db_session):
    """录入表要一并给出**全部可选科目**：界面上的「科目与满分」靠它把删掉的科目加回来。

    前端不自己维护一份科目词表 —— 这里少一个字段，那边就只能硬编码，
    然后两份词表迟早对不上（「作业里能选地理、成绩里选不到」就是这么来的）。
    """
    exam = _exam(client, _class_id(db_session), name="可选科目测试", date="2026-06-20")
    assert _subjects(client, exam["id"], [("语文", 150)]).status_code == 200

    sheet = client.get(f"/api/v1/exams/{exam['id']}/sheet").json()["data"]
    assert sheet["allSubjects"] == list(SUBJECTS)
    assert [item["subject"] for item in sheet["subjects"]] == ["语文"]


def test_pass_line_uses_this_exam_subjects_only(client, db_session):
    """某场只考 3 科时，及格线按这 3 科的满分算 —— 旧应用按全科并集算，全班都不及格。"""
    exam = _exam(client, _class_id(db_session), name="三科及格线测试", date="2026-06-02")
    assert _subjects(client, exam["id"], _three_subjects()).status_code == 200
    good = _student(db_session, "及格线测试甲", "E9001")
    weak = _student(db_session, "及格线测试乙", "E9002")

    _cells(
        client,
        exam["id"],
        [
            {"studentId": good.id, "subject": "语文", "value": 100},
            {"studentId": good.id, "subject": "数学", "value": 100},
            {"studentId": good.id, "subject": "英语", "value": 80},
            {"studentId": weak.id, "subject": "语文", "value": 90},
            {"studentId": weak.id, "subject": "数学", "value": 90},
            {"studentId": weak.id, "subject": "英语", "value": 70},
        ],
    )
    report = _report(client, exam["id"])

    assert report["fullTotal"] == 450  # 不是 1350
    assert _row(report, good)["passed"] is True    # 280 / 450 = 62.2%
    assert _row(report, weak)["passed"] is False   # 250 / 450 = 55.6%


def test_removing_a_subject_with_scores_is_refused(client, db_session):
    exam = _exam(client, _class_id(db_session), name="移科目测试", date="2026-06-03")
    student = _student(db_session, "移科目测试甲", "E9003")
    _cells(client, exam["id"], [{"studentId": student.id, "subject": "地理", "value": 80}])

    response = _subjects(client, exam["id"], [("语文", 150), ("数学", 150)])
    assert response.status_code == 400, response.text
    assert "地理 1 条" in response.json()["error"]["message"]

    # 拒绝之后科目没有被删掉，成绩也还在
    sheet = client.get(f"/api/v1/exams/{exam['id']}/sheet").json()["data"]
    assert "地理" in [item["subject"] for item in sheet["subjects"]]


def test_bad_full_marks_is_rejected(client, db_session):
    exam = _exam(client, _class_id(db_session), name="满分校验测试", date="2026-06-04")
    response = _subjects(client, exam["id"], [("语文", 0)])
    assert response.status_code == 400
    assert "满分" in response.json()["error"]["message"]


# ---------- 名次与缺考 ----------


def test_ties_share_the_same_rank(client, db_session):
    """同分并列：1, 2, 2, 4 —— 旧应用按数组顺序给，同一份数据换个顺序名次就变。"""
    exam = _exam(client, _class_id(db_session), name="并列名次测试", date="2026-06-05")
    assert _subjects(client, exam["id"], _three_subjects()).status_code == 200
    first = _student(db_session, "并列名次甲", "E9004")
    tie_a = _student(db_session, "并列名次乙", "E9005")
    tie_b = _student(db_session, "并列名次丙", "E9006")
    last = _student(db_session, "并列名次丁", "E9007")

    _cells(
        client,
        exam["id"],
        [
            {"studentId": first.id, "subject": "语文", "value": 140},
            {"studentId": tie_a.id, "subject": "语文", "value": 130},
            {"studentId": tie_b.id, "subject": "语文", "value": 130},
            {"studentId": last.id, "subject": "语文", "value": 120},
        ],
    )
    report = _report(client, exam["id"])

    assert _row(report, first)["rank"] == 1
    assert _row(report, tie_a)["rank"] == 2
    assert _row(report, tie_b)["rank"] == 2
    assert _row(report, last)["rank"] == 4  # 跳过被并列占掉的第 3 名
    assert _row(report, tie_a)["tied"] is True
    assert _row(report, first)["tied"] is False


def test_absent_does_not_count_as_zero(client, db_session):
    """缺考：不计总分、不当 0 分，但这场考试仍然算他应考。"""
    exam = _exam(client, _class_id(db_session), name="缺考测试", date="2026-06-06")
    assert _subjects(client, exam["id"], _three_subjects()).status_code == 200
    student = _student(db_session, "缺考测试甲", "E9008")

    _cells(
        client,
        exam["id"],
        [
            {"studentId": student.id, "subject": "语文", "value": None, "absent": True},
            {"studentId": student.id, "subject": "数学", "value": 150},
            {"studentId": student.id, "subject": "英语", "value": 150},
        ],
    )
    report = _report(client, exam["id"])
    row = _row(report, student)

    assert row["absent"] == ["语文"]
    assert "语文" not in row["values"]
    assert row["total"] == 300             # 不是 0 + 150 + 150 之外的别的算法
    assert row["attemptedFull"] == 300     # 缺考那科不计入应考满分
    assert row["scoreRate"] == 100.0
    assert row["passed"] is True           # 旧应用会拿 450 当分母判他不合格
    assert row["missing"] == []


def test_unrecorded_is_not_zero_either(client, db_session):
    """一科都没录的学生单独报出来，而不是当 0 分排在最后。"""
    exam = _exam(client, _class_id(db_session), name="未录测试", date="2026-06-07")
    assert _subjects(client, exam["id"], _three_subjects()).status_code == 200
    graded = _student(db_session, "未录测试甲", "E9009")
    unrecorded = _student(db_session, "未录测试乙", "E9010")

    _cells(client, exam["id"], [{"studentId": graded.id, "subject": "语文", "value": 100}])
    report = _report(client, exam["id"])

    row = _row(report, unrecorded)
    assert row["values"] == {} and row["absent"] == []
    assert row["missing"] == ["语文", "数学", "英语"]
    assert row["rank"] is None           # 没参加的人不排名
    assert row["total"] == 0
    assert row["scoreRate"] is None      # 「没考」不是 0%
    assert row["passed"] is False

    assert report["taken"] == 1                      # 实考只有 1 人
    assert report["unrecordedStudents"] == 1         # 还没录到他，界面要能说出来（用例级清理保证了人数精确）
    assert report["avgTotal"] == 100.0               # 没录的不拉低平均分


def test_fully_absent_student_counts_in_expected(client, db_session):
    """缺考全部科目：计入应考人数，但不计入实考与平均分。"""
    exam = _exam(client, _class_id(db_session), name="全缺考测试", date="2026-06-08")
    assert _subjects(client, exam["id"], _three_subjects()).status_code == 200
    present = _student(db_session, "全缺考甲", "E9011")
    away = _student(db_session, "全缺考乙", "E9012")

    _cells(
        client,
        exam["id"],
        [
            {"studentId": present.id, "subject": "语文", "value": 120},
            *[
                {"studentId": away.id, "subject": subject, "value": None, "absent": True}
                for subject in ("语文", "数学", "英语")
            ],
        ],
    )
    report = _report(client, exam["id"])

    assert _row(report, away)["rank"] is None
    assert report["taken"] == 1
    assert report["absentStudents"] == 1
    assert report["avgTotal"] == 120.0


# ---------- 改满分：不需要「重算」 ----------


def test_changing_full_marks_takes_effect_immediately(client, db_session):
    """名次与统计不落库，所以改满分立刻生效，不存在「忘了重算」这回事。"""
    exam = _exam(client, _class_id(db_session), name="改满分测试", date="2026-06-09")
    assert _subjects(client, exam["id"], _three_subjects()).status_code == 200
    student = _student(db_session, "改满分测试甲", "E9013")
    _cells(client, exam["id"], [{"studentId": student.id, "subject": "语文", "value": 135}])

    before = _report(client, exam["id"])
    assert _row(before, student)["passed"] is True    # 135 / 450 → 单科 90% 及格

    # 把这场考试的语文满分改成 150 → 不动；改成 300 则这一科不再及格
    assert _subjects(
        client, exam["id"], [("语文", 300), ("数学", 150), ("英语", 150)]
    ).status_code == 200
    after = _report(client, exam["id"])

    subject = [item for item in after["subjects"] if item["subject"] == "语文"][0]
    assert subject["fullMarks"] == 300
    assert subject["rate"] == 45.0       # 135 / 300
    assert subject["passRate"] == 0.0
    assert _row(after, student)["passed"] is False   # 135 / 600 → 22.5%


def test_rank_and_total_are_not_stored(client, db_session):
    """结构上的保证：成绩行里没有 rank/total 列，也就没机会过期。"""
    columns = set(Score.__table__.columns.keys())
    assert "rank" not in columns
    assert "total" not in columns


# ---------- 录入表的校验 ----------


def test_cell_above_full_marks_is_rejected(client, db_session):
    exam = _exam(client, _class_id(db_session), name="超分测试", date="2026-06-10")
    assert _subjects(client, exam["id"], [("地理", 100)]).status_code == 200
    student = _student(db_session, "超分测试甲", "E9014")

    response = _cells(client, exam["id"], [{"studentId": student.id, "subject": "地理", "value": 120}])
    assert response.status_code == 400
    assert "0–100" in response.json()["error"]["message"]


def test_absent_with_a_score_is_rejected(client, db_session):
    exam = _exam(client, _class_id(db_session), name="缺考冲突测试", date="2026-06-11")
    student = _student(db_session, "缺考冲突甲", "E9015")

    response = _cells(
        client,
        exam["id"],
        [{"studentId": student.id, "subject": "语文", "value": 100, "absent": True}],
    )
    assert response.status_code == 400
    assert "缺考" in response.json()["error"]["message"]


def test_subject_outside_the_exam_is_rejected(client, db_session):
    exam = _exam(client, _class_id(db_session), name="科目不符测试", date="2026-06-12")
    assert _subjects(client, exam["id"], [("语文", 150)]).status_code == 200
    student = _student(db_session, "科目不符甲", "E9016")

    response = _cells(client, exam["id"], [{"studentId": student.id, "subject": "数学", "value": 100}])
    assert response.status_code == 400
    assert "不在本场考试" in response.json()["error"]["message"]


def test_clearing_a_cell_deletes_the_row(client, db_session):
    """value=null + not absent 表示「这一格清掉」，与「缺考」是两件事。"""
    exam = _exam(client, _class_id(db_session), name="清格测试", date="2026-06-13")
    student = _student(db_session, "清格测试甲", "E9017")
    _cells(client, exam["id"], [{"studentId": student.id, "subject": "语文", "value": 100}])

    result = _cells(
        client, exam["id"], [{"studentId": student.id, "subject": "语文", "value": None}]
    ).json()["data"]
    assert result["changes"]["removed"] == 1

    row = _row(_report(client, exam["id"]), student)
    assert row["values"] == {}
    assert row["missing"] == [item["subject"] for item in _report(client, exam["id"])["subjects"]]


def test_saving_the_same_cell_twice_updates_instead_of_duplicating(client, db_session):
    exam = _exam(client, _class_id(db_session), name="重复录入测试", date="2026-06-14")
    student = _student(db_session, "重复录入甲", "E9018")

    _cells(client, exam["id"], [{"studentId": student.id, "subject": "语文", "value": 100}])
    result = _cells(
        client, exam["id"], [{"studentId": student.id, "subject": "语文", "value": 120}]
    ).json()["data"]

    assert result["changes"] == {"created": 0, "updated": 1, "removed": 0}
    saved = db_session.scalars(select(Score).where(Score.exam_id == exam["id"])).all()
    assert len(saved) == 1  # 没有多出第二行（唯一约束 + 按格更新）
    assert saved[0].value == 120


def test_same_cell_twice_in_one_submission_uses_the_last_value(client, db_session):
    """同一次提交里同一格出现两次：按后面的为准，不是 500。

    不去重的话第二次会走「新增」分支撞上唯一约束 —— 用户看到的是
    「服务内部错误：IntegrityError」，既看不懂也没法自己解决。
    """
    exam = _exam(client, _class_id(db_session), name="同批重复格测试", date="2026-06-21")
    student = _student(db_session, "同批重复格甲", "E9022")

    response = _cells(
        client,
        exam["id"],
        [
            {"studentId": student.id, "subject": "语文", "value": 100},
            {"studentId": student.id, "subject": "语文", "value": 130},
        ],
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["changes"] == {"created": 1, "updated": 0, "removed": 0}

    saved = db_session.scalars(select(Score).where(Score.exam_id == exam["id"])).all()
    assert len(saved) == 1
    assert saved[0].value == 130


def test_absent_flag_accepts_chinese_and_string_false(client, db_session):
    """`absent` 传来字符串 "否"/"false"/"0" 时是「不是缺考」—— `bool("否")` 是 True。"""
    exam = _exam(client, _class_id(db_session), name="缺考标志解析测试", date="2026-06-22")
    student = _student(db_session, "缺考标志甲", "E9023")

    response = _cells(
        client,
        exam["id"],
        [{"studentId": student.id, "subject": "语文", "value": 100, "absent": "否"}],
    )
    assert response.status_code == 200, response.text
    row = _row(_report(client, exam["id"]), student)
    assert row["values"] == {"语文": 100.0}
    assert row["absent"] == []


# ---------- 与上一场对比 ----------


def test_report_compares_with_the_previous_exam(client, db_session):
    class_id = _class_id(db_session)
    student = _student(db_session, "对比测试甲", "E9019")
    older = _exam(client, class_id, name="对比测试上一场", date="2026-06-15")
    newer = _exam(client, class_id, name="对比测试本场", date="2026-06-16")
    for exam in (older, newer):
        assert _subjects(client, exam["id"], _three_subjects()).status_code == 200

    _cells(client, older["id"], [{"studentId": student.id, "subject": "语文", "value": 100}])
    _cells(client, newer["id"], [{"studentId": student.id, "subject": "语文", "value": 130}])

    report = _report(client, newer["id"])
    row = _row(report, student)
    assert report["previous"]["examId"] == older["id"]
    assert row["prevTotal"] == 100
    assert row["prevRank"] == 1
    assert row["total"] == 130


def test_previous_exam_is_picked_by_date_not_insertion_order(client, db_session):
    """同一天的上一场按 id 判定，顺序永远确定 —— 旧应用按存储顺序取，取到的是更早那场。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "顺序测试甲", "E9020")
    first = _exam(client, class_id, name="顺序测试第一场", date="2026-06-17")
    second = _exam(client, class_id, name="顺序测试第二场", date="2026-06-17")
    third = _exam(client, class_id, name="顺序测试第三场", date="2026-06-18")
    for exam in (first, second, third):
        assert _subjects(client, exam["id"], _three_subjects()).status_code == 200

    _cells(client, first["id"], [{"studentId": student.id, "subject": "语文", "value": 100}])
    _cells(client, second["id"], [{"studentId": student.id, "subject": "语文", "value": 110}])
    _cells(client, third["id"], [{"studentId": student.id, "subject": "语文", "value": 120}])

    report = _report(client, third["id"])
    assert report["previous"]["examId"] == second["id"]
    assert _row(report, student)["prevTotal"] == 110


# ---------- 其他 ----------


def test_clear_scores_keeps_the_exam(client, db_session):
    exam = _exam(client, _class_id(db_session), name="清场测试", date="2026-06-19")
    student = _student(db_session, "清场测试甲", "E9021")
    _cells(client, exam["id"], [{"studentId": student.id, "subject": "语文", "value": 100}])

    result = client.post(f"/api/v1/exams/{exam['id']}/clear-scores").json()["data"]
    assert result["removed"] == 1
    assert client.get(f"/api/v1/exams/{exam['id']}").status_code == 200  # 考试还在


def test_missing_exam_reports_not_found(client):
    response = client.get("/api/v1/exams/999999/report")
    assert response.status_code == 404
    assert "不存在" in response.json()["error"]["message"]
