"""学生档案：把「字段定义」变成「表声明」。

学生档案的字段是**运行时可变的**（老师能自己加字段），所以它的 `TableSpec` 不是写死的常量，
而是每次请求按库里的字段定义现算 —— 这就是「动态表」的含义（见 `schemas/registry.py`
的 `DYNAMIC_TABLES`）。

好处是它照样走**通用链路**：列表、表单、导入、导出、统计、软删除全部复用同一套实现，
不必为学生档案写一套特例 —— 特例正是「同一规则多处实现」的温床。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, ApiError
from app.db.engine import SessionLocal
from app.models.student import Student, StudentFieldDef
from app.schemas.registry import ColumnSpec, FieldSpec, TableSpec
from app.services.student_fields import build_defs_from_template

# 这两个是**真实列**（身份字段：列表、搜索、导入判重、点名都靠它），其余都在 extra JSON 里
COLUMN_KEYS = ("name", "sno")

DEFAULT_SORT = ("sno", 1)  # 按学号排，与旧应用一致


def load_defs(session: Session) -> list[StudentFieldDef]:
    return list(
        session.scalars(
            select(StudentFieldDef).order_by(StudentFieldDef.sort_order, StudentFieldDef.id)
        )
    )


def build_spec_from_defs(defs: list[StudentFieldDef]) -> TableSpec:
    columns = tuple(
        ColumnSpec(definition.key, definition.label) for definition in defs if definition.in_list
    )
    fields = tuple(
        FieldSpec(
            definition.key,
            definition.label,
            type=definition.type,
            # 姓名必须填（模型也是 NOT NULL）；其余按定义。学号允许为空（转学生可能还没有）
            required=definition.required or definition.key == "name",
            options=tuple(definition.options or ()),
            full=definition.type == "textarea",
            hint=definition.hint,
            aliases=tuple(definition.aliases or ()),
        )
        for definition in defs
        if definition.in_form
    )
    searchable = tuple(
        definition.key
        for definition in defs
        if definition.searchable and definition.key not in COLUMN_KEYS
    )
    return TableSpec(
        key="students",
        model=Student,
        title="学生档案",
        entity="学生",
        columns=columns,
        fields=fields,
        # 姓名与学号永远可搜 —— 老师找学生就是按这两个
        search_keys=COLUMN_KEYS + searchable,
        filter_keys=tuple(definition.key for definition in defs if definition.filterable),
        default_sort=DEFAULT_SORT,
        class_scoped=True,
        dedupe_keys=("sno",),  # 同学号即同一名学生，重复导入不翻倍
        json_column="extra",
        json_fields=frozenset(
            definition.key for definition in defs if definition.key not in COLUMN_KEYS
        ),
        before_save=check_unique_sno,
    )


def students_spec() -> TableSpec:
    """动态表声明：每次调用按当前字段定义现算（老师加完字段立即生效，不用重启）。

    迁移还没跑（表还不存在）时退回默认模板 —— 表声明因此**始终可描述**，
    不会因为「谁先谁后」在启动早期或测试收集阶段炸掉。
    """
    try:
        with SessionLocal() as session:
            defs = load_defs(session)
    except OperationalError:
        defs = build_defs_from_template()
    return build_spec_from_defs(defs)


def check_unique_sno(values: dict[str, Any], session: Session, row: Any = None) -> None:
    """学号在班内唯一。

    数据库有部分唯一索引兜底，但撞上时只会抛 IntegrityError（500），
    对老师来说等于「出错了」。这里提前查一次，给出能看懂、能照做的提示。
    """
    sno = str(values.get("sno") or "").strip()
    if not sno:
        return

    class_id = values.get("classId") or getattr(row, "class_id", None)
    query = select(Student).where(Student.deleted_at.is_(None), Student.sno == sno)
    if class_id:
        query = query.where(Student.class_id == class_id)
    if row is not None:
        query = query.where(Student.id != row.id)

    if session.scalar(query) is not None:
        raise ApiError(
            INVALID_VALUE,
            f"学号「{sno}」在这个班里已经有了，请检查是否重复导入或学号填错",
            detail={"field": "sno", "value": sno},
        )
