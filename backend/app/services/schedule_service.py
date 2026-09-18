"""课表与倒计时的写入规则。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, ApiError
from app.models.schedule import PERIODS, WEEKDAYS, ScheduleSlot


def apply_slot(values: dict[str, Any], session: Session, row: Any = None) -> None:
    """课表格子：星期与节次必须在词表里，且一格只能有一门课。"""
    weekday = str(values.get("weekday") or (getattr(row, "weekday", "") if row else "") or "").strip()
    if weekday not in WEEKDAYS:
        raise ApiError(
            INVALID_VALUE,
            f"认不出的星期「{weekday}」，只能是{'、'.join(WEEKDAYS)}",
            detail={"field": "weekday", "value": weekday},
        )
    values["weekday"] = weekday
    values["weekday_no"] = WEEKDAYS.index(weekday) + 1

    period = str(values.get("period") or (getattr(row, "period", "") if row else "") or "").strip()
    if period not in PERIODS:
        raise ApiError(
            INVALID_VALUE,
            f"认不出的节次「{period}」，只能是{'、'.join(PERIODS)}",
            detail={"field": "period", "value": period},
        )
    values["period"] = period

    class_id = values.get("class_id") or (getattr(row, "class_id", None) if row else None)
    if class_id:
        clash = session.scalars(
            select(ScheduleSlot).where(
                ScheduleSlot.deleted_at.is_(None),
                ScheduleSlot.class_id == class_id,
                ScheduleSlot.weekday_no == values["weekday_no"],
                ScheduleSlot.period == period,
                ScheduleSlot.id != (row.id if row is not None and row.id else 0),
            )
        ).first()
        if clash is not None:
            raise ApiError(
                INVALID_VALUE,
                f"{weekday} {period} 已经有「{clash.subject or '一门课'}」了。"
                "一格只能放一门课 —— 要换课请直接改那一条。",
                detail={"field": "period", "slotId": clash.id},
            )


def week_view(session: Session, class_id: int) -> dict[str, Any]:
    """一周的课表：按星期 × 节次排好，空位也在（界面直接渲染格子）。"""
    rows = list(
        session.scalars(
            select(ScheduleSlot).where(
                ScheduleSlot.deleted_at.is_(None), ScheduleSlot.class_id == class_id
            )
        )
    )
    by_cell = {(row.weekday_no, row.period): row for row in rows}
    return {
        "weekdays": list(WEEKDAYS),
        "periods": list(PERIODS),
        "grid": [
            [
                {
                    "slotId": by_cell[(index, period)].id if (index, period) in by_cell else None,
                    "subject": by_cell[(index, period)].subject if (index, period) in by_cell else "",
                    "teacher": by_cell[(index, period)].teacher if (index, period) in by_cell else "",
                    "room": by_cell[(index, period)].room if (index, period) in by_cell else "",
                }
                for period in PERIODS
            ]
            for index in range(1, len(WEEKDAYS) + 1)
        ],
    }


def today_slots(session: Session, class_id: int, weekday_no: int) -> list[dict[str, Any]]:
    """某天的课（代课简报的「今日课表」段用它）。"""
    rows = session.scalars(
        select(ScheduleSlot)
        .where(
            ScheduleSlot.deleted_at.is_(None),
            ScheduleSlot.class_id == class_id,
            ScheduleSlot.weekday_no == weekday_no,
        )
        .order_by(ScheduleSlot.id)
    )
    order = {period: index for index, period in enumerate(PERIODS)}
    items = [
        {
            "period": row.period,
            "subject": row.subject,
            "teacher": row.teacher,
            "room": row.room,
            "note": row.note,
        }
        for row in rows
    ]
    return sorted(items, key=lambda item: order.get(item["period"], 99))
