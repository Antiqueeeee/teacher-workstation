"""数据库迁移：启动时自动升级到最新版本。

老师自己部署，不会（也不该）手工敲 alembic 命令，所以让服务启动时自己升级。
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import DATABASE_URL

BACKEND_DIR = Path(__file__).resolve().parents[2]  # app/db/migrate.py → backend/
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
SCRIPT_LOCATION = BACKEND_DIR / "app" / "db" / "migrations"


def alembic_config() -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(SCRIPT_LOCATION))
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    return config


def upgrade_to_head() -> None:
    command.upgrade(alembic_config(), "head")
