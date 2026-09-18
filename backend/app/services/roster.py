"""名单解析：把「老师写的姓名串」变成学生记录。

未交名单、出勤名单、活动参与人…… 这些地方的共同点是**老师填的是名字，程序要的是 id**。
解析规则只能有一处 —— 同一个名字在两条路上得到不同结果，是不会报错的那种错。

分隔符与「表示没人」的写法沿用旧应用的习惯：
- 分隔：顿号、逗号、分号、空格、斜杠、换行；
- 「无」「没有」「/」「—」「-」等表示「没有这个人」。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.student import Student

SEPARATORS = re.compile(r"[、,，;；/\s]+")
# 这些写法表示「没有」——旧应用里「全部提交填「无」」
EMPTY_WORDS = frozenset({"无", "没有", "全交", "全部提交", "无未交", "—", "-", "/", "なし"})


@dataclass
class RosterResult:
    students: list[Student] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def split_names(text: str | None) -> list[str]:
    """把一段文本拆成姓名列表，去掉空白项与「无」这类占位写法，并保序去重。"""
    if not text:
        return []
    names: list[str] = []
    for raw in SEPARATORS.split(str(text).strip()):
        name = raw.strip()
        if not name or name in EMPTY_WORDS:
            continue
        if name not in names:
            names.append(name)
    return names


def resolve_names(session: Session, names: list[str], class_id: int | None = None) -> RosterResult:
    """把姓名解析成学生。

    查无此人、或同名不止一个 → 记进 `problems`（由调用方决定报错还是提示）。
    **绝不随便挑一个** —— 静默挂错人比报错糟糕得多。
    """
    result = RosterResult()
    for name in names:
        query = select(Student).where(Student.deleted_at.is_(None), Student.name == name)
        if class_id:
            query = query.where(Student.class_id == class_id)
        matches = list(session.scalars(query))

        if not matches:
            result.problems.append(f"「{name}」不在学生档案里")
        elif len(matches) > 1:
            result.problems.append(f"有 {len(matches)} 个学生都叫「{name}」")
        else:
            result.students.append(matches[0])
    return result


def count_class_students(session: Session, class_id: int) -> int:
    """全班人数（未删除）—— 用于「应交人数」的默认值。"""
    from sqlalchemy import func  # 局部导入：只在这个小工具里用得上

    return session.scalar(
        select(func.count()).select_from(Student).where(
            Student.class_id == class_id, Student.deleted_at.is_(None)
        )
    ) or 0
