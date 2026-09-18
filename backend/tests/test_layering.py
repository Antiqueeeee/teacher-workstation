"""分层禁令的看门测试（`CONTRIBUTING.md` §2）。

三条禁令：`api/` 不写 SQL、不写业务规则；`services/` 不 import FastAPI；
`models/` 不写查询。这些靠人盯是盯不住的 —— 写新接口时顺手来一句 `select(...)`
太自然了，而它的代价（口径散在多处、脱离 HTTP 就没法单测）要过很久才显出来。

阶段 5 评审实测抓到过两处（`student_fields.py`、`contacts.py` 里有 SQL），
所以这里把它变成一条**会失败的断言**，而不是一条只写在文档里的规矩。
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"

# 唯一允许在 `api/` 里用 SQLAlchemy 的文件：通用 CRUD 路由工厂。
# 它本身就是「把表声明变成一组查询」的生成器，抽到服务层反而会被切成两半。
API_SQL_ALLOWED = {"crud_factory.py"}

# 允许 import 的 SQLAlchemy 模块：Session 只是依赖注入的类型标注，不含查询能力
ALLOWED_SQLALCHEMY_MODULES = {"sqlalchemy.orm"}

# 事务控制**不算**数据访问：媒体那几个接口必须在响应之前把文件状态与库状态一起落定
# （见 `db/engine.py:get_session` 的提交时机说明）
TRANSACTION_METHODS = {"commit", "rollback", "flush", "close", "expunge"}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imports(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _session_calls(tree: ast.Module) -> int:
    """数一数代码里对 `session` 调了几次**查询类**方法 —— 那一层不该碰数据访问。"""
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in {"session", "db"} and node.attr not in TRANSACTION_METHODS:
                count += 1
    return count


def test_api_layer_has_no_sql():
    offenders: list[str] = []
    for path in sorted((APP / "api").rglob("*.py")):
        if path.name in API_SQL_ALLOWED:
            continue
        tree = _tree(path)
        bad_imports = {
            name
            for name in _imports(tree)
            if name.startswith("sqlalchemy") and name not in ALLOWED_SQLALCHEMY_MODULES
        }
        if bad_imports:
            offenders.append(f"{path.name} 导入了 {sorted(bad_imports)}")
        calls = _session_calls(tree)
        if calls:
            offenders.append(f"{path.name} 里对 session 调了 {calls} 次方法（查询要放进 services/）")
    assert not offenders, "api/ 层出现了数据访问代码：" + "；".join(offenders)


def test_services_layer_does_not_import_fastapi():
    offenders = []
    for path in sorted((APP / "services").rglob("*.py")):
        if any(name.startswith("fastapi") for name in _imports(_tree(path))):
            offenders.append(path.name)
    assert not offenders, f"services/ 不该 import FastAPI（脱离 HTTP 也要能单测）：{offenders}"


def test_models_layer_does_not_query():
    """模型里不写查询 —— 查询与规则都在服务层，模型只管「数据长什么样」。"""
    offenders = []
    for path in sorted((APP / "models").rglob("*.py")):
        if any(name.startswith("sqlalchemy.orm") and name != "sqlalchemy.orm" for name in
               _imports(_tree(path))):
            offenders.append(path.name)
    assert not offenders, f"models/ 里出现了会话相关导入：{offenders}"
