"""出勤记录（含点名）。

旧应用这一块有四个问题，建模时就按「从根上不出错」来定：

1. **一人一天可以存多条**：种子数据里同一个学生同一天有一条病假、一条事假
   （`:2539` 的 `A026`/`A035`）。所有统计都按**记录条数**当人数用，于是这个学生
   被扣两次，45 人班的出勤率被压到 93%。新模型用 `UNIQUE(date, student_id)`
   从结构上堵掉：一条记录 = 一个学生一天的状态。
2. **没有约束，只能靠约定**：旧表没有唯一键、没有外键，学号写错就是一条孤儿记录。
   这里学生是外键关联，「查无此人」在写入时就会报错。
3. **迟到/早退与缺席混在一张表里没有区分**：口径靠各处硬编码 `['病假','事假','旷课']`。
   改成常量（`ABSENCE_TYPES` / `DISCIPLINE_TYPES`），只有一处定义。
4. **「跟进状态」缺失**：旧应用的 `handled` 是自由文本（"处理情况"），而待办中心
   用「`handled` 为空」判定"缺勤未联系家长"—— 于是点名生成的记录全都变成待办。
   新模型把它拆成两件事：`handled` 三态（驱动待办）+ `handled_note` 自由文本（留档）。

**刻意不用软删除**：`UNIQUE(date, student_id)` 与软删除天生冲突 —— 删掉的记录仍占着
唯一键，同一天同一个学生就再也写不进来了。出勤是一天的日志，删了重新登记即可，
本来也不需要「找回某一条出勤记录」这个能力（点名整体覆盖时也是真删）。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# 与旧应用一致（`:9780` 的类型下拉，5 类，没有别的值）
ATTENDANCE_TYPES = ("病假", "事假", "迟到", "早退", "旷课")

# 进「缺席」统计的三类 —— 旧应用各处硬编码的 `['病假','事假','旷课']`
ABSENCE_TYPES = ("病假", "事假", "旷课")
# 单独成指标、**不进出勤率**的两类
DISCIPLINE_TYPES = ("迟到", "早退")
# 家长已经打过招呼的两类（与「旷课」的区别就在这里）
EXCUSED_TYPES = ("病假", "事假")

# 与旧应用一致（`:9782` 的节次下拉；`period` 只作留档，不参与任何统计）
PERIODS = (
    "早读",
    "第1节",
    "第2节",
    "第3节",
    "第4节",
    "下午第1节",
    "下午第2节",
    "下午第3节",
    "晚自习",
    "全天",
)

# 跟进状态（替代旧应用那个既当状态又当备注的自由文本 `handled`）
FOLLOW_UP_STATES = ("待联系", "已通知", "无需联系")


class Attendance(Base, TimestampMixin):
    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint("date", "student_id", name="uq_attendance_date_student"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # 姓名快照：列表、搜索、导出都直接读它，不必 join（学号也一样由学生带出）
    student_name: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    type: Mapped[str] = mapped_column(String(8), nullable=False)
    period: Mapped[str] = mapped_column(String(16), default="全天", nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 「待联系」是刻意的兜底值：任何绕过服务层直接插数据的路径，宁可多出一条待办
    # （老师随手清掉即可），也不要漏掉一次该打的电话。正常写入时由
    # `services/attendance_service.py:default_follow_up` 按类型算出真实默认值。
    handled: Mapped[str] = mapped_column(String(8), default="待联系", nullable=False)
    # 「处理情况」：旧应用 `handled` 的自由文本部分，留档用
    handled_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
