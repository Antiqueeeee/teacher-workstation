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


# 每个用例之间要清掉的**业务表**（顺序：先子表后主表，虽然外键是级联的，
# 但显式按顺序删更好读、也不依赖 PRAGMA foreign_keys 的开启时机）。
#
# 为什么不一起清 `students` 之外的种子数据：`classes`（默认班级）、
# `student_field_defs`（默认字段定义）、`app_state` 是应用启动时播种的，
# 清掉它们后面的用例会找不到班级与字段。
BUSINESS_TABLES = (
    "scores",
    "exam_subjects",
    "exams",
    "dorm_beds",
    "dorm_rooms",
    "attendance",
    "homework_unsubmitted",
    "homework",
    "guardians",
    "todos",
    "rules",
    "templates",
    "students",
)


@pytest.fixture(autouse=True)
def clean_business_data(client):  # 依赖 client：确保表已经建好
    """每个用例跑完清空业务数据。

    没有这一步，用例之间会互相污染：「上一个用例顺手多建了一个学生」会让
    后面用例里的「全班人数」多 1，于是断言只能写成 `>= 1` 这种弱形式 ——
    而弱断言在测试顺序一变时就会变成假阴性（真实回归也测不出来）。
    """
    yield

    from sqlalchemy import text

    session = SessionLocal()
    try:
        for table in BUSINESS_TABLES:
            session.execute(text(f"DELETE FROM {table}"))
        session.commit()
    finally:
        session.close()
