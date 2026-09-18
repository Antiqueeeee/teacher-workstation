"""端到端冒烟测试：注册表 → 增删改查 → 统计 → 校验与错误码。

这是阶段 1「先用最简单的页面把整条链路跑通」的那道闸门 ——
它一旦通过，说明「前端 → API → 库」的骨架是通的，后面只是往注册表里加表。
"""

from __future__ import annotations


def test_health(client):
    from app.schemas.registry import TABLES

    body = client.get("/api/v1/health").json()
    assert body["ok"] is True
    # 与注册表对齐，而不是写死数字 —— 加一张表不该让测试红
    assert body["data"]["tables"] == len(TABLES)


def test_registry_lists_every_declared_table(client):
    from app.schemas.registry import TABLES

    data = client.get("/api/v1/meta/registry").json()["data"]
    assert {spec["key"] for spec in data} == set(TABLES)

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


# ---------------------------------------------------------------------------
# 下面四组是评审阶段发现的问题的回归测试。
# 它们守的都是「不会报错、但数据会变歪」这一类 —— 最贵的那种错。
# ---------------------------------------------------------------------------


def test_stats_shares_the_same_conditions_as_list(client):
    """KPI 与列表必须同一套条件，否则搜完之后看到的总数不是搜索结果的总数。"""
    client.post("/api/v1/todos", json={"content": "口径测试-高", "priority": "高"})
    client.post("/api/v1/todos", json={"content": "口径测试-低", "priority": "低"})
    params = {"q": "口径测试", "filter.priority": "高"}

    listed = client.get("/api/v1/todos", params=params).json()
    stats = client.get("/api/v1/todos/stats", params=params).json()["data"]

    assert listed["meta"]["total"] == 1
    assert stats["total"] == 1  # 曾经这里是 2（stats 没认 q 与 filter）
    assert stats["groups"]["priority"] == {"高": 1}


def test_boolean_group_label_uses_chinese(client):
    """分组键要走「是/否」词表，不能冒出 True/False。"""
    client.post("/api/v1/todos", json={"content": "布尔分组测试", "done": True})
    stats = client.get("/api/v1/todos/stats", params={"q": "布尔分组测试"}).json()["data"]
    assert stats["groups"]["done"] == {"是": 1}


def test_soft_deleted_row_can_be_listed_and_restored(client):
    """软删除必须留出口 —— 删除确认框里对用户承诺过「可以找回」。"""
    created = client.post("/api/v1/todos", json={"content": "回收站测试"}).json()["data"]
    client.delete(f"/api/v1/todos/{created['id']}")
    assert client.get("/api/v1/todos", params={"q": "回收站测试"}).json()["meta"]["total"] == 0

    shown = client.get("/api/v1/todos", params={"q": "回收站测试", "includeDeleted": "1"}).json()
    assert shown["meta"]["total"] == 1

    restored = client.post(f"/api/v1/todos/{created['id']}/restore").json()["data"]
    assert restored["id"] == created["id"]
    assert client.get("/api/v1/todos", params={"q": "回收站测试"}).json()["meta"]["total"] == 1


def test_batch_skips_deleted_rows(client):
    """批量操作不能碰到界面上看不见的已删记录。"""
    created = client.post("/api/v1/todos", json={"content": "批量软删测试"}).json()["data"]
    client.delete(f"/api/v1/todos/{created['id']}")

    result = client.post(
        "/api/v1/todos/batch",
        json={"action": "update", "ids": [created["id"]], "patch": {"content": "不该被改"}},
    ).json()["data"]
    assert result == {"requested": 1, "affected": 0}
