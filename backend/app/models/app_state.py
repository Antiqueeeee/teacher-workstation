"""应用级键值配置。

存放原本散落在旧应用 `meta` / `appearance` / `seatPlan` / `pageVisibility` 里的东西：
外观、座位表参数、页面可见性、跟进规则等。它们的共同点是「结构不固定、数量少」，
不值得各建一张表。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AppState(Base, TimestampMixin):
    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
