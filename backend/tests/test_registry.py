"""注册表自洽测试。

注册表是全项目的单一事实来源（路由、校验、表单、词表、默认值都看它），
所以「注册表自己写错了没有」必须有测试守住 —— 这类错误不会抛异常，
只会让数据悄悄变歪。

下面的断言来自两个真实踩过的坑：
- 改了词表忘改默认值 → 库里出现词表外的值（`rule.category` 曾默认「其他」，
  而真实词表里没有「其他」；新增接口又不过选项校验，所以永远抓不到）；
- 声明里写了模型上没有的列 → 运行期 AttributeError 或筛选静默失效。
"""

from __future__ import annotations

import pytest

from app.schemas.registry import TABLES
from app.services.field_value import parse_value

SPECS = list(TABLES.values())
SPEC_IDS = [spec.key for spec in SPECS]


def columns_of(spec) -> set[str]:
    return set(spec.model.__table__.columns.keys())


@pytest.mark.parametrize("spec", SPECS, ids=SPEC_IDS)
def test_every_declared_key_exists_on_model(spec):
    available = columns_of(spec)
    declared = (
        [column.k for column in spec.columns]
        + [field.k for field in spec.fields]
        + list(spec.search_keys)
        + list(spec.filter_keys)
        + list(spec.dedupe_keys)
        + list(spec.extra_keys)
        + list(spec.output_keys)
    )
    missing = sorted({key for key in declared if key not in available})
    assert not missing, f"声明里有模型上不存在的列：{missing}"


@pytest.mark.parametrize("spec", SPECS, ids=SPEC_IDS)
def test_select_fields_declare_options(spec):
    for field in spec.fields:
        if field.type == "select":
            assert field.options, f"{field.k}: select 必须声明 options，否则无从校验"


@pytest.mark.parametrize("spec", SPECS, ids=SPEC_IDS)
def test_defaults_are_valid_values(spec):
    """默认值必须落在词表/格式允许的范围内 —— 这条就是拦住那个真实踩过的坑。"""
    for field in spec.fields:
        if field.default is None:
            continue
        _, issue = parse_value(field, field.default)
        assert issue is None, f"{field.k}: 默认值不合法 —— {issue.message}"


@pytest.mark.parametrize("spec", SPECS, ids=SPEC_IDS)
def test_filter_and_sort_keys_are_usable(spec):
    assert spec.default_sort[0] in spec.sortable_keys, "默认排序键不可排序"
    for key in spec.filter_keys:
        assert key in spec.field_map, f"筛选键 {key} 没有对应的字段声明"


@pytest.mark.parametrize("spec", SPECS, ids=SPEC_IDS)
def test_model_default_agrees_with_registry_default(spec):
    """模型列上的 Python 默认值不能和注册表声明冲突 —— 两处描述同一件事就会漂。"""
    for field in spec.fields:
        column = spec.model.__table__.columns.get(field.k)
        if column is None or column.default is None or field.default is None:
            continue
        model_default = column.default.arg
        if callable(model_default):
            continue
        assert str(model_default) == str(field.default), (
            f"{field.k}: 模型默认值 {model_default!r} 与注册表默认值 {field.default!r} 不一致"
        )


@pytest.mark.parametrize("spec", SPECS, ids=SPEC_IDS)
def test_class_scoped_flag_matches_model(spec):
    """`class_scoped` 与模型上是否真有 class_id 必须一致，否则会写进一个不存在的班。"""
    has_class_id = "class_id" in columns_of(spec)
    assert spec.class_scoped == has_class_id, (
        f"class_scoped={spec.class_scoped}，但模型{'有' if has_class_id else '没有'} class_id"
    )
