"""数据库引擎与会话。

SQLite 参数（见 CONTRIBUTING.md §5）：
- `journal_mode=WAL`   —— 支持「手机与电脑并发读 + 单写」；
- `foreign_keys=ON`    —— SQLite 默认不校验外键，必须显式打开；
- `busy_timeout=5000`  —— 写锁冲突时最多等 5 秒，而不是立刻报错。
"""

from __future__ import annotations

from collections.abc import Iterator
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _apply_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_session() -> Iterator[Session]:
    """FastAPI 依赖（经 `app/api/session.py:db_session` 使用）：每个请求一个会话。

    **提交时机**：写请求的提交在 `app/api/committing_route.py` 里做（在响应发出**之前**，
    失败才能变成 500）；这里最后那次 commit 是**保险**（脚本直接调服务层、老代码路径）。
    为什么不能只靠这里：FastAPI 的 yield 依赖在响应发出之后才收尾，
    所以「提交时报错」发生时客户端已经拿到 200「已保存」了 —— 老师以为记上了，其实没记上。
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
