"""话术模板（试点页之一）。

字段与旧应用的真实形状对齐（旧应用 `seedTemplatesOnce` 里每条就是
`{title, scenario, tone, body}`）：

| 旧应用 | 这里 | 说明 |
|---|---|---|
| `title` | `title` | 标题 |
| `scenario` | `category` | 场景 |
| `tone` | `tone` | 语气 —— **保留**：老师挑模板时正是按语气挑的，丢掉就少一半信息 |
| `body` | `content` | 正文，含 `〔…〕` 占位符 |

**故意不属于任何班级**（`class_scoped=False`）：话术是全班共享的素材，
选它做试点就是为了验证注册表同时支持「班级范围」和「全局」两种表。

下面的 `CATEGORIES` / `TONES` 是**旧应用内置 45 条模板的真实词表**
（由 `tools/extract_demo_fixture.py` 抽出，22 个场景 + 19 种语气）。
不自己另编一套 —— 词表对不上，老师手里已有的模板一条都导不进来。
（旧应用里这些选项的排列顺序无从得知，这里按 Unicode 序排列。）
"""

from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin

CATEGORIES = (
    "事务通知",
    "假期关怀",
    "升学就业",
    "同事协作",
    "学生谈话",
    "安全提醒",
    "实习实训",
    "家长会",
    "心理关注",
    "成绩关心",
    "日常表扬",
    "期末寄语",
    "活动动员",
    "活动招募",
    "班会",
    "班级管理",
    "矛盾调解",
    "竞赛动员",
    "考前动员",
    "致歉沟通",
    "进步鼓励",
    "违纪沟通",
)

TONES = (
    "严肃沟通",
    "中立温和",
    "关切提醒",
    "关切鼓励",
    "务实有力",
    "务实温暖",
    "务实简明",
    "正式友好",
    "正式温暖",
    "正式通知",
    "温和坚定",
    "温暖有力",
    "温暖诚挚",
    "温暖鼓励",
    "热情活泼",
    "热血有力",
    "谨慎温暖",
    "轻松友好",
    "轻松有力",
)


class Template(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(primary_key=True)

    title: Mapped[str] = mapped_column(String(120), nullable=False)
    # 场景 / 语气都允许留空：老师的模板未必都属于既有的 22×19 组合
    category: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    tone: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
