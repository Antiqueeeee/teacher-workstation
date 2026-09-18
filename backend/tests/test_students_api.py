"""学生档案 HTTP 接口的端到端测试。

重点守两件在旧应用里出过问题的事：

1. **字段是数据，不是代码** —— 老师加一个字段，接口立刻就能用（不必重启服务）；
   删掉定义**数据还在**（界面上就是这么承诺的，不能是空话）；
2. **导入认的是真实别名** —— 老师表格里写「学籍号 / 生日 / 手机号」也要认出来，
   而不是要求他先把表头改成我们想要的样子。
"""

from __future__ import annotations

import io

from openpyxl import load_workbook


def test_schema_is_built_from_field_defs(client):
    spec = client.get("/api/v1/students/schema").json()["data"]
    assert spec["key"] == "students"
    assert spec["title"] == "学生档案"
    assert spec["classScoped"] is True

    defs = {item["key"] for item in client.get("/api/v1/students/fields").json()["data"]}
    assert set(column["k"] for column in spec["columns"]) <= defs
    # 姓名必须填；学号允许为空（转学生可能还没有学籍号）
    fields = {field["k"]: field for field in spec["fields"]}
    assert fields["name"]["required"] is True
    assert fields["sno"]["required"] is False


def test_create_and_read_dynamic_fields(client):
    created = client.post(
        "/api/v1/students",
        json={"name": "动态字段测试", "sno": "D9001", "gender": "男", "boarding": "住校", "native": "本市城区"},
    )
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    assert data["gender"] == "男"  # 存在 extra JSON 里，照样原样返回
    assert data["boarding"] == "住校"

    listed = client.get("/api/v1/students", params={"q": "动态字段测试"}).json()
    assert listed["meta"]["total"] == 1
    assert listed["data"][0]["native"] == "本市城区"


def test_filter_and_sort_work_on_dynamic_fields(client):
    client.post("/api/v1/students", json={"name": "动态筛选甲", "sno": "D9002", "boarding": "走读"})
    client.post("/api/v1/students", json={"name": "动态筛选乙", "sno": "D9003", "boarding": "住校"})

    filtered = client.get("/api/v1/students", params={"q": "动态筛选", "filter.boarding": "走读"}).json()
    assert filtered["meta"]["total"] == 1
    assert filtered["data"][0]["name"] == "动态筛选甲"

    ordered = client.get(
        "/api/v1/students", params={"q": "动态筛选", "sort": "boarding", "dir": "asc"}
    ).json()["data"]
    assert [row["boarding"] for row in ordered] == ["住校", "走读"]


def test_duplicate_sno_gets_a_readable_error(client):
    client.post("/api/v1/students", json={"name": "学号重复甲", "sno": "D9004"})
    response = client.post("/api/v1/students", json={"name": "学号重复乙", "sno": "D9004"})
    assert response.status_code == 400
    # 数据库有唯一索引兜底，但不能让老师看到 IntegrityError
    assert "学号" in response.json()["error"]["message"]


def test_stats_can_group_by_dynamic_fields(client):
    """统计的分组也必须走 json_extract。

    曾经这里用 `getattr(model, key)` 取字段 —— 普通列没问题，
    学生档案的 JSON 字段直接 AttributeError。而「统计」和「列表」不同源，
    正是这个项目反复要避免的形状。
    """
    client.post("/api/v1/students", json={"name": "统计分组测试", "sno": "D9008", "boarding": "住校"})
    stats = client.get("/api/v1/students/stats", params={"q": "统计分组测试"}).json()["data"]
    assert stats["total"] == 1
    assert stats["groups"]["boarding"] == {"住校": 1}


def test_import_accepts_real_aliases(client):
    csv_text = "学籍号,姓名,生日,住宿,手机号\nD9005,别名导入测试,2008-05-06,住校,13800001111\n"
    preview = client.post(
        "/api/v1/transfer/import",
        params={"table": "students"},
        files={"file": ("s.csv", csv_text.encode("utf-8"), "text/csv")},
    ).json()["data"]

    assert preview["missingColumns"] == []
    assert preview["summary"]["problem"] == 0, preview
    assert preview["mapping"]["sno"] == "学籍号"  # 别名来自旧应用的真实定义
    assert preview["mapping"]["birth"] == "生日"

    rows = [row["values"] for row in preview["rows"]]
    committed = client.post(
        "/api/v1/transfer/import/commit", params={"table": "students"}, json={"rows": rows}
    ).json()["data"]
    assert committed["created"] == 1

    saved = client.get("/api/v1/students", params={"q": "别名导入测试"}).json()["data"][0]
    assert saved["sno"] == "D9005"
    assert saved["boarding"] == "住校"


def test_export_uses_field_labels(client):
    response = client.get("/api/v1/transfer/export/students.xlsx", params={"q": "动态字段测试"})
    assert response.status_code == 200
    sheet = load_workbook(io.BytesIO(response.content)).active
    headers = [cell.value for cell in sheet[1]]
    assert "姓名" in headers and "学号" in headers


def test_adding_a_field_takes_effect_immediately(client):
    """字段是数据：加完字段接口立刻能用，**不需要重启服务**。"""
    created = client.post(
        "/api/v1/students/fields",
        json={"key": "seatNo", "label": "座位号", "type": "text", "in_list": True, "in_form": True},
    )
    assert created.status_code == 201, created.text

    spec = client.get("/api/v1/students/schema").json()["data"]
    assert "seatNo" in [field["k"] for field in spec["fields"]]

    saved = client.post(
        "/api/v1/students", json={"name": "新字段测试", "sno": "D9006", "seatNo": "3排2座"}
    ).json()["data"]
    assert saved["seatNo"] == "3排2座"


def test_deleting_a_field_keeps_the_data(client):
    """删字段只删定义、数据保留；把同名字段加回来，值还在。"""
    field = client.post(
        "/api/v1/students/fields",
        json={"key": "tempNote", "label": "临时字段", "type": "text", "in_list": True, "in_form": True},
    ).json()["data"]
    client.post("/api/v1/students", json={"name": "删字段测试", "sno": "D9007", "tempNote": "临时值"})

    client.delete(f"/api/v1/students/fields/{field['id']}")
    spec = client.get("/api/v1/students/schema").json()["data"]
    assert "tempNote" not in [item["k"] for item in spec["fields"]]

    client.post(
        "/api/v1/students/fields",
        json={"key": "tempNote", "label": "临时字段", "type": "text", "in_list": True, "in_form": True},
    )
    row = client.get("/api/v1/students", params={"q": "删字段测试"}).json()["data"][0]
    assert row["tempNote"] == "临时值"  # 数据没丢


def test_identity_fields_cannot_be_deleted(client):
    identity = next(
        item for item in client.get("/api/v1/students/fields").json()["data"] if item["key"] == "sno"
    )
    response = client.delete(f"/api/v1/students/fields/{identity['id']}")
    assert response.status_code == 400
    assert "身份字段" in response.json()["error"]["message"]


def test_field_key_cannot_be_renamed(client):
    field = next(
        item for item in client.get("/api/v1/students/fields").json()["data"] if item["key"] == "hobby"
    )
    response = client.patch(f"/api/v1/students/fields/{field['id']}", json={"key": "hobby2"})
    assert response.status_code == 400
    assert "不能改" in response.json()["error"]["message"]
