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

from app.schemas.registry import all_specs
from app.services.field_value import parse_value

# 用 all_specs() 而不是 TABLES：**动态表（学生档案）也要被这套断言覆盖** ——
# 它的字段定义是数据，更容易写歪，却最容易被漏掉
SPECS = all_specs()
SPEC_IDS = [spec.key for spec in SPECS]


def columns_of(spec) -> set[str]:
    """模型上真实存在的字段：真实列 + 声明为 JSON 存储的字段 + **派生属性**。

    JSON 字段（学生档案的 `extra` 内容）不是列，但同样是「存得住」的字段；
    派生属性（如作业的未交名单、未交人数）由关系算出来，也是可输出的字段。
    自洽检查必须把这三种都算进来，否则会把合法声明误判成错的。
    """
    available = set(spec.model.__table__.columns.keys()) | set(spec.json_fields)
    # 注意是 spec.model.__mro__（类自身的继承链）；
    # 写成 type(spec.model).__mro__ 会拿到**元类**的 MRO，什么都找不到（踩过）
    for klass in spec.model.__mro__:
        for name, attribute in vars(klass).items():
            if isinstance(attribute, property):
                available.add(name)
    return available


def sql_expressible(spec) -> set[str]:
    """能进 SQL 的字段：真实列 + JSON 字段。**派生属性不在其中。**"""
    return set(spec.model.__table__.columns.keys()) | set(spec.json_fields)


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
def test_sortable_and_searched_keys_must_be_sql_expressible(spec):
    """能排序 / 筛选 / 搜索的列必须是**真实列或 JSON 字段**，不能是派生属性。

    派生属性（如作业的未交名单）在 Python 里读得到，但 `field_expr` 取到的是
    property 对象，构不出 SQL —— 一旦声明成可排序，用户点一下表头就是
    AttributeError → 500「服务内部错误」。这个错真实发生过一次，
    而且点完之后前端会把那个排序键记在 state 里，这个页面再也刷不出列表。
    """
    usable = sql_expressible(spec)
    for column in spec.columns:
        if column.sortable:
            assert column.k in usable, (
                f"{spec.key}.{column.k} 声明为可排序，但它不是真实列/JSON 字段 —— 点了会 500"
            )
    assert spec.default_sort[0] in usable, f"{spec.key} 的默认排序键不是真实列/JSON 字段"
    for key in spec.search_keys:
        assert key in usable, f"{spec.key} 的搜索键 {key} 不是真实列/JSON 字段"
    for key in spec.filter_keys:
        assert key in usable, f"{spec.key} 的筛选键 {key} 不是真实列/JSON 字段"


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


def test_registry_payload_carries_what_the_frontend_needs():
    """`/meta/registry` 是前端的唯一配置来源，键名就是前后端的契约。

    少一个键，前端是**静默**降级：比如少了 `softDelete`，删除确认框会对一张
    不软删除的表承诺「记录还在库里、可以恢复」——文案与真实行为不符，
    而这种错误没有任何测试会抓到（因为它们本来就不该靠人眼发现）。
    """
    spec_keys = {
        "key", "title", "entity", "classScoped", "softDelete",
        "columns", "fields", "filterKeys", "searchKeys", "defaultSort",
    }
    column_keys = {"k", "label", "w", "numeric", "sortable"}
    field_keys = {
        "k", "label", "type", "required", "options", "default",
        "full", "hint", "editable", "aliases",
    }
    for spec in SPECS:
        payload = spec.to_dict()
        assert spec_keys <= set(payload), f"{spec.key} 的输出少了 {spec_keys - set(payload)}"
        assert payload["key"] == spec.key
        assert payload["defaultSort"] == {"k": spec.default_sort[0], "dir": spec.default_sort[1]}
        for column in payload["columns"]:
            assert column_keys <= set(column), f"{spec.key}.{column.get('k')} 的列声明不完整"
        for field in payload["fields"]:
            assert field_keys <= set(field), f"{spec.key}.{field.get('k')} 的字段声明不完整"
