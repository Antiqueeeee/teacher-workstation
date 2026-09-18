"""班级事务类的三张主数据表：班委、团员、值日。

它们的共同点：都是从旧应用的 `makeStudentModule` 生成的普通 CRUD，
**学生只存姓名 + 学号回填**（`beforeSave` 里按姓名反查）。姓名重名会挂错人、
改名会断链，所以这里统一改成 `student_id` 引用 + 姓名快照。

按域放一个文件（`CONTRIBUTING.md` §3 的「按聚合分」）：这三张都是「班里的人承担什么角色」。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin

# 与旧应用一致（`:9590` CFG_CADRES 的 appraise 选项）
APPRAISALS = ("优秀", "良好", "称职", "待改进")

# 与旧应用一致（`:11203` CFG_YOUTH 的 post 选项），默认「团员」
YOUTH_POSTS = ("团员", "团支书", "组织委员", "宣传委员", "纪检委员")
YOUTH_FEES = ("已缴", "未缴")

# 与旧应用一致（`:11085` CFG_DUTY）：星期用「星期一…星期日」（旧应用只画到周五，是它的缺陷）
# 与旧应用一致（`:11131`）的 8 个区域
DUTY_AREAS = (
    "教室地面",
    "黑板讲台",
    "走廊包干区",
    "门窗桌椅",
    "垃圾清运",
    "饮水机区域",
    "图书角",
    "清洁工具间",
)
DUTY_CHECKS = ("优秀", "合格", "待改进")

WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


class Cadre(Base, TimestampMixin, SoftDeleteMixin):
    """班委成员。一个人可以担任多个职务（旧应用也是），所以不加唯一约束。"""

    __tablename__ = "cadres"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True, default=None
    )
    student_name: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    post: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    term: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    appraise: Mapped[str] = mapped_column(String(8), default="良好", nullable=False)
    duty: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 文档 §4 要求加的：任期的起止（旧应用只有一个「任期」文本）
    start_date: Mapped[date | None] = mapped_column(Date, default=None)
    end_date: Mapped[date | None] = mapped_column(Date, default=None)

    student = relationship("Student", lazy="selectin")

    @property
    def sno(self) -> str:
        return self.student.sno if self.student else ""

    @property
    def phone(self) -> str:
        """联系电话取自学生档案（旧应用是保存时回填一次的快照，学生换号就过期了）。"""
        return str((self.student.extra or {}).get("phone") or "") if self.student else ""

    @property
    def gender(self) -> str:
        return str((self.student.extra or {}).get("gender") or "") if self.student else ""


class YouthMember(Base, TimestampMixin, SoftDeleteMixin):
    """团员名册。

    与学生档案的 `politics` 字段有语义重叠（都是「是不是团员」）。**不在这里做双向同步**：
    一致性校验放在服务层（保存团员档案时提示与 `politics` 不一致的人），
    两处各自动改写对方是最容易出怪事的那种设计。
    """

    __tablename__ = "youth_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True, default=None
    )
    student_name: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    join_date: Mapped[date] = mapped_column(Date, nullable=False)
    branch: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    post: Mapped[str] = mapped_column(String(16), default="团员", nullable=False)
    fee: Mapped[str] = mapped_column(String(8), default="已缴", nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    student = relationship("Student", lazy="selectin")

    @property
    def sno(self) -> str:
        return self.student.sno if self.student else ""

    @property
    def gender(self) -> str:
        return str((self.student.extra or {}).get("gender") or "") if self.student else ""


class DutyGroup(Base, TimestampMixin, SoftDeleteMixin):
    """值日安排：某天、某个区域、谁负责。

    与旧应用（`:11085`）的两处结构差别：

    1. **成员是学生引用**（子表 `duty_members`），不再是一串顿号分隔的姓名 ——
       这样才统计得出「个人值日次数」（旧应用的自由文本做不到）；
    2. **区域与星期用词表常量**，不是各处硬编码的字符串。
    """

    __tablename__ = "duty_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    weekday_no: Mapped[int] = mapped_column(nullable=False)  # 1–7，排序用
    weekday: Mapped[str] = mapped_column(String(8), nullable=False)
    group_name: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    area: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    leader_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id", ondelete="SET NULL"), default=None
    )
    leader_name: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    check: Mapped[str] = mapped_column(String(8), default="合格", nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 成员姓名的冗余串（顿号分隔）：**列表与搜索要用真实列**（派生属性构不出 SQL，
    # 声明成可搜索就会被看门测试拦下）。由钩子在写成员子表时一并写。
    members_cache: Mapped[str] = mapped_column(Text, default="", nullable=False)

    members = relationship(
        "DutyMember",
        cascade="all, delete-orphan",
        lazy="selectin",
        back_populates="duty",
    )

    @property
    def members_text(self) -> str:
        """成员姓名串（顿号分隔）。

        这是**输入用的虚拟字段**（老师的表就是这个形状），钩子解析完把它摘掉、
        写进 `members_cache`。展示与搜索读 `members_cache`。
        """
        return self.members_cache or "、".join(link.student_name for link in self.members)

    @property
    def member_count(self) -> int:
        return len(self.members)


class DutyMember(Base, TimestampMixin):
    """一位值日成员（子表）。没有软删除：它跟着那条值日安排走。"""

    __tablename__ = "duty_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    duty_id: Mapped[int] = mapped_column(
        ForeignKey("duty_groups.id", ondelete="CASCADE"), index=True, nullable=False
    )
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True, default=None
    )
    student_name: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    duty = relationship("DutyGroup", back_populates="members")
