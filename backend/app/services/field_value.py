"""字段值的解析与校验 —— **API 与 Excel 导入共用同一套语义**。

为什么单独抽出来：同一份「这个字段是什么意思」（下拉范围、日期格式、布尔写法、长度上限）
如果在新增加接口、编辑接口、导入里各写一遍，迟早三份不一致 ——
旧应用 40 条缺陷里反复出现的就是这个模式（同一个「提交率」有五套算法）。

约定：解析函数**不抛异常**，返回 `(值, ValueIssue | None)`，让调用方自己决定
是「弹错误」还是「记进导入报告」。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.schemas.registry import FieldSpec

# 床位号之类「老师会写中文」的整数：取第一段数字（见 `_parse_bed_no`）
BED_NUMBER = re.compile(r"\d+")

# 布尔的中文/数字/英文写法（表单、Excel、旧数据里都出现过）
TRUE_WORDS = {"1", "true", "yes", "y", "是", "已完成", "已缴", "已交", "有"}
FALSE_WORDS = {"0", "false", "no", "n", "否", "未完成", "未缴", "未交", "无", ""}

DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日", "%Y%m%d")

# 文本长度上限：挡住「一次粘贴十万字」把库和页面撑爆
MAX_LENGTH = {"text": 2000, "textarea": 20000}
DATE_EXAMPLE = "2026-09-01"

CODE_MISSING_REQUIRED = "MISSING_REQUIRED"
CODE_INVALID_VALUE = "INVALID_VALUE"
CODE_TOO_LONG = "TOO_LONG"


@dataclass(frozen=True)
class ValueIssue:
    code: str
    message: str


def is_empty(raw: Any) -> bool:
    """空值判定：None 与「纯空白字符串」算空，`0` 和 `False` 不算空。"""
    return raw is None or (isinstance(raw, str) and not raw.strip())


def _missing(field: FieldSpec) -> ValueIssue:
    return ValueIssue(CODE_MISSING_REQUIRED, f"「{field.label}」是必填项")


def _parse_bool(field: FieldSpec, raw: Any) -> tuple[Any, ValueIssue | None]:
    if isinstance(raw, bool):
        return raw, None
    if isinstance(raw, (int, float)):
        return bool(raw), None
    if is_empty(raw):
        return False, None
    text = str(raw).strip().lower()
    if text in TRUE_WORDS:
        return True, None
    if text in FALSE_WORDS:
        return False, None
    return None, ValueIssue(CODE_INVALID_VALUE, f"「{field.label}」只能填是/否（当前：{raw}）")


def _parse_number(field: FieldSpec, raw: Any) -> tuple[Any, ValueIssue | None]:
    if is_empty(raw):
        return (None, _missing(field)) if field.required else (None, None)
    text = str(raw).strip().replace(",", "").replace("，", "")
    try:
        if "." in text:
            number = float(text)
            if not number.is_integer():
                return None, ValueIssue(CODE_INVALID_VALUE, f"「{field.label}」需要是整数（当前：{raw}）")
            return int(number), None
        return int(text), None
    except ValueError:
        return None, ValueIssue(CODE_INVALID_VALUE, f"「{field.label}」需要是数字（当前：{raw}）")


def _parse_money(field: FieldSpec, raw: Any) -> tuple[Any, ValueIssue | None]:
    """金额：用户填**元**，存**分**（整数）。

    为什么单独一个类型而不是用 `number`：`number` 是整数专用的（人数、床位号那种），
    `1200.50` 会被它判成「需要是整数」。金额也不能存浮点的元 ——
    `0.1 + 0.2` 在浮点里是 `0.30000000000000004`，而这是要跟家长对账的钱。
    """
    if is_empty(raw):
        return (None, _missing(field)) if field.required else (0, None)
    text = (
        str(raw).strip().replace(",", "").replace("，", "").replace("¥", "").replace("元", "")
    )
    try:
        return int(round(float(text) * 100)), None
    except ValueError:
        return None, ValueIssue(
            CODE_INVALID_VALUE, f"「{field.label}」要填数字（元），如 1200 或 1200.50"
        )


def _parse_bed_no(field: FieldSpec, raw: Any) -> tuple[Any, ValueIssue | None]:
    """床位号 / 房间序号这类整数，但**容忍中文写法**：「1号床」「01」「床 1」都认。

    取第一段数字（旧应用的 `:13645` 就是这么解析的），所以「1号床（靠窗）」→ 1 ——
    老师的表里就是这种写法，这个宽容度要保留。

    区别在于认不出来时**报错**：旧应用把「靠窗」解析成 0，那条记录从此在网格里
    看不见、还会让满员判定出错，而界面上没有任何提示。
    """
    if is_empty(raw):
        return (None, _missing(field)) if field.required else (None, None)
    if isinstance(raw, bool):
        return None, ValueIssue(CODE_INVALID_VALUE, f"「{field.label}」要填数字")
    if isinstance(raw, int):
        return raw, None
    if isinstance(raw, float):
        if float(raw).is_integer():
            return int(raw), None
        return None, ValueIssue(CODE_INVALID_VALUE, f"「{field.label}」需要是整数（当前：{raw}）")

    match = BED_NUMBER.search(str(raw))
    if not match:
        return None, ValueIssue(
            CODE_INVALID_VALUE,
            f"认不出的「{field.label}」「{raw}」。请填数字，例如 1 或 1号床。",
        )
    return int(match.group()), None


def _parse_date(field: FieldSpec, raw: Any) -> tuple[Any, ValueIssue | None]:
    if is_empty(raw):
        return (None, _missing(field)) if field.required else (None, None)
    if isinstance(raw, datetime):
        return raw.date(), None
    if isinstance(raw, date):
        return raw, None
    text = str(raw).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date(), None
        except ValueError:
            continue
    return None, ValueIssue(
        CODE_INVALID_VALUE, f"「{field.label}」日期格式不对（当前：{text}，应形如 {DATE_EXAMPLE}）"
    )


def _parse_text(field: FieldSpec, raw: Any) -> tuple[Any, ValueIssue | None]:
    text = "" if raw is None else str(raw).strip()
    if not text:
        return ("", _missing(field)) if field.required else ("", None)
    if field.options and text not in field.options:
        return None, ValueIssue(
            CODE_INVALID_VALUE, f"「{field.label}」只能填：{'、'.join(field.options)}（当前：{text}）"
        )
    limit = MAX_LENGTH.get(field.type, 2000)
    if len(text) > limit:
        return None, ValueIssue(CODE_TOO_LONG, f"「{field.label}」超过 {limit} 字（当前 {len(text)} 字）")
    return text, None


def parse_value(field: FieldSpec, raw: Any) -> tuple[Any, ValueIssue | None]:
    """按字段声明解析单个值。返回 `(值, 问题)`，问题为 None 表示通过。"""
    if field.type == "checkbox":
        return _parse_bool(field, raw)
    if field.type == "number":
        return _parse_number(field, raw)
    if field.type == "date":
        return _parse_date(field, raw)
    if field.type == "bedno":
        return _parse_bed_no(field, raw)
    if field.type == "money":
        return _parse_money(field, raw)
    return _parse_text(field, raw)


def apply_defaults(fields: tuple[FieldSpec, ...], values: dict[str, Any]) -> dict[str, Any]:
    """按声明补齐缺省值 —— **唯一实现**，CRUD 新增、导入预览、导入提交三处共用。

    必须共用：曾经预览补了默认值、提交没补，于是出现「预览显示优先级=中、
    库里存的是空字符串」——筛选和 KPI 都按「中」查，查不到它。同一规则两处实现，
    结果就是两条路径产生两种数据。

    默认值本身也过一遍解析，防止「默认值不在词表里」这种声明错误
    （另有 `tests/test_registry.py` 的自洽测试在 CI 里兜底）。
    """
    for field_spec in fields:
        if not field_spec.editable or field_spec.k in values or field_spec.default is None:
            continue
        parsed, issue = parse_value(field_spec, field_spec.default)
        if issue is None:
            values[field_spec.k] = parsed
    return values
