"""pytest 全局配置。

两件必须在 `import app.*` 之前完成的事：

1. 把 `backend/` 放进 `sys.path`，这样无论用 `pytest` 还是 `python -m pytest` 都能 `import app`；
2. 把数据目录指向临时目录 —— `app.config` 是在**导入时**读取环境变量的，晚一步测试就会写真实数据目录。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

_TMP_DATA_DIR = Path(tempfile.mkdtemp(prefix="tws-test-"))
os.environ["TWS_DATA_DIR"] = str(_TMP_DATA_DIR)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.engine import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(_TMP_DATA_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def client():
    """带 lifespan 的客户端：会建目录、跑数据库迁移、建默认班级、播种学生字段定义。"""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db_session(client):  # 依赖 client：确保应用已启动、迁移已跑，表才存在
    """直连测试库的会话，供服务级测试直接准备数据（比如插一名学生）。"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
