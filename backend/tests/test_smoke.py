"""端到端冒烟测试：注册表 → 增删改查 → 统计 → 校验与错误码。

这是阶段 1「先用最简单的页面把整条链路跑通」的那道闸门 ——
它一旦通过，说明「前端 → API → 库」的骨架是通的，后面只是往注册表里加表。
"""

from __future__ import annotations


def test_health(client):
    body = client.get("/api/v1/health").json()
    assert body["ok"] is True
    assert body["data"]["tables"] == 3


def test_registry_exposes_three_tables(client):
    data = client.get("/api/v1/meta/registry").json()["data"]
    assert {spec["key"] for spec in data} == {"todos", "rules", "templates"}

    todos = next(spec for spec in data if spec["key"] == "todos")
    assert todos["classScoped"] is True
    assert [column["k"] for column in todos["columns"]][:2] == ["content", "due_date"]


def test_todo_crud_and_stats(client):
    created = client.post(
        "/api/v1/todos",
        json={"content": "收作业", "priority": "高", "due_date": "2026-09-20"},
    )
    assert created.status_code == 201, created.text
    todo = created.json()["data"]
    assert todo["due_date"] == "2026-09-20"
    assert todo["done"] is False

    listed = client.get("/api/v1/todos", params={"q": "收作业"}).json()
    assert listed["meta"]["total"] == 1

    patched = client.patch(f"/api/v1/todos/{todo['id']}", json={"done": True}).json()
    assert patched["data"]["done"] is True

    stats = client.get("/api/v1/todos/stats").json()["data"]
    assert stats["total"] == 1
    assert stats["groups"]["priority"] == {"高": 1}

    assert client.delete(f"/api/v1/todos/{todo['id']}").json()["data"]["id"] == todo["id"]
    assert client.get(f"/api/v1/todos/{todo['id']}").status_code == 404


def test_required_and_unknown_field_codes(client):
    missing = client.post("/api/v1/rules", json={"title": ""})
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "FIELD_REQUIRED"

    unknown = client.post("/api/v1/rules", json={"title": "早读要求", "whatever": 1})
    assert unknown.json()["error"]["code"] == "UNKNOWN_FIELD"


def test_bad_date_message_is_human_readable(client):
    bad = client.post("/api/v1/todos", json={"content": "交材料", "due_date": "下周一"})
    assert bad.status_code == 400
    error = bad.json()["error"]
    assert error["code"] == "INVALID_VALUE"
    # 提示里给出正确格式示例，而不是「出错了：…」
    assert "2026-09-01" in error["message"]


def test_global_table_needs_no_class(client):
    created = client.post("/api/v1/templates", json={"title": "迟到沟通", "content": "家长您好……"})
    assert created.status_code == 201, created.text
    template = created.json()["data"]
    assert template["title"] == "迟到沟通"
    assert "class_id" not in template  # 全局表不属于任何班级


def test_batch_delete_then_list_is_empty(client):
    ids = [
        client.post("/api/v1/todos", json={"content": f"批量{i}"}).json()["data"]["id"]
        for i in range(3)
    ]
    result = client.post("/api/v1/todos/batch", json={"action": "delete", "ids": ids}).json()
    assert result["data"]["affected"] == 3
    assert client.get("/api/v1/todos", params={"q": "批量"}).json()["meta"]["total"] == 0


# ---------------------------------------------------------------------------
# 下面三个用例守的是「错误永远走统一封套」这条底线 ——
# 曾经因为把异常处理器注册在 fastapi.HTTPException（子类）上，
# 导致 404 与请求体解析失败漏出 {"detail": ...}，前端拿不到 code。
# ---------------------------------------------------------------------------


def test_unknown_route_uses_our_envelope(client):
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "NOT_FOUND"


def test_malformed_json_uses_our_envelope(client):
    response = client.post(
        "/api/v1/todos",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION"
    assert "JSON" in body["error"]["message"]


def test_chinese_content_roundtrip(client):
    created = client.post(
        "/api/v1/rules",
        json={"title": "早读要求", "content": "7:20 前到班，朗读书目自选。"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["title"] == "早读要求"
