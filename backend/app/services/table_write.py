"""写入管线：**校验 → 班级归属 → 保存前钩子 → 分流（真实列 / JSON 列）→ 落库**。

为什么单独成模块：这条管线原本在四个地方各写了一遍（新增、更新、批量、导入）。
每次给钩子加一点能力都要改四处，漏掉一处的表现是「某条路径行为不一致」——
而这类不一致**不会报错，只会让数据悄悄分叉**，正是这个项目旧版垮掉的方式。

现在只有这一份：

- `save()`：给接口用，接收**原始提交体**（字符串），自己做校验与默认值补齐；
- `save_validated()`：给导入用，接收**已校验好的值**（预览阶段已按声明解析过）；
- 两条路共用同一个钩子、同一套分流、同一条落库逻辑。

**班级归属在钩子之前解析好放进 `values`**：钩子要能读到它（作业需要按班级取全班人数），
也允许改它（监护人从学生带出班级）。更新时一律不接受客户端改班级。

**钩子可以返回一个回调**，在行落库（拿到 id）之后执行 —— 需要写子表时用得上
（作业的未交名单就是子表）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.api.errors import FIELD_REQUIRED, INVALID_VALUE, UNKNOWN_FIELD, ApiError
from app.schemas.common import split_values
from app.schemas.registry import FieldSpec, TableSpec
from app.services.class_scope import resolve_class_id
from app.services.field_value import CODE_MISSING_REQUIRED, apply_defaults, parse_value

# 这些键由系统管理，出现在提交体里不算「未知字段」，但也不允许客户端直接改
RESERVED_KEYS = frozenset({"id", "class_id", "classId", "created_at", "updated_at", "deleted_at"})

AfterSave = Callable[[Any], None]


def _short(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw)
    return text if len(text) <= 100 else text[:100] + "…"


def coerce(field_spec: FieldSpec, raw: Any) -> Any:
    """按声明解析入参；不合法就抛带中文说明的 ApiError。

    真正的语义在 `services/field_value.py` —— **Excel 导入走的是同一份实现**。
    """
    value, issue = parse_value(field_spec, raw)
    if issue is None:
        return value
    code = FIELD_REQUIRED if issue.code == CODE_MISSING_REQUIRED else INVALID_VALUE
    raise ApiError(code, issue.message, detail={"field": field_spec.k, "value": _short(raw)})


def normalize(spec: TableSpec, payload: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    """校验整个提交体，返回可直接赋给模型的值。

    - `partial=False`（新增）：必填项缺失即报错，其余按声明补默认值；
    - `partial=True`（更新）：只处理传了的字段，**不补默认值**
      （否则一次改「备注」会把没传的字段全重置成默认值）。
    """
    known = spec.field_map
    for key in payload:
        if key in RESERVED_KEYS:
            continue
        if key not in known:
            raise ApiError(UNKNOWN_FIELD, f"未知字段：{key}", detail={"field": key})

    values: dict[str, Any] = {}
    for key, field_spec in known.items():
        if not field_spec.editable:
            continue
        if key in payload:
            values[key] = coerce(field_spec, payload[key])
        elif not partial and field_spec.required:
            raise ApiError(FIELD_REQUIRED, f"「{field_spec.label}」是必填项", detail={"field": key})

    # 默认值补齐与导入预览/提交共用同一实现 —— 曾经两边不一致，
    # 出现「预览显示优先级=中、库里存的是空」这种数据错位
    return values if partial else apply_defaults(spec.fields, values)


@dataclass
class Prepared:
    values: dict[str, Any] = field(default_factory=dict)
    after_save: AfterSave | None = None


def _run_hook(spec: TableSpec, values: dict[str, Any], session: Session, row: Any) -> AfterSave | None:
    if spec.before_save is None:
        return None
    produced = spec.before_save(values, session, row)
    return produced if callable(produced) else None


def apply(spec: TableSpec, session: Session, prepared: Prepared, *, row: Any = None):
    """把准备好的值写进行（新建或更新），返回该行。"""
    columns, payload = split_values(spec, prepared.values)
    if row is None:
        row = spec.model(**columns)
        if payload and spec.json_column:
            setattr(row, spec.json_column, payload)
        session.add(row)
    else:
        for key, value in columns.items():
            setattr(row, key, value)
        if payload and spec.json_column:
            # JSON 字段是**合并**而不是覆盖：没提交的字段保持原值
            merged = dict(getattr(row, spec.json_column) or {})
            merged.update(payload)
            setattr(row, spec.json_column, merged)

    session.flush()  # 钩子回调要拿到 id，所以先落一次

    if prepared.after_save is not None:
        prepared.after_save(row)
        session.flush()
    return row


def prepare(
    spec: TableSpec,
    session: Session,
    payload: dict[str, Any],
    *,
    partial: bool,
    row: Any = None,
    class_id_raw: Any = None,
) -> Prepared:
    """把原始提交体准备成「要写入的值」。不落库。"""
    values = normalize(spec, payload, partial=partial)

    if spec.class_scoped and row is None:
        # 新建：先把班级定下来，钩子才读得到（也允许钩子改它）
        values["class_id"] = resolve_class_id(spec, class_id_raw, session)
    else:
        # 非班级范围的表 / 更新：都不接受客户端指定班级
        # （更新时改班级会让一条记录悄悄换班，而不是报错）
        values.pop("class_id", None)

    return Prepared(values=values, after_save=_run_hook(spec, values, session, row))


def save(
    spec: TableSpec,
    session: Session,
    payload: dict[str, Any],
    *,
    partial: bool,
    row: Any = None,
    class_id_raw: Any = None,
):
    """接口用：原始提交体 → 落库后的行。"""
    prepared = prepare(spec, session, payload, partial=partial, row=row, class_id_raw=class_id_raw)
    return apply(spec, session, prepared, row=row)


def save_validated(
    spec: TableSpec,
    session: Session,
    values: dict[str, Any],
    *,
    class_id: int | None = None,
    row: Any = None,
):
    """导入用：**已校验好的值** → 落库后的行。

    预览阶段已经按声明解析过一遍（`import_service._validate`），这里再 normalize 一次
    只会把日期对象当字符串重解析，反而容易出岔子；但**钩子与分流必须共用**，
    否则两条路会分叉。
    """
    working = dict(values)
    if spec.class_scoped and row is None:
        working["class_id"] = class_id
    else:
        working.pop("class_id", None)
    prepared = Prepared(values=working, after_save=_run_hook(spec, working, session, row))
    return apply(spec, session, prepared, row=row)
