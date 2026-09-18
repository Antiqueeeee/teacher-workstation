"""Pydantic 模型与「表注册表」。"""

from app.schemas.common import page_meta
from app.schemas.registry import TABLES, ColumnSpec, FieldSpec, TableSpec, get_spec

__all__ = ["page_meta", "TABLES", "ColumnSpec", "FieldSpec", "TableSpec", "get_spec"]
