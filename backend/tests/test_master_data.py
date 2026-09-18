"""学生主数据与监护人的服务级测试。

学生档案的 HTTP 接口在下一批做，这里先守两条最要紧的：
1. **字段定义是从旧应用真实模板播种的**（含 Excel 别名）—— 别名对不上，真实表格就进不来；
2. **监护人必须挂到真实学生身上** —— 老师填的是姓名，程序要的是 id，
   这个转换只能有一处，且重名必须报错而不是随便挑一个。
"""

from __future__ import annotations

from sqlalchemy import select

from app.models.class_ import Class
from app.models.student import Student, StudentFieldDef
from app.services.student_fields import MOVED_TO_GUARDIAN, seed_field_defs

# 旧应用默认模板 24 条，其中 4 条（父母姓名/电话）挪到了监护人表
EXPECTED_FIELD_COUNT = 24 - len(MOVED_TO_GUARDIAN)


def _default_class_id(session) -> int:
    return session.scalar(select(Class.id).where(Class.deleted_at.is_(None)).limit(1))


def _make_student(session, class_id: int, name: str, sno: str = "", **extra) -> Student:
    student = Student(class_id=class_id, name=name, sno=sno, extra=extra)
    session.add(student)
    session.commit()
    return student


# --------------------------------------------------------------------------- 字段定义


def test_field_defs_are_seeded_from_the_real_template(db_session):
    seed_field_defs(db_session)
    db_session.commit()
    defs = {row.key: row for row in db_session.scalars(select(StudentFieldDef))}

    assert len(defs) == EXPECTED_FIELD_COUNT
    # 别名来自旧应用的真实定义（`syn`），导入认列名全靠它
    assert "学籍号" in defs["sno"].aliases
    assert "生日" in defs["birth"].aliases
    # 姓名/学号是身份字段，不允许被删掉
    assert defs["name"].identity and defs["sno"].identity
    # 挪到监护人表的字段不该再出现在学生档案里（旧应用两处都存，是同一件事两份数据）
    assert not (MOVED_TO_GUARDIAN & set(defs))


def test_seeding_is_idempotent(db_session):
    # 启动时已经播过种，再调一次不该新增
    assert seed_field_defs(db_session) == 0
    db_session.commit()


def test_field_defs_keep_real_options(db_session):
    seed_field_defs(db_session)
    db_session.commit()
    boarding = db_session.scalar(select(StudentFieldDef).where(StudentFieldDef.key == "boarding"))
    assert "住校" in boarding.options and "走读" in boarding.options


# --------------------------------------------------------------------------- 监护人


def test_guardian_resolves_student_by_name(client, db_session):
    class_id = _default_class_id(db_session)
    _make_student(db_session, class_id, "监护人解析测试", sno="T9001")

    created = client.post(
        "/api/v1/guardians",
        json={"student_name": "监护人解析测试", "name": "测试父亲", "role": "父亲", "phone": "13800000000"},
    )
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    assert data["student_id"] > 0
    assert data["class_id"] == class_id  # 班级是从学生带出来的，不是让前端传的


def test_guardian_rejects_unknown_student(client):
    response = client.post("/api/v1/guardians", json={"student_name": "查无此人X", "name": "某家长"})
    assert response.status_code == 400
    message = response.json()["error"]["message"]
    assert "没有叫" in message  # 提示要能指向解决办法（先去学生档案里加人）


def test_guardian_rejects_ambiguous_name(client, db_session):
    class_id = _default_class_id(db_session)
    _make_student(db_session, class_id, "重名测试甲")
    _make_student(db_session, class_id, "重名测试甲")

    response = client.post("/api/v1/guardians", json={"student_name": "重名测试甲", "name": "某家长"})
    assert response.status_code == 400
    # 会议里点过「有重名」这个现实问题 —— 静默挂到同名学生身上比报错糟糕得多
    assert "都叫" in response.json()["error"]["message"]


def test_guardian_import_uses_the_same_hook(client, db_session):
    """导入走的是同一个保存前钩子，不是另一套逻辑。"""
    class_id = _default_class_id(db_session)
    _make_student(db_session, class_id, "导入监护人测试", sno="T9002")

    csv_text = "学生,监护人姓名,关系,电话\n导入监护人测试,测试母亲,母亲,13900000000\n"
    preview = client.post(
        "/api/v1/transfer/import",
        params={"table": "guardians"},
        files={"file": ("g.csv", csv_text.encode("utf-8"), "text/csv")},
    ).json()["data"]
    assert preview["summary"]["problem"] == 0, preview

    rows = [row["values"] for row in preview["rows"]]
    committed = client.post(
        "/api/v1/transfer/import/commit", params={"table": "guardians"}, json={"rows": rows}
    ).json()["data"]
    assert committed["created"] == 1

    listed = client.get("/api/v1/guardians", params={"q": "导入监护人测试"}).json()["data"]
    assert listed[0]["student_id"] > 0
    assert listed[0]["class_id"] == class_id


def test_guardian_import_fails_cleanly_for_unknown_student(client):
    """钩子抛错时整批回滚，不留半批数据。"""
    rows = [{"student_name": "导入查无此人", "name": "某家长", "role": "其他"}]
    response = client.post(
        "/api/v1/transfer/import/commit", params={"table": "guardians"}, json={"rows": rows}
    )
    assert response.status_code == 400
    assert client.get("/api/v1/guardians", params={"q": "导入查无此人"}).json()["meta"]["total"] == 0
