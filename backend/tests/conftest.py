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

from app.config import DATA_DIR, MEDIA_DIR  # noqa: E402
from app.db.base import Base  # noqa: E402
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


# 每个用例之间要清掉的**业务表** —— **从模型元数据自动取**，不手工维护清单。
#
# 手工清单这件事我漏过三次（新加的表忘了写进去，于是上一个用例的数据漏到下一个），
# 所以改成推导：除了启动时播种的几张表（班级、学生字段定义、应用配置），其余全清。
SEEDED_TABLES = {"classes", "student_field_def", "app_state"}
# 自检：名字写错的话，播种数据会被当成业务数据清掉，而症状是「学生档案突然没有字段了」——
# 离原因很远。所以这里当场炸。
assert SEEDED_TABLES <= {table.name for table in Base.metadata.sorted_tables}, (
    f"SEEDED_TABLES 里有不存在的表名：{SEEDED_TABLES - {t.name for t in Base.metadata.sorted_tables}}"
)
# 倒着取：先子表后主表（外键开着，先删主表会被约束拦下）
BUSINESS_TABLES = [
    table.name
    for table in reversed(Base.metadata.sorted_tables)
    if table.name not in SEEDED_TABLES
]

# 存在 `app_state` 里、但属于「业务数据」的键（每个班一份）。
# 不清的话，上一个用例的座位快照会让下一个用例的「能回退吗」显示出错。
BUSINESS_APP_STATE_KEYS = ("seat_snapshot:",)


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
        # `classes` 是启动时播种的（默认班），不能整表清 —— 但**用例额外建的班必须清掉**：
        # 留着它，后面所有「只有一个班、不用传 classId」的用例都会变成 409
        # （多班场景的用例建了第二个班，症状却出现在别的文件里，很难查）。
        # 外键带 CASCADE，附属数据在上面的循环里已经清过了
        session.execute(text("DELETE FROM classes WHERE id <> (SELECT MIN(id) FROM classes)"))
        for prefix in BUSINESS_APP_STATE_KEYS:
            session.execute(
                text("DELETE FROM app_state WHERE key LIKE :pattern"), {"pattern": f"{prefix}%"}
            )
        session.commit()
    finally:
        session.close()

    # 媒体**文件**也要清：只清表的话，上一个用例传的照片还留在盘上，
    # 「盘上只有一份文件」这类断言就会被别人留下的文件搅乱
    for folder in (MEDIA_DIR, DATA_DIR / "trash"):
        if not folder.exists():
            continue
        for item in folder.rglob("*"):
            if item.is_file():
                item.unlink()
