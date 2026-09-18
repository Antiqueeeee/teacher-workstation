"""沟通留档与德育活动的六张表：家访、谈话、班会、班级活动、大事记、矛盾调解。

它们的共同点：都是「一件发生在某天的事」+ 一份留档，而且**都可以挂照片与录音**
（用户明确要的「和家长沟通之后留档」）。所以六张表统一声明 `media_owner=True`，
附件走媒体库的多态归属，不给每张表各写一套图片字段 ——
旧应用正是各写各的（`meetings.images` / `events.photo` 字段错配、照片接不过来）。

与学生关联的有三张：家访、谈话（一人一次）、矛盾调解（**多人**，用子表）。
旧应用的矛盾调解把「涉及学生」存成顿号分隔的姓名串，然后在一生一档里用
`parties.includes(name)` 匹配 —— 姓名互为子串时会挂错人（文档 §31）。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, MediaAttachmentMixin, SoftDeleteMixin, TimestampMixin

# 与旧应用一致（`:16179` CFG_TALKS）
TALK_TYPES = (
    "学业指导",
    "心理疏导",
    "纪律教育",
    "生涯规划",
    "人际关系",
    "行为习惯",
    "家庭沟通",
    "荣誉激励",
)
TALK_PLACES = ("办公室", "教室走廊", "操场散步", "心理辅导室", "线上电话", "家访")

# 与旧应用一致（`:16603` CFG_CLASSACT）
ACTIVITY_TYPES = (
    "文体活动",
    "社会实践",
    "志愿服务",
    "主题班会延伸",
    "节日庆祝",
    "研学旅行",
    "其他",
)

# 与旧应用一致（`:16351` CFG_EVENTS）
EVENT_CATEGORIES = ("组建", "荣誉", "竞赛", "活动", "家校", "其他")

# 与旧应用一致（`:16465` CFG_CONFLICTS）
CONFLICT_LEVELS = ("轻微", "一般", "较严重")
CONFLICT_STATUSES = ("已化解", "跟踪中", "未解决")


class Visit(Base, TimestampMixin, SoftDeleteMixin, MediaAttachmentMixin):
    """家访记录。"""

    __tablename__ = "visits"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True, default=None
    )
    student_name: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    teacher: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    duration: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    home_situation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    performance: Mapped[str] = mapped_column(Text, default="", nullable=False)
    parent_needs: Mapped[str] = mapped_column(Text, default="", nullable=False)
    consensus: Mapped[str] = mapped_column(Text, default="", nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    student = relationship("Student", lazy="selectin")

    @property
    def sno(self) -> str:
        return self.student.sno if self.student else ""


class Talk(Base, TimestampMixin, SoftDeleteMixin, MediaAttachmentMixin):
    """学生谈话。"""

    __tablename__ = "talks"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True, default=None
    )
    student_name: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    type: Mapped[str] = mapped_column(String(16), default="学业指导", nullable=False)
    place: Mapped[str] = mapped_column(String(16), default="办公室", nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    result: Mapped[str] = mapped_column(Text, default="", nullable=False)
    follow_up: Mapped[str] = mapped_column(Text, default="", nullable=False)
    recorder: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    student = relationship("Student", lazy="selectin")

    @property
    def sno(self) -> str:
        return self.student.sno if self.student else ""


class Meeting(Base, TimestampMixin, SoftDeleteMixin, MediaAttachmentMixin):
    """主题班会。"""

    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    theme: Mapped[str] = mapped_column(String(64), nullable=False)
    host: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    # 旧应用是「45/45」这样一个自由文本框，统计不出来；这里拆成实到与应到两个数
    attend_actual: Mapped[int | None] = mapped_column(Integer, default=None)
    attend_expected: Mapped[int | None] = mapped_column(Integer, default=None)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    effect: Mapped[str] = mapped_column(Text, default="", nullable=False)

    @property
    def attend_text(self) -> str:
        if self.attend_actual is None and self.attend_expected is None:
            return ""
        return f"{self.attend_actual or 0}/{self.attend_expected or 0}"


class ClassActivity(Base, TimestampMixin, SoftDeleteMixin, MediaAttachmentMixin):
    """班级活动。"""

    __tablename__ = "class_activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    organizer: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    place: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    effect: Mapped[str] = mapped_column(Text, default="", nullable=False)


class ClassEvent(Base, TimestampMixin, SoftDeleteMixin, MediaAttachmentMixin):
    """班级大事记。"""

    __tablename__ = "class_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(8), default="活动", nullable=False)
    participants: Mapped[str] = mapped_column(String(64), default="全班", nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)

    @property
    def honored(self) -> bool:
        """荣誉或竞赛 —— 首页与看板按它筛「值得写进总结的」。"""
        return self.category in ("荣誉", "竞赛")


class Conflict(Base, TimestampMixin, SoftDeleteMixin, MediaAttachmentMixin):
    """学生矛盾调解。

    「涉及学生」是**多人**：存子表（`conflict_parties`），并在 `parties_cache` 留一列
    顿号分隔的冗余串供列表与搜索 —— 派生属性构不出 SQL。
    """

    __tablename__ = "conflicts"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    level: Mapped[str] = mapped_column(String(8), default="一般", nullable=False)
    status: Mapped[str] = mapped_column(String(8), default="跟踪中", nullable=False)
    mediator: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    process: Mapped[str] = mapped_column(Text, default="", nullable=False)
    result: Mapped[str] = mapped_column(Text, default="", nullable=False)
    follow_up: Mapped[str] = mapped_column(Text, default="", nullable=False)
    parties_cache: Mapped[str] = mapped_column(Text, default="", nullable=False)

    parties = relationship(
        "ConflictParty",
        cascade="all, delete-orphan",
        lazy="selectin",
        back_populates="conflict",
    )

    @property
    def parties_text(self) -> str:
        """涉及学生姓名串（顿号分隔）—— 输入用这个形状，解析完写进 `parties_cache`。"""
        return self.parties_cache or "、".join(link.student_name for link in self.parties)

    @property
    def resolved(self) -> bool:
        return self.status == "已化解"


class ConflictParty(Base, TimestampMixin):
    """矛盾的一方（子表）。没有软删除：跟着那条调解记录走。"""

    __tablename__ = "conflict_parties"

    id: Mapped[int] = mapped_column(primary_key=True)
    conflict_id: Mapped[int] = mapped_column(
        ForeignKey("conflicts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True, default=None
    )
    student_name: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    conflict = relationship("Conflict", back_populates="parties")
