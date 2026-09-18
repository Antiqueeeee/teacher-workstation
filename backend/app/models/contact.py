"""家长联系日志（沟通留档）。

旧应用（`:7808`）是一个 `makeStudentModule` 生成的普通 CRUD：日期 / 学生 / 方式 / 事由 /
内容 / 家长反馈 / 是否待跟进。**没有附件能力** —— 而「和家长沟通之后把照片、录音留档」
正是用户提的三项调整之一。

两个结构变化：

1. 学生是**引用**（`student_id`）而不是只存姓名 —— 旧应用按姓名做 KPI 去重，重名就误算，
   改名就与人对不上；
2. 附件走 `media` 表的**多态归属**（`owner_table='contacts'` + `owner_id`），
   照片与录音都由后端落盘，不再 base64 进库。

字段上还加了两项（文档 `02` §17 的「改造后」）：**联系方向**与**结果**。旧应用的「方式」
（电话/微信/面对面/短信）说的是渠道，说不清「谁打给谁、接没接通」，而这两件事在日常使用里
分得挺开：老师要回看的是「上周给张伟妈妈打了两次都没接」。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, MediaAttachmentMixin, SoftDeleteMixin, TimestampMixin

# 与旧应用一致（`CFG_CONTACTS` 的 filters）
CHANNELS = ("电话", "微信", "面对面", "短信", "其他")
CATEGORIES = ("表扬", "违纪", "成绩", "安全", "请假", "心理", "其他")

# 新增：方向与结果
DIRECTIONS = ("去电", "来电", "面谈", "线上")
RESULTS = ("已沟通", "未接通", "待再联系")


class ContactLog(Base, TimestampMixin, SoftDeleteMixin, MediaAttachmentMixin):
    __tablename__ = "contact_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True, default=None
    )
    # 姓名快照：列表与导出不必 join（与出勤/成绩同一套做法）
    student_name: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    channel: Mapped[str] = mapped_column(String(16), default="电话", nullable=False)
    direction: Mapped[str] = mapped_column(String(8), default="去电", nullable=False)
    category: Mapped[str] = mapped_column(String(16), default="其他", nullable=False)
    result: Mapped[str] = mapped_column(String(8), default="已沟通", nullable=False)

    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    feedback: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 标记「还要再联系」—— 首页的「需要我跟进」读它（旧应用是 needsFollowUp==='是'）
    needs_follow_up: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    @property
    def sno(self) -> str:
        """学号（派生）—— 导出与列表按这个扁平形状用，与别处一致。"""
        return self.student.sno if self.student else ""

    student = relationship("Student", lazy="selectin")

    @property
    def attachment_count(self) -> int:
        """这条记录挂了几个附件（列表上要显示「2 张照片 · 1 段录音」）。

        由媒体服务在序列化前填进来（），而不是每条记录各查一次 ——
        一页 20 条记录就是 20 次查询。
        """
        return getattr(self, "_attachment_count", 0)
