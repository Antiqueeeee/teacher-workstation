"""表声明用的三个类型（列 / 字段 / 整张表）。

单独成模块，`schemas/registry.py` 只做汇总与访问器，各域的声明在 `schemas/specs/`。
**既有代码继续 `from app.schemas.registry import FieldSpec` 也没问题** ——
registry 把这三个类型原样再导出，改 import 路径不是这次拆分的目的。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.db.base import Base


FIELD_TYPES = (
    "text",
    "number",
    "textarea",
    "select",
    "checkbox",
    "date",
    "bedno",
    # 金额：界面填「元」，库里存「分」（整数）—— 浮点算钱会出现小数尾数
    "money",
)


@dataclass(frozen=True)
class ColumnSpec:
    """列表页的一列。"""

    k: str
    label: str
    w: str | None = None
    numeric: bool = False
    sortable: bool = True


@dataclass(frozen=True)
class FieldSpec:
    """表单/导入的一个字段。"""

    k: str
    label: str
    type: str = "text"
    required: bool = False
    options: tuple[str, ...] = ()
    default: Any = None
    full: bool = False          # 表单里占整行
    hint: str = ""
    editable: bool = True       # 只读字段（如系统生成的计数）
    # Excel 表头别名。内建表写在 table_io.ALIASES，动态字段（如学生档案）
    # 由字段定义带进来 —— 两处最终都汇到 table_io.build_alias_index
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableSpec:
    """一张表的完整声明。"""

    key: str                     # URL 与前端 cfg 的 key，如 "todos"
    model: type[Base]
    title: str                   # 页面标题
    entity: str                  # 单数称呼，用于文案
    columns: tuple[ColumnSpec, ...] = ()
    fields: tuple[FieldSpec, ...] = ()
    search_keys: tuple[str, ...] = ()          # 关键词搜索覆盖的列
    filter_keys: tuple[str, ...] = ()          # 允许 filter.<k> 精确筛选的列
    default_sort: tuple[str, int] = ("id", -1)  # (列, 方向) 方向 1=升序 -1=降序
    class_scoped: bool = True                  # 是否属于某个班级
    soft_delete: bool = True
    dedupe_keys: tuple[str, ...] = ()          # 导入时的「判重键」：同键视为同一条记录，跳过而不是重复插入
    extra_keys: tuple[str, ...] = field(default_factory=tuple)  # 输出里额外带的列
    # 保存前的派生/校验钩子（旧应用的 beforeSave 就是这个位置）。
    # 签名：before_save(values: dict, session: Session, row: 现有记录 | None) -> None
    # 可以改 values、也可以抛 ApiError；新增、更新、导入提交三条路径都会调用它。
    # 用途举例：监护人把「学生姓名」解析成 student_id 并带出 class_id。
    before_save: Any = None
    # 删除前的钩子（签名 ，可以抛 ApiError 拒绝）。
    # 用途：有些表删一条会牵连别的表的状态，又不能在数据库层用外键表达 ——
    # 例如「删宿舍房间」会让那间房的人从看板上消失，所以要在这里挡住。
    before_delete: Any = None
    # 这张表的记录可以挂附件（照片/录音归档）。通用列表据此显示附件数与附件入口，
    # 并在序列化前批量填 `attachment_count`（不是每条记录查一次）。
    # 支持哪些附件类型由媒体服务按 kind 判断，这里只声明「能挂」。
    media_owner: bool = False
    # 有些表的字段存在一个 JSON 列里（学生档案的 `extra`）：字段定义在运行时可变，
    # 建成列就等于每加一个字段改一次表结构。声明后，搜索 / 排序 / 筛选 / 序列化
    # 都会自动走 `json_extract`，不必为该表写一套特例。
    json_column: str | None = None
    json_fields: frozenset[str] = frozenset()

    @property
    def sortable_keys(self) -> frozenset[str]:
        """允许出现在 `sort=` 里的键。

        除了声明为可排序的列与时间戳，还包括**声明成不可编辑、但确实是真实列的字段**
        （宿舍值日的 `weekday_no` 就是这种：界面上不单独占一列 —— 它显示的是
        「星期」汉字 —— 但排序要用序号，用汉字排是按码位排，星期五会跑到星期一前面）。
        派生属性不在此列：它们构不出 SQL（另有看门测试拦着）。
        """
        generated = {
            field_spec.k
            for field_spec in self.fields
            if not field_spec.editable and field_spec.k in self.model.__table__.columns
        }
        return frozenset(
            {c.k for c in self.columns if c.sortable} | generated | {"id", "created_at", "updated_at"}
        )

    @property
    def field_map(self) -> dict[str, FieldSpec]:
        return {f.k: f for f in self.fields}

    @property
    def output_keys(self) -> tuple[str, ...]:
        keys = ["id"]
        if self.class_scoped:
            keys.append("class_id")
        keys += [c.k for c in self.columns]
        keys += [f.k for f in self.fields if f.k not in {c.k for c in self.columns}]
        keys += [k for k in self.extra_keys if k not in keys]
        if self.media_owner:
            # 支持附件的表自动带上附件数 —— 加模块的人不必记得再声明一次
            keys.append("attachment_count")
        if self.soft_delete:
            # 前端要靠它区分「已删除」并给出恢复入口（软删除不能没有出口）
            keys.append("deleted_at")
        keys += ["created_at", "updated_at"]
        return tuple(dict.fromkeys(keys))

    def to_dict(self) -> dict[str, Any]:
        """给前端的形状（`GET /api/v1/meta/registry`），可直接当页面 cfg 用。"""
        return {
            "key": self.key,
            "title": self.title,
            "entity": self.entity,
            "classScoped": self.class_scoped,
            # 前端要靠它决定「删除确认框怎么说」：能恢复的表说「可以找回」，
            # 不能恢复的表必须说清是彻底删掉（说反了就是骗人）
            "softDelete": self.soft_delete,
            # 这张表的记录能不能挂附件（照片/录音归档）—— 列表据此显示附件入口
            "mediaOwner": self.media_owner,
            "defaultSort": {"k": self.default_sort[0], "dir": self.default_sort[1]},
            "columns": [asdict(column) for column in self.columns],
            "fields": [asdict(field_spec) for field_spec in self.fields],
            "filterKeys": list(self.filter_keys),
            "searchKeys": list(self.search_keys),
        }
