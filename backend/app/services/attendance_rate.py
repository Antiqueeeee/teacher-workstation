"""出勤率的唯一口径。

旧应用有**三处**独立实现的出勤率（出勤页看板 `:9854`、代课简报 `:10184`、数据看板
14 天趋势 `:6380`），公式同构但都按**记录条数**而不是**人数**算：同一个学生同一天
两条记录就被扣两次。三处的边界也不一致 —— 0 条记录时一律返回 100%，于是「没登记考勤」
和「全员出勤」在界面上长得一模一样。

新口径（**只有这一份实现**，看板 / 趋势 / 简报 / 首页全部调它）：

- 缺席 = 当天**去重后的缺席学生数**（`病假/事假/旷课`），迟到、早退单列指标，不进出勤率；
- 分母 = 当日应到人数（在册学生数；学生表里还没有「休学」这类状态字段，等有了再接）；
- 应交 0 人、或**那天压根没登记考勤** → 出勤率为空（界面显示「—」），**不假装 100%**；
- 未登记日与「登记了、全员出勤」是两件事，分开表达（`registered` 字段）。

区间统计里，出勤率**只按已登记的日子**算，并同时给出「登记天数 / 区间天数」——
把没登记的日子当全员出勤混进分母，只会得出一个虚高的数，那种数看着好看但没用。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, ApiError
from app.models.attendance import ABSENCE_TYPES, Attendance
from app.services.roster import list_class_students

# 一次最多统计多少天：一个手改的 URL（from=1900-01-01）不该让服务空转
MAX_RANGE_DAYS = 400


def compute_rate(expected: int, absent: int) -> int | None:
    """出勤率 = (应到 − 缺席) / 应到。应到 0 人时返回 None（界面显示「—」）。"""
    if expected <= 0:
        return None
    missing = max(0, min(absent, expected))  # 缺席比应到还多时按应到封顶
    return round((expected - missing) / expected * 100)


@dataclass(frozen=True)
class DaySummary:
    """某一天的出勤小结。"""

    day: date
    expected: int
    absent: int            # 去重后的缺席学生数
    late: int
    early: int
    registered: bool       # 这天登记过考勤吗（登记过 = 至少有一条记录）
    absent_students: tuple[str, ...]

    @property
    def rate(self) -> int | None:
        # 未登记 ≠ 全员出勤：那天压根没记考勤，出勤率只能是空
        if not self.registered:
            return None
        return compute_rate(self.expected, self.absent)

    def to_dict(self) -> dict:
        return {
            "date": self.day.isoformat(),
            "expected": self.expected,
            "absent": self.absent,
            "late": self.late,
            "early": self.early,
            "registered": self.registered,
            "absentStudents": list(self.absent_students),
            "rate": self.rate,
        }


@dataclass(frozen=True)
class RangeSummary:
    """一段区间的出勤小结。`days` 里包含未登记的日子（`registered=False`）。"""

    days: tuple[DaySummary, ...]

    @property
    def registered_days(self) -> int:
        return sum(1 for day in self.days if day.registered)

    @property
    def expected(self) -> int:
        """已登记日的应到**人次**（未登记日不计入，否则分母虚高）。"""
        return sum(day.expected for day in self.days if day.registered)

    @property
    def absent(self) -> int:
        return sum(day.absent for day in self.days if day.registered)

    @property
    def late(self) -> int:
        return sum(day.late for day in self.days)

    @property
    def early(self) -> int:
        return sum(day.early for day in self.days)

    @property
    def rate(self) -> int | None:
        # 一天都没登记 → None，不是 100%
        if not self.registered_days:
            return None
        return compute_rate(self.expected, self.absent)

    def to_dict(self) -> dict:
        return {
            "from": self.days[0].day.isoformat() if self.days else None,
            "to": self.days[-1].day.isoformat() if self.days else None,
            "days": [day.to_dict() for day in self.days],
            "totalDays": len(self.days),
            "registeredDays": self.registered_days,
            "expected": self.expected,
            "absent": self.absent,
            "late": self.late,
            "early": self.early,
            "rate": self.rate,
        }


def _summarize_day(day: date, roster: dict[int, str], rows: Iterable[Attendance]) -> DaySummary:
    """把「某天的记录 + 当前在册名单」折成小结。

    只统计**还在册**的学生：转出/删除的学生不该继续拉低出勤率，
    而分母（应到）本来就不含他们 —— 分子分母必须用同一个人群。

    去重按 **student_id**，不是姓名：班上有两个「张伟」时，按姓名去重会把两个人
    当成一个人（出勤率偏高、缺席名单少一个人）。旧应用按姓名匹配，同名本来就是个
    现实问题（会议里点过），所以这里不能用姓名当身份。
    """
    absent_ids: list[int] = []
    late = 0
    early = 0
    rows = list(rows)
    for row in rows:
        if row.student_id not in roster:
            continue
        if row.type in ABSENCE_TYPES:
            if row.student_id not in absent_ids:
                absent_ids.append(row.student_id)
        elif row.type == "迟到":
            late += 1
        elif row.type == "早退":
            early += 1

    return DaySummary(
        day=day,
        expected=len(roster),
        absent=len(absent_ids),
        late=late,
        early=early,
        # 「登记过」按是否有记录判断：连转出学生的记录也算登记过，
        # 那天的考勤确实是记过的
        registered=bool(rows),
        # 同一个名字可能出现两次（真是两个人），照实列出来
        absent_students=tuple(roster[student_id] for student_id in absent_ids),
    )


def range_summary(session: Session, class_id: int | None, start: date, end: date) -> RangeSummary:
    """区间小结：看板、趋势图、代课简报、首页卡片全部读这一个函数的结果。"""
    if start > end:
        raise ApiError(INVALID_VALUE, "开始日期不能晚于结束日期", detail={"from": str(start), "to": str(end)})
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise ApiError(
            INVALID_VALUE,
            f"一次最多统计 {MAX_RANGE_DAYS} 天",
            detail={"from": str(start), "to": str(end)},
        )

    roster = {student.id: student.name for student in list_class_students(session, class_id)} if class_id else {}
    grouped: dict[date, list[Attendance]] = {}
    if class_id:
        rows = session.scalars(
            select(Attendance).where(
                Attendance.class_id == class_id,
                Attendance.date >= start,
                Attendance.date <= end,
            )
        )
        for row in rows:
            grouped.setdefault(row.date, []).append(row)

    days: list[DaySummary] = []
    day = start
    while day <= end:
        days.append(_summarize_day(day, roster, grouped.get(day, [])))
        day += timedelta(days=1)
    return RangeSummary(days=tuple(days))


def day_summary(session: Session, class_id: int | None, day: date) -> DaySummary:
    return range_summary(session, class_id, day, day).days[0]
