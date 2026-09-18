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

from app.models.student import StudentFieldDef

DEFAULT_FIELDS_PATH = Path(__file__).resolve().parent / "default_student_fields.json"

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


def seed_field_defs(session: Session) -> int:
    """把默认字段模板写进库。**幂等**：同 key 已存在就跳过，不覆盖老师改过的定义。"""
    existing = set(session.scalars(select(StudentFieldDef.key)))
    created = 0
    for order, row in enumerate(load_default_fields(), start=1):
        key = row.get("k")
        if not key or key in existing:
            continue
        field_type = normalize_type(row.get("type"))
        session.add(
            StudentFieldDef(
                key=key,
                label=row.get("label") or key,
                type=field_type,
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
        created += 1
    return created
