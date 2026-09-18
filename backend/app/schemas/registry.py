"""表注册表：一张表的所有「声明式」信息，是通用 CRUD 与前端 cfg 的唯一来源。

为什么要有它：
- 旧应用里每个模块都手写一遍「列 / 字段 / 筛选项 / 校验」，同一个口径散在多处；
- 这里把「这张表长什么样」集中成数据，后端据此生成路由、前端据此渲染列表与表单
  （见 `docs/改造方案/03-目标架构与代码组织.md` §5.1 的 `/meta/registry`）。

新增一张表 = 加一个模型 + 在 `TABLES` 里加一条 `TableSpec`，不需要写 CRUD 代码。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.db.base import Base
from app.models.attendance import ATTENDANCE_TYPES, FOLLOW_UP_STATES, PERIODS, Attendance
from app.models.exam import EXAM_KINDS, Exam
from app.models.guardian import ROLES as GUARDIAN_ROLES
from app.models.guardian import Guardian
from app.models.homework import QUALITIES, RATE_MODES, SUBJECTS, Homework
from app.models.rule import CATEGORIES as RULE_CATEGORIES
from app.models.rule import Rule
from app.models.template import CATEGORIES as TEMPLATE_CATEGORIES
from app.models.template import TONES as TEMPLATE_TONES
from app.models.template import Template
from app.models.todo import PRIORITIES, Todo
from app.services.attendance_service import apply_attendance
from app.services.exam_service import apply_exam
from app.services.guardian_service import link_student
from app.services.homework_service import apply_homework

# 字段类型（与前端 field 渲染器一一对应）
FIELD_TYPES = ("text", "number", "textarea", "select", "checkbox", "date")


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
    # 有些表的字段存在一个 JSON 列里（学生档案的 `extra`）：字段定义在运行时可变，
    # 建成列就等于每加一个字段改一次表结构。声明后，搜索 / 排序 / 筛选 / 序列化
    # 都会自动走 `json_extract`，不必为该表写一套特例。
    json_column: str | None = None
    json_fields: frozenset[str] = frozenset()

    @property
    def sortable_keys(self) -> frozenset[str]:
        return frozenset({c.k for c in self.columns if c.sortable} | {"id", "created_at", "updated_at"})

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
            "defaultSort": {"k": self.default_sort[0], "dir": self.default_sort[1]},
            "columns": [asdict(column) for column in self.columns],
            "fields": [asdict(field_spec) for field_spec in self.fields],
            "filterKeys": list(self.filter_keys),
            "searchKeys": list(self.search_keys),
        }


TODO = TableSpec(
    key="todos",
    model=Todo,
    title="待办任务",
    entity="待办",
    columns=(
        ColumnSpec("content", "内容"),
        ColumnSpec("due_date", "截止日期", w="110px", numeric=True),
        ColumnSpec("priority", "优先级", w="80px"),
        ColumnSpec("done", "状态", w="90px"),
        ColumnSpec("note", "备注"),
    ),
    fields=(
        FieldSpec("content", "内容", required=True),
        FieldSpec("due_date", "截止日期", type="date"),
        FieldSpec("priority", "优先级", type="select", options=PRIORITIES, default="中"),
        FieldSpec("done", "已完成", type="checkbox", default=False),
        FieldSpec("note", "备注", type="textarea"),
    ),
    search_keys=("content", "note"),
    filter_keys=("priority", "done"),
    default_sort=("id", -1),
    dedupe_keys=("content", "due_date"),  # 同内容 + 同截止日视为同一条，重复导入不会翻倍
)

RULE = TableSpec(
    key="rules",
    model=Rule,
    title="班规制度",
    entity="班规",
    columns=(
        ColumnSpec("category", "类别", w="90px"),
        ColumnSpec("title", "标题"),
        ColumnSpec("version", "版本", w="80px"),
        ColumnSpec("effective_from", "生效日期", w="110px", numeric=True),
        ColumnSpec("effective_to", "失效日期", w="110px", numeric=True),
        ColumnSpec("content", "内容"),
    ),
    fields=(
        FieldSpec("category", "类别", type="select", options=RULE_CATEGORIES),
        FieldSpec("title", "标题", required=True),
        FieldSpec("version", "版本"),
        FieldSpec("effective_from", "生效日期", type="date"),
        FieldSpec("effective_to", "失效日期", type="date"),
        FieldSpec("content", "内容", type="textarea", full=True),
    ),
    search_keys=("title", "content"),
    filter_keys=("category",),
    default_sort=("id", -1),
    dedupe_keys=("category", "title"),  # 同类同标题视为同一条班规
)

TEMPLATE = TableSpec(
    key="templates",
    model=Template,
    title="话术模板库",
    entity="模板",
    columns=(
        ColumnSpec("title", "标题"),
        ColumnSpec("category", "场景", w="100px"),
        ColumnSpec("tone", "语气", w="100px"),
        ColumnSpec("use_count", "使用次数", w="90px", numeric=True),
        ColumnSpec("content", "内容"),
    ),
    fields=(
        FieldSpec("title", "标题", required=True),
        FieldSpec("category", "场景", type="select", options=TEMPLATE_CATEGORIES),
        FieldSpec("tone", "语气", type="select", options=TEMPLATE_TONES),
        FieldSpec("content", "内容", type="textarea", full=True, required=True),
        FieldSpec("use_count", "使用次数", type="number", default=0, editable=False),
    ),
    search_keys=("title", "content"),
    filter_keys=("category", "tone"),
    default_sort=("id", -1),
    class_scoped=False,  # 话术模板是全班共享的素材，不属于某个班级
    dedupe_keys=("title",),  # 同标题视为同一条模板
)

HOMEWORK = TableSpec(
    key="homework",
    model=Homework,
    title="作业情况",
    entity="作业",
    columns=(
        ColumnSpec("date", "布置日期", w="104px", numeric=True),
        ColumnSpec("subject", "科目", w="70px"),
        ColumnSpec("content", "作业内容"),
        ColumnSpec("total", "应交", w="62px", numeric=True),
        ColumnSpec("unsubmitted_names", "未交名单"),
        ColumnSpec("rate", "提交率", w="78px", numeric=True),
        ColumnSpec("quality", "质量", w="62px"),
    ),
    fields=(
        FieldSpec("date", "布置日期", type="date", required=True),
        FieldSpec("subject", "科目", type="select", options=SUBJECTS, required=True),
        FieldSpec("content", "作业内容", type="textarea", full=True, required=True),
        FieldSpec("deadline", "截止时间", hint="如 次日早读前"),
        FieldSpec("total", "应交人数", type="number", hint="留空按当前全班人数"),
        FieldSpec(
            "unsubmitted_names",
            "未交名单",
            type="textarea",
            full=True,
            hint="多人用顿号分隔；全部交齐填「无」。提交率由它自动算出，不用手填",
        ),
        FieldSpec(
            "rate_mode",
            "提交率模式",
            type="select",
            options=RATE_MODES,
            default="自动",
            hint="手工只用于特殊情况（如学校要求按人数上报）",
        ),
        FieldSpec("rate_manual", "手工提交率（%）", type="number"),
        # 计算出来的值：不让人填（editable=False），但声明成字段，导出的文件再导回来时
        # 这一列会被认出来并忽略，而不是报「认不出这一列」
        FieldSpec("rate", "提交率（%）", type="number", editable=False),
        FieldSpec("quality", "完成质量", type="select", options=QUALITIES, default="良"),
        FieldSpec("teacher", "布置教师"),
    ),
    search_keys=("content", "teacher"),
    filter_keys=("subject", "quality"),
    default_sort=("date", -1),
    dedupe_keys=("date", "subject", "content"),  # 同一天同一科同一份作业，重复导入不翻倍
    before_save=apply_homework,
)

ATTENDANCE = TableSpec(
    key="attendance",
    model=Attendance,
    title="出勤记录",
    entity="考勤记录",
    columns=(
        ColumnSpec("date", "日期", w="104px", numeric=True),
        ColumnSpec("student_name", "学生", w="92px"),
        ColumnSpec("type", "类型", w="70px"),
        ColumnSpec("period", "节次", w="92px"),
        ColumnSpec("reason", "事由"),
        ColumnSpec("handled", "跟进状态", w="92px"),
        ColumnSpec("handled_note", "处理情况"),
    ),
    fields=(
        FieldSpec("date", "日期", type="date", required=True),
        # 与家长通讯同一套做法：填姓名，钩子解析成 student_id，重名时明确报错
        FieldSpec("student_name", "学生", required=True, hint="填学生姓名；重名时会提示确认"),
        FieldSpec("type", "类型", type="select", options=ATTENDANCE_TYPES, required=True),
        FieldSpec(
            "period",
            "节次",
            type="select",
            options=PERIODS,
            default="全天",
            hint="只作留档，不参与统计",
        ),
        FieldSpec("reason", "事由", type="textarea", full=True, hint="如：发热就医、家中有事"),
        FieldSpec(
            "handled",
            "跟进状态",
            type="select",
            options=FOLLOW_UP_STATES,
            hint="留空按类型自动判定：旷课为「待联系」，其余为「无需联系」",
        ),
        FieldSpec(
            "handled_note",
            "处理情况",
            type="textarea",
            full=True,
            hint="如：已电话联系家长确认",
        ),
    ),
    search_keys=("student_name", "reason", "handled_note"),
    filter_keys=("type", "period", "handled"),
    default_sort=("date", -1),
    # 刻意不软删除：UNIQUE(date, student_id) 与软删除冲突 —— 删掉的记录仍占着唯一键，
    # 同一天同一个学生就再也登记不进来（见 models/attendance.py）
    soft_delete=False,
    dedupe_keys=("date", "student_name"),  # 一天一个学生只有一条，重复导入不翻倍
    extra_keys=("student_id",),            # 点名表要按学生 id 匹配
    before_save=apply_attendance,
)

EXAM = TableSpec(
    key="exams",
    model=Exam,
    title="考试管理",
    entity="考试",
    columns=(
        ColumnSpec("name", "考试名称"),
        ColumnSpec("date", "日期", w="104px", numeric=True),
        ColumnSpec("kind", "类型", w="80px"),
        ColumnSpec("note", "备注"),
    ),
    fields=(
        FieldSpec("name", "考试名称", required=True, full=True, hint="如：2026 学年第二学期期末考"),
        FieldSpec("date", "考试日期", type="date", required=True),
        FieldSpec("kind", "考试类型", type="select", options=EXAM_KINDS, default="月考"),
        FieldSpec("note", "备注", type="textarea", full=True),
    ),
    search_keys=("name", "note"),
    filter_keys=("kind",),
    default_sort=("date", -1),
    dedupe_keys=("date", "name"),  # 同一天同名视为同一场，重复导入不翻倍
    # 新建考试时按词表把科目表建出来（考试考哪几科必须当场确定，见 exam_service）
    before_save=apply_exam,
)

GUARDIAN = TableSpec(
    key="guardians",
    model=Guardian,
    title="家长通讯",
    entity="监护人",
    columns=(
        ColumnSpec("student_name", "学生", w="90px"),
        ColumnSpec("name", "姓名"),
        ColumnSpec("role", "关系", w="76px"),
        ColumnSpec("phone", "电话", w="130px"),
        ColumnSpec("job", "工作单位", w="130px"),
        ColumnSpec("is_primary", "主要联系人", w="100px"),
        ColumnSpec("note", "备注"),
    ),
    fields=(
        # 表单里填的是**学生姓名**，不是 id —— 老师记的是名字。
        # student_id / class_id 由 services/guardian_service.py 的 before_save 解析出来，
        # 同名学生会明确报错让人确认，而不是随便挂到一个同名学生身上
        FieldSpec("student_name", "学生", required=True, hint="填学生姓名；重名时会提示确认"),
        FieldSpec("name", "监护人姓名", required=True),
        FieldSpec("role", "关系", type="select", options=GUARDIAN_ROLES, default="其他"),
        FieldSpec("phone", "电话", hint="手机号或固定电话"),
        FieldSpec("job", "工作单位"),
        FieldSpec("wechat", "微信/其他联系标识"),
        FieldSpec("is_primary", "主要联系人", type="checkbox", default=False, hint="紧急情况优先打这一个"),
        FieldSpec("note", "备注", type="textarea", full=True),
    ),
    search_keys=("student_name", "name", "phone", "job"),
    filter_keys=("role", "is_primary"),
    default_sort=("id", -1),
    class_scoped=True,
    dedupe_keys=("student_name", "name"),  # 同一学生的同一位监护人，重复导入不翻倍
    extra_keys=("student_id",),
    # 把老师填的「学生姓名」解析成 student_id，并带出 class_id 与冗余姓名
    before_save=link_student,
)

TABLES: dict[str, TableSpec] = {
    spec.key: spec for spec in (TODO, RULE, TEMPLATE, GUARDIAN, HOMEWORK, ATTENDANCE, EXAM)
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
