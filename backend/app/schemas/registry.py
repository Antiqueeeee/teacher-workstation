"""表注册表：所有表声明的**汇总点**与访问器。

为什么要有它：旧应用里每个模块都手写一遍「列 / 字段 / 筛选项 / 校验」，同一个口径散在
多处；这里把「这张表长什么样」集中成数据，后端据此生成路由、前端据此渲染列表与表单
（见 `docs/改造方案/03` §5.1 的 `/meta/registry`）。

**新增一张表 = 加一个模型 + 在 `schemas/specs/` 对应的域里加一条 `TableSpec` +
在下头的 `TABLES` 里挂上它**，不需要写 CRUD 代码。

文件怎么分的（`CONTRIBUTING.md` §3 的「按聚合分」）：
- `schemas/table_spec.py`：`ColumnSpec` / `FieldSpec` / `TableSpec` 三个类型；
- `schemas/specs/classroom.py`：待办、班规、话术模板
- `schemas/specs/contact.py`：家长通讯
- `schemas/specs/teaching.py`：作业、出勤、考试
- `schemas/specs/dorm.py`：宿舍房间、床位、值日、座位
- 本文件：汇总成 `TABLES`、动态表注册表、`get_spec` / `all_specs`
"""

from __future__ import annotations

from typing import Any

from app.schemas.specs.class_roles import CADRE, DUTY, YOUTH
from app.schemas.specs.classroom import RULE, TEMPLATE, TODO
from app.schemas.specs.contact import CONTACT, GUARDIAN
from app.schemas.specs.student_records import DISCIPLINE, GRANT, HEALTH
from app.schemas.specs.dorm import DORM_BED, DORM_DUTY, DORM_ROOM, SEAT
from app.schemas.specs.teaching import ATTENDANCE, EXAM, HOMEWORK
from app.schemas.table_spec import FIELD_TYPES, ColumnSpec, FieldSpec, TableSpec

# 重新导出：老代码里的 `from app.schemas.registry import FieldSpec` 继续可用
__all__ = [
    "FIELD_TYPES",
    "ColumnSpec",
    "FieldSpec",
    "TableSpec",
    "TODO",
    "RULE",
    "TEMPLATE",
    "GUARDIAN",
    "CONTACT",
    "HOMEWORK",
    "ATTENDANCE",
    "EXAM",
    "DORM_ROOM",
    "DORM_BED",
    "DORM_DUTY",
    "SEAT",
    "CADRE",
    "YOUTH",
    "DUTY",
    "DISCIPLINE",
    "HEALTH",
    "GRANT",
    "TABLES",
    "DYNAMIC_TABLES",
    "get_spec",
    "all_specs",
]


TABLES: dict[str, TableSpec] = {
    spec.key: spec
    for spec in (
        TODO,
        RULE,
        TEMPLATE,
        GUARDIAN,
        CONTACT,
        HOMEWORK,
        ATTENDANCE,
        EXAM,
        DORM_ROOM,
        DORM_BED,
        DORM_DUTY,
        SEAT,
        CADRE,
        YOUTH,
        DUTY,
        DISCIPLINE,
        HEALTH,
        GRANT,
    )
}

# 字段定义存在数据库里的表（学生档案）：spec 每次请求**现算**。
# 否则老师在字段管理里加了一个字段，要重启服务才生效 —— 而他并不知道要重启。
DYNAMIC_TABLES: dict[str, Any] = {}


def get_spec(key: str) -> TableSpec | None:
    if key in TABLES:
        return TABLES[key]
    provider = DYNAMIC_TABLES.get(key)
    return provider() if provider else None


def all_specs() -> list[TableSpec]:
    """全部表声明（静态 + 动态现算），供 `/meta/registry` 与自洽测试使用。"""
    return list(TABLES.values()) + [provider() for provider in DYNAMIC_TABLES.values()]
