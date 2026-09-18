"""学生档案字段：默认模板 + 由字段定义生成「表声明」。

默认模板来自旧应用真实的 24 条字段定义（`tools/extract_demo_fixture.py` 抽出），
**包括 Excel 表头别名** —— 别名是导入能不能认出那一列的关键，自己编一套等于让真实表格进不来
（这个坑在班规类别上踩过一次）。

`default_student_fields.json` 是**应用数据**（新建档案时的默认字段集），随代码交付。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, NOT_FOUND, ApiError
from app.models.student import StudentFieldDef
# 从 table_spec 取类型表，**不走 registry**：registry 会 import 各域 specs，
# 而 specs 又要 import 服务层 —— 走它在导入链上会成环
from app.schemas.table_spec import FIELD_TYPES

DEFAULT_FIELDS_PATH = Path(__file__).resolve().parent / "default_student_fields.json"

# 字段定义里**允许改**的属性（改 key 会让历史数据失去归属，见 update_def）
EDITABLE_ATTRS = (
    "label",
    "type",
    "options",
    "required",
    "in_list",
    "in_form",
    "in_detail",
    "searchable",
    "filterable",
    "sort_order",
    "aliases",
    "hint",
)

# 这些字段在新模型里属于「监护人」子表，不再作为学生的动态字段
# （旧应用把它们同时放在学生档案和联系人表里，是同一件事两处存）
MOVED_TO_GUARDIAN = frozenset({"father", "mother", "fatherPhone", "motherPhone"})

# 旧应用的字段类型 → 我们支持的字段类型
# tel：本质是文本，但手机上要弹数字键盘（前端按 text + inputmode 处理）
# photo：照片能力在阶段 4 接入，先当文本存文件名/说明，界面上有说明
TYPE_MAP = {
    "tel": "text",
    "photo": "text",
    "images": "text",
}

FALLBACK_TYPE = "text"
FIELD_TYPE_HINT = {
    "photo": "照片功能在后续阶段接入，这里先记文件名或说明",
}


def load_default_fields() -> list[dict[str, Any]]:
    """读取默认字段模板（已剔除挪到监护人表的字段）。"""
    rows = json.loads(DEFAULT_FIELDS_PATH.read_text(encoding="utf-8"))
    return [row for row in rows if row.get("k") not in MOVED_TO_GUARDIAN]


def normalize_type(raw_type: str | None) -> str:
    return TYPE_MAP.get(raw_type or "", raw_type or FALLBACK_TYPE)


def build_defs_from_template() -> list[StudentFieldDef]:
    """按默认模板造出字段定义对象（**不落库**）。

    播种与「迁移还没跑、表还不存在时的兜底」共用它 ——
    两处各写一遍模板解析，迟早不一致。
    """
    defs: list[StudentFieldDef] = []
    for order, row in enumerate(load_default_fields(), start=1):
        key = row.get("k")
        if not key:
            continue
        defs.append(
            StudentFieldDef(
                key=key,
                label=row.get("label") or key,
                type=normalize_type(row.get("type")),
                options=list(row.get("options") or []),
                required=bool(row.get("required")),
                identity=bool(row.get("identity")),
                in_list=bool(row.get("inList", True)),
                in_form=bool(row.get("inForm", True)),
                in_detail=bool(row.get("inDetail", True)),
                searchable=bool(row.get("searchable")),
                filterable=bool(row.get("filter", False)),
                sort_order=order,
                aliases=list(row.get("syn") or []),
                hint=FIELD_TYPE_HINT.get(row.get("type") or "", ""),
            )
        )
    return defs


def seed_field_defs(session: Session) -> int:
    """把默认字段模板写进库。**幂等**：同 key 已存在就跳过，不覆盖老师改过的定义。"""
    existing = set(session.scalars(select(StudentFieldDef.key)))
    created = 0
    for definition in build_defs_from_template():
        if definition.key in existing:
            continue
        session.add(definition)
        created += 1
    return created


# ------------------------------------------------- 字段管理的读写（接口层不再写 SQL）


def list_defs(session: Session) -> list[StudentFieldDef]:
    return list(
        session.scalars(
            select(StudentFieldDef).order_by(StudentFieldDef.sort_order, StudentFieldDef.id)
        )
    )


def get_def(session: Session, field_id: int) -> StudentFieldDef:
    definition = session.get(StudentFieldDef, field_id)
    if definition is None:
        raise ApiError(NOT_FOUND, "这个字段不存在，可能已被删除", status=404, detail={"id": field_id})
    return definition


def check_type(value: Any) -> str:
    if value not in FIELD_TYPES:
        raise ApiError(
            INVALID_VALUE,
            f"字段类型只能是：{'、'.join(FIELD_TYPES)}",
            detail={"field": "type", "value": value},
        )
    return str(value)


def create_def(session: Session, body: dict[str, Any]) -> StudentFieldDef:
    """加一个字段。标识（key）是数据存储用的键，所以校验得细一点。"""
    key = str(body.get("key") or "").strip()
    label = str(body.get("label") or "").strip()
    if not key or not label:
        raise ApiError(INVALID_VALUE, "字段标识与名称都必填", detail={"field": "key"})
    if not key.isascii() or not key.replace("_", "").isalnum():
        raise ApiError(
            INVALID_VALUE,
            "字段标识请用英文字母/数字/下划线（它同时是 Excel 列名匹配与数据存储用的键）",
            detail={"field": "key", "value": key},
        )
    if session.scalar(select(StudentFieldDef).where(StudentFieldDef.key == key)) is not None:
        raise ApiError(INVALID_VALUE, f"已经有一个字段叫「{key}」了", detail={"field": "key"})

    max_order = session.scalar(
        select(StudentFieldDef.sort_order).order_by(StudentFieldDef.sort_order.desc()).limit(1)
    )
    definition = StudentFieldDef(
        key=key,
        label=label,
        type=check_type(body.get("type") or "text"),
        options=list(body.get("options") or []),
        required=bool(body.get("required")),
        in_list=bool(body.get("in_list", True)),
        in_form=bool(body.get("in_form", True)),
        in_detail=bool(body.get("in_detail", True)),
        searchable=bool(body.get("searchable")),
        filterable=bool(body.get("filterable")),
        sort_order=int(body.get("sort_order") or (max_order or 0) + 1),
        aliases=list(body.get("aliases") or []),
        hint=str(body.get("hint") or ""),
    )
    session.add(definition)
    session.flush()
    return definition


def update_def(session: Session, field_id: int, body: dict[str, Any]) -> StudentFieldDef:
    definition = get_def(session, field_id)
    if "key" in body and str(body["key"]).strip() != definition.key:
        # 改 key 等于让历史数据失去归属：extra 里存的是旧 key
        raise ApiError(
            INVALID_VALUE,
            "字段标识不能改（数据是按它存的）。可以改名称，或删掉这个字段再新建一个。",
            detail={"field": "key"},
        )
    if "type" in body:
        body = {**body, "type": check_type(body["type"])}
    for attr in EDITABLE_ATTRS:
        if attr in body:
            setattr(definition, attr, body[attr])
    session.flush()
    return definition


def delete_def(session: Session, field_id: int) -> str:
    """删字段**只删定义**：`extra` 里的值原样保留，把同名字段加回来值还在。"""
    definition = get_def(session, field_id)
    if definition.identity:
        raise ApiError(
            INVALID_VALUE,
            f"「{definition.label}」是身份字段，不能删除（记录之间对得上全靠它）",
            detail={"field": "key", "value": definition.key},
        )
    key = definition.key
    session.delete(definition)
    session.flush()
    return key
