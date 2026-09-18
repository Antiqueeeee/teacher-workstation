"""课表与倒计时的表声明。"""

from __future__ import annotations

from app.models.schedule import PERIODS, WEEKDAYS, Countdown, ScheduleSlot
from app.schemas.table_spec import ColumnSpec, FieldSpec, TableSpec
from app.services.schedule_service import apply_slot

SLOT = TableSpec(
    key="schedule_slots",
    title="课程表",
    entity="课表",
    model=ScheduleSlot,
    columns=(
        # 显示用**星期几的汉字**（模型上有 `weekday` 这一列）；排序仍走 `weekday_no`
        # —— 按汉字排是按码位排，星期五会跑到星期一前面。所以这一列不给点排序
        ColumnSpec("weekday", "星期", w="84px", sortable=False),
        ColumnSpec("period", "节次", w="80px"),
        ColumnSpec("subject", "科目", w="90px"),
        ColumnSpec("teacher", "任课教师", w="110px"),
        ColumnSpec("room", "地点", w="110px"),
        ColumnSpec("note", "备注"),
    ),
    fields=(
        FieldSpec("weekday", "星期", type="select", options=WEEKDAYS, default="星期一"),
        FieldSpec("period", "节次", type="select", options=PERIODS, required=True),
        FieldSpec("subject", "科目", default="", hint="留空表示这一格空着"),
        FieldSpec("teacher", "任课教师"),
        FieldSpec("room", "地点", hint="如 教学楼 305"),
        FieldSpec("note", "备注", type="textarea", full=True),
        # 排序用（由钩子从「星期」算出来，不让人填）
        FieldSpec("weekday_no", "星期序号", type="number", editable=False),
    ),
    search_keys=("subject", "teacher", "room", "note"),
    filter_keys=("weekday_no", "period", "subject"),
    default_sort=("weekday_no", 1),
    dedupe_keys=("weekday", "period"),  # 一格一条，重复导入不翻倍
    extra_keys=("weekday_no",),
    before_save=apply_slot,
)

COUNTDOWN = TableSpec(
    key="countdowns",
    title="倒计时",
    entity="倒计时",
    model=Countdown,
    columns=(
        ColumnSpec("title", "事项", w="220px"),
        ColumnSpec("date", "日期", w="104px", numeric=True),
        ColumnSpec("category", "类别", w="90px"),
        ColumnSpec("days_left", "还有几天", w="92px", numeric=True, sortable=False),
        ColumnSpec("note", "备注"),
    ),
    fields=(
        FieldSpec("title", "事项", required=True, hint="如 期末考试 / 运动会"),
        FieldSpec("date", "日期", type="date", required=True),
        FieldSpec(
            "category",
            "类别",
            type="select",
            options=("考试", "活动", "截止日", "其他"),
            default="其他",
        ),
        FieldSpec("note", "备注", type="textarea", full=True),
    ),
    search_keys=("title", "note"),
    filter_keys=("category",),
    default_sort=("date", 1),
    dedupe_keys=("title", "date"),
    extra_keys=("days_left",),
)
