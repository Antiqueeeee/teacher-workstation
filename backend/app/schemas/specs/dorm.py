"""宿舍与座位类表的声明：宿舍房间、床位、宿舍值日、座位。

类型定义在 `schemas/table_spec.py`，汇总与访问器在 `schemas/registry.py`。
"""

from __future__ import annotations

from app.models.dorm import (
    DEFAULT_CAPACITY,
    DUTY_RESULTS,
    DUTY_TASKS,
    WEEKDAYS,
    DormBed,
    DormDuty,
    DormRoom,
)
from app.models.seat import Seat
from app.schemas.table_spec import ColumnSpec, FieldSpec, TableSpec
from app.services.dorm_service import apply_bed, apply_duty, apply_room
from app.services.seat_service import apply_seat

DORM_ROOM = TableSpec(
    key="dorm_rooms",
    model=DormRoom,
    title="宿舍房间",
    entity="宿舍房间",
    columns=(
        ColumnSpec("building", "楼栋", w="88px"),
        ColumnSpec("room_no", "房号", w="80px"),
        ColumnSpec("capacity", "容量", w="70px", numeric=True),
        ColumnSpec("occupied", "已住", w="64px", numeric=True, sortable=False),
        ColumnSpec("full", "满员", w="64px", sortable=False),
        ColumnSpec("note", "备注"),
    ),
    fields=(
        FieldSpec("building", "楼栋", hint="只有一个宿舍楼时留空即可"),
        FieldSpec("room_no", "房号", required=True, hint="如 203"),
        FieldSpec(
            "capacity",
            "容量（几人间）",
            type="number",
            default=DEFAULT_CAPACITY,
            hint=f"留空按 {DEFAULT_CAPACITY} 人间；要改小会先检查里面住了几个人",
        ),
        FieldSpec("note", "备注", type="textarea", full=True),
        # 派生值：导出带上、导入忽略，人不用填（与作业的提交率同一套做法）
        FieldSpec("occupied", "已住人数", type="number", editable=False),
    ),
    search_keys=("room_no", "building", "note"),
    filter_keys=("building",),
    default_sort=("room_no", 1),
    dedupe_keys=("building", "room_no"),
    before_save=apply_room,
)


DORM_BED = TableSpec(
    key="dorm_beds",
    model=DormBed,
    title="宿舍分布",
    entity="床位",
    # 楼栋/房号/学号是**派生属性**（来自房间与学生），所以不能声明为可排序/可筛选 ——
    # 排序点下去会 500（看门测试拦着）。列表照常显示，分组看「宿舍分布」的看板视图
    columns=(
        ColumnSpec("building", "楼栋", w="88px", sortable=False),
        ColumnSpec("room_no", "房号", w="80px", sortable=False),
        ColumnSpec("bed_no", "床位号", w="76px", numeric=True),
        ColumnSpec("student_name", "学生", w="92px"),
        ColumnSpec("leader", "寝室长", w="76px"),
        ColumnSpec("note", "备注"),
    ),
    fields=(
        FieldSpec(
            "building",
            "楼栋",
            hint="没有楼栋就留空；房间不存在时会自动建出来",
        ),
        FieldSpec("room_no", "房号", required=True),
        FieldSpec(
            "bed_no",
            "床位号",
            # `bedno` 类型 = 宽容的整数：「1号床」「01」都认成 1，「靠窗」报错
            # （导入预览里就会报，不用等到提交）
            type="bedno",
            required=True,
            hint="如 1 或 1号床；认不出来的写法（例如「靠窗」）会报错，不会变成 0 号床",
        ),
        FieldSpec(
            "student_name",
            "学生",
            hint="填学生姓名；也可以用学号（下面那一栏）",
        ),
        FieldSpec("sno", "学号", hint="姓名重名时用学号指定"),
        FieldSpec("leader", "寝室长", type="checkbox", default=False),
        FieldSpec("note", "备注", type="textarea", full=True, hint="如：上铺、靠窗"),
    ),
    search_keys=("student_name", "note"),
    filter_keys=("leader",),
    default_sort=("bed_no", 1),
    # 床位**没有软删除**：腾床位就是删掉这一行。软删除会让 (room_id, bed_no)
    # 唯一约束与「重新分配同一个床位」冲突，而「找回一条床位记录」并不需要
    soft_delete=False,
    # 一个学生只能有一张床（唯一索引兜底），导入判重按人算
    dedupe_keys=("student_name",),
    extra_keys=("student_id", "room_id", "room_label", "orphan"),
    before_save=apply_bed,
)


DORM_DUTY = TableSpec(
    key="dorm_duties",
    model=DormDuty,
    title="宿舍值日",
    entity="值日安排",
    # 楼栋/房号/星期/学号都是派生属性或输入字段，所以不能声明为可排序/可筛选
    columns=(
        ColumnSpec("room_label", "房间", w="120px", sortable=False),
        # 星期列显示汉字、不给点：点了会按汉字码位排序（星期五排到星期一前面）。
        # 列表默认顺序就是按星期序号（见 default_sort），本来就是对的
        ColumnSpec("weekday", "星期", w="84px", sortable=False),
        ColumnSpec("student_name", "值日学生", w="96px"),
        ColumnSpec("task", "值日任务", w="130px"),
        ColumnSpec("checker", "检查人", w="96px"),
        ColumnSpec("result", "检查结果", w="92px"),
        ColumnSpec("note", "备注"),
    ),
    fields=(
        FieldSpec("building", "楼栋", hint="房号在多个楼栋都有时才要填"),
        FieldSpec("room_no", "房号", required=True, hint="必须在「宿舍分布」里已经有这间房"),
        # 星期用汉字填（老师手里的表就是汉字），落库存序号 —— 排序天然正确
        FieldSpec("weekday", "星期", type="select", options=WEEKDAYS, default="星期一"),
        FieldSpec("student_name", "值日学生", hint="填学生姓名；也可以用学号"),
        FieldSpec("sno", "学号", hint="姓名重名时用学号指定"),
        FieldSpec("task", "值日任务", type="select", options=DUTY_TASKS, required=True),
        FieldSpec("checker", "检查人", hint="舍长或检查的老师（只作留档）"),
        FieldSpec("result", "检查结果", type="select", options=DUTY_RESULTS, default="合格"),
        FieldSpec("note", "备注", type="textarea", full=True),
        # 排序/筛选用的星期序号：不让人填（由钩子从「星期」算出来）
        FieldSpec("weekday_no", "星期序号", type="number", editable=False),
    ),
    search_keys=("student_name", "task", "checker", "note"),
    filter_keys=("weekday", "result"),
    default_sort=("weekday_no", 1),
    dedupe_keys=("room_no", "weekday", "task"),  # 同一房间同一天同一项任务，重复导入不翻倍
    extra_keys=("room_id", "room_label", "student_id", "orphan"),
    before_save=apply_duty,
)


SEAT = TableSpec(
    key="seats",
    model=Seat,
    title="座位安排",
    entity="座位",
    # 「组」由列决定（派生属性），所以不能声明为可排序/可筛选
    columns=(
        ColumnSpec("row", "排", w="62px", numeric=True),
        ColumnSpec("col", "列", w="62px", numeric=True),
        ColumnSpec("group", "组", w="72px", sortable=False),
        ColumnSpec("student_name", "学生", w="96px"),
        ColumnSpec("locked", "锁定", w="70px"),
        ColumnSpec("note", "备注"),
    ),
    fields=(
        FieldSpec("row", "第几排", type="number", required=True, hint="1 是最前面一排"),
        FieldSpec("col", "第几列", type="number", required=True),
        FieldSpec("student_name", "学生", hint="留空就是一个空座位"),
        FieldSpec("sno", "学号", hint="姓名重名时用学号指定"),
        FieldSpec(
            "locked",
            "锁定",
            type="checkbox",
            default=False,
            hint="锁定的座位不参与随机排位与轮换",
        ),
        FieldSpec(
            "note",
            "备注",
            type="textarea",
            full=True,
            hint="如：近视 500 度，需坐前排。随机排位不会清掉它",
        ),
    ),
    search_keys=("student_name", "note"),
    filter_keys=("locked",),
    default_sort=("row", 1),
    dedupe_keys=("row", "col"),  # 同一格重复导入不翻倍
    extra_keys=("student_id", "position", "orphan"),
    before_save=apply_seat,
)
