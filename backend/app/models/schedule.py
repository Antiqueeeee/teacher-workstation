"""课表与倒计时。

课表在旧应用里是 `schedule` 的一个嵌套结构（周次 → 节次 → 课程），还带一个
**走公网 CDN 的 OCR 导入**（`:11643`，识别图片里的课表）。按 `05` §7 的已作废清单，
OCR 整体不做；这里只留手工维护的格子。

一格 = 一周里的某天某一节（`UNIQUE(class_id, weekday, period)`）—— 同一格放两门课
在老应用里能存下去，但界面上永远只显示一格，等于其中一门课人间蒸发。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin

# 与旧应用一致（`:6218` 的课程表节次）
PERIODS = ("第1节", "第2节", "第3节", "第4节", "第5节", "第6节", "第7节", "第8节")
WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


class ScheduleSlot(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "schedule_slots"
    __table_args__ = (
        UniqueConstraint("class_id", "weekday_no", "period", name="uq_schedule_slots_cell"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    weekday: Mapped[str] = mapped_column(String(8), nullable=False)
    weekday_no: Mapped[int] = mapped_column(Integer, nullable=False)
    period: Mapped[str] = mapped_column(String(8), nullable=False)
    subject: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    teacher: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    room: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)


class Countdown(Base, TimestampMixin, SoftDeleteMixin):
    """倒计时（考试、活动、截止日）。"""

    __tablename__ = "countdowns"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(64), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(16), default="其他", nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    @property
    def days_left(self) -> int:
        """还有几天 —— 后端算，界面不自己减（时区与「今天」的口径只该有一处）。"""
        return (self.date - date.today()).days
