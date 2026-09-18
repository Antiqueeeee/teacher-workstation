"""学生档案。

**设计取舍：除身份字段外，其余档案字段全部放在 `extra` JSON 列里**，字段元数据由
`student_field_def` 驱动（种子来自旧应用真实的 24 条字段模板）。

为什么不把 24 个字段都建成列：旧应用支持老师在**运行时增删字段**（它有一个「字段管理」
界面），这是产品真实能力。每加一个字段就改一次表结构，等于把这个能力砍掉。
而一个班几十名学生，JSON 取值的代价可以忽略 —— 排序与筛选走 SQLite 的 `json_extract`。

留在真实列上的只有三样，都是被代码到处引用的：
- `sno`：唯一业务键（导入判重、点名、成绩关联都要它）；
- `name`：列表与搜索的主力；
- `class_id`：班级维度。

`extra` 里的字段即使删掉定义也不丢数据 —— 重新加回同名字段，值还在。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class Student(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "students"
    __table_args__ = (
        # 学号在班内唯一；但允许为空（转学生可能还没有学籍号），
        # 所以用**部分唯一索引**：只约束非空学号，避免两条空学号互相冲突
        Index("uq_students_class_sno", "class_id", "sno", unique=True, sqlite_where=text("sno <> ''")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )

    sno: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    # 其余档案字段（性别/住宿/籍贯/监护人以外的一切）
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class StudentFieldDef(Base, TimestampMixin):
    """学生档案的字段定义（内置 24 条 + 老师自己加的）。

    字段定义是**全局**的，不按班级分：同一个老师带多个班时，
    档案字段的使用习惯是一样的，按班各存一份只会让人来回配置。
    """

    __tablename__ = "student_field_def"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    type: Mapped[str] = mapped_column(String(16), default="text", nullable=False)
    options: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 身份字段（姓名、学号）不允许删除，是记录之间对得上的依据
    identity: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    in_list: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    in_form: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    in_detail: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    searchable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    filterable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Excel 表头别名 —— 导入能不能认出这一列，全靠它
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    hint: Mapped[str] = mapped_column(String(120), default="", nullable=False)
