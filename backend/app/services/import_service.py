"""导入服务：文件 → 预览（规范化行 + 问题清单）→ 确认后单事务写入。

**关键设计取舍：不做服务端暂存令牌。**

预览把规范化后的行**返回给前端**，老师可以就地改错；提交时把确认过的行发回来，
重新校验、单事务写入。好处是没有超时、没有服务端状态、重启不丢，
并且天然支持「在预览里改一行再提交」这个真实用法（老师手里的表总有几个脏格子）。

**提交是全有或全无**：只要有一行校验不过，整批不写 —— 数据库里不会留下半份导入结果。
这比「能进多少进多少」可预测得多，也省掉了「到底哪些进去了」的排查成本。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.schemas.registry import TableSpec
from app.services import table_io
from app.services.field_value import parse_value

MAX_ROWS = 2000  # 一次导入的行数上限：防止误传一个几万行的总表

CODE_MISSING_COLUMN = "MISSING_COLUMN"
CODE_DUPLICATE_IN_FILE = "DUPLICATE_IN_FILE"


class ImportFailed(Exception):
    """输入本身没法处理（空文件、认不出任何表头）。由 API 层翻成 ApiError。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class PreviewRow:
    row: int  # 原文件里的行号（含表头，从 1 开始）
    values: dict[str, Any]
    issues: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"row": self.row, "values": self.values, "issues": self.issues, "ok": not self.issues}


def _dedupe_key(spec: TableSpec, values: dict[str, Any]) -> tuple | None:
    if not spec.dedupe_keys:
        return None
    if any(key not in values for key in spec.dedupe_keys):
        return None  # 判重键不全就没法判，交给逐格校验去报错
    return tuple(str(values[key]) for key in spec.dedupe_keys)


def normalize_rows(
    spec: TableSpec, rows: list[list[Any]], mapping: dict[int, str]
) -> list[PreviewRow]:
    """把二维表按列映射翻译成「字段 → 值」，逐格校验，并标出文件内重复。"""
    preview_rows: list[PreviewRow] = []
    seen_keys: dict[tuple, int] = {}

    for offset, raw_row in enumerate(rows):
        values: dict[str, Any] = {}
        issues: list[dict[str, str]] = []

        for position, field_key in mapping.items():
            raw = raw_row[position] if position < len(raw_row) else None
            value, issue = parse_value(spec.field_map[field_key], raw)
            if issue is not None:
                issues.append({"field": field_key, "code": issue.code, "message": issue.message})
            else:
                values[field_key] = value

        # 选填字段整列缺失时补默认值，保证写入的是一份完整记录
        for field_spec in spec.fields:
            if not field_spec.editable or field_spec.k in values:
                continue
            if not field_spec.required and field_spec.default is not None:
                values[field_spec.k] = field_spec.default

        key = _dedupe_key(spec, values)
        if key is not None and not issues:
            first_row = seen_keys.get(key)
            if first_row is not None:
                issues.append(
                    {
                        "field": "",
                        "code": CODE_DUPLICATE_IN_FILE,
                        "message": f"与第 {first_row} 行重复（同一份文件里出现两次）",
                    }
                )
            else:
                seen_keys[key] = offset + 1

        preview_rows.append(PreviewRow(row=offset + 1, values=values, issues=issues))

    return preview_rows


def preview(spec: TableSpec, filename: str, content: bytes) -> dict[str, Any]:
    """解析 + 校验，产出可编辑的预览。不写数据库。"""
    if not content:
        raise ImportFailed("EMPTY_FILE", "文件是空的，没有读到任何内容")

    rows = table_io.read_rows(filename, content)
    if not rows:
        raise ImportFailed("EMPTY_FILE", "文件里没有有效数据行")

    header_row = rows[0]
    data_rows = rows[1:]
    if not data_rows:
        raise ImportFailed("NO_DATA_ROWS", "只读到表头，没有数据行")
    if len(data_rows) > MAX_ROWS:
        raise ImportFailed("TOO_MANY_ROWS", f"一次最多导入 {MAX_ROWS} 行（当前 {len(data_rows)} 行）")

    mapping, unknown_headers = table_io.match_headers(spec, header_row)
    if not mapping:
        raise ImportFailed(
            "NO_HEADER_MATCHED",
            "表头一个字段都没认出来。请先下载模板对照列名，或检查是否选错了表。"
            f"（读到的表头：{'、'.join(str(cell) for cell in header_row if not table_io.is_blank(cell))}）",
        )

    missing_columns = [
        field_spec.label
        for field_spec in spec.fields
        if field_spec.required and field_spec.editable and field_spec.k not in mapping.values()
    ]

    preview_rows = normalize_rows(spec, data_rows, mapping)
    problem_rows = [row for row in preview_rows if row.issues]

    return {
        "table": spec.key,
        "filename": filename,
        "headers": [str(cell) if cell is not None else "" for cell in header_row],
        "mapping": {field_key: str(header_row[position]) for position, field_key in sorted(mapping.items())},
        "unknownHeaders": unknown_headers,
        "missingColumns": missing_columns,
        "rows": [row.to_dict() for row in preview_rows],
        "summary": {
            "total": len(preview_rows),
            "ok": len(preview_rows) - len(problem_rows),
            "problem": len(problem_rows),
            "duplicateInFile": sum(
                1
                for row in preview_rows
                if any(issue["code"] == CODE_DUPLICATE_IN_FILE for issue in row.issues)
            ),
        },
    }


def _validate(spec: TableSpec, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """重新校验提交上来的行。返回 `(合法行, 报错行)`。

    提交路径**必须重新校验**：预览结果在前端绕了一圈，可能被人改过，也可能过期。
    """
    good: list[dict[str, Any]] = []
    bad: list[dict[str, Any]] = []

    for index, raw in enumerate(rows, start=1):
        values: dict[str, Any] = {}
        issues: list[dict[str, str]] = []
        for field_spec in spec.fields:
            if not field_spec.editable:
                continue
            value, issue = parse_value(field_spec, raw.get(field_spec.k))
            if issue is not None:
                issues.append({"field": field_spec.k, "code": issue.code, "message": issue.message})
            else:
                values[field_spec.k] = value
        if issues:
            bad.append({"row": index, "values": raw, "issues": issues})
        else:
            good.append(values)

    return good, bad


def commit(
    spec: TableSpec, session: Session, rows: list[dict[str, Any]], class_id: int | None
) -> dict[str, Any]:
    """单事务写入。有任何一行不过就整批不写。"""
    if not rows:
        raise ImportFailed("NO_ROWS", "没有要导入的行")

    good, bad = _validate(spec, rows)
    if bad:
        raise ImportFailed(
            "ROW_VALIDATION_FAILED",
            f"有 {len(bad)} 行没通过校验，整批未写入。请修好后再提交。",
        )

    existing: set[tuple] = set()
    if spec.dedupe_keys:
        query = select(spec.model)
        if spec.soft_delete:
            query = query.where(spec.model.deleted_at.is_(None))
        if spec.class_scoped and class_id is not None:
            query = query.where(spec.model.class_id == class_id)
        for row in session.scalars(query):
            key = tuple(str(getattr(row, name)) for name in spec.dedupe_keys)
            existing.add(key)

    created, skipped = 0, []
    for index, values in enumerate(good, start=1):
        key = _dedupe_key(spec, values)
        if key is not None and key in existing:
            skipped.append({"row": index, "reason": "库里已有同一条记录，已跳过"})
            continue
        row = spec.model(**values)
        if spec.class_scoped and class_id is not None:
            row.class_id = class_id
        session.add(row)
        if key is not None:
            existing.add(key)
        created += 1

    session.flush()
    return {
        "table": spec.key,
        "created": created,
        "skipped": skipped,
        "skippedCount": len(skipped),
    }
