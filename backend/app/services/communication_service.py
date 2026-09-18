"""沟通留档类（家访 / 谈话 / 班会 / 活动 / 大事记 / 矛盾调解）的写入规则。

三张表与学生关联（家访、谈话、矛盾调解）：前两张一人一条记录，矛盾调解是**多人**，
用子表 —— 旧应用把涉及学生存成顿号分隔的姓名串，然后在一生一档里用
`parties.includes(name)` 匹配，姓名互为子串时会挂错人（文档 §31）。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, ApiError
from app.models.communication import ConflictParty
from app.services.roster import resolve_names, split_names, student_link_hook

link_visit_student = student_link_hook()
link_talk_student = student_link_hook()


def apply_meeting(values: dict[str, Any], session: Session, row: Any = None) -> None:
    """班会：出席人数不能超过应到（旧应用是一个「45/45」的自由文本框，统计不出来）。"""
    actual = values.get("attend_actual")
    expected = values.get("attend_expected")
    if actual is not None and expected is not None and expected >= 0 and actual > expected:
        raise ApiError(
            INVALID_VALUE,
            f"实到 {actual} 人不可能超过应到 {expected} 人，请核对一下",
            detail={"field": "attend_actual"},
        )


def apply_conflict(values: dict[str, Any], session: Session, row: Any = None) -> Callable[[Any], None] | None:
    """矛盾调解：把「涉及学生」解析成子表，并写一列冗余串供列表与搜索。"""
    text = values.pop("parties_text", None)

    def after_save(saved: Any) -> None:
        if text is None:
            return
        result = resolve_names(session, split_names(text), saved.class_id)
        if not result.ok:
            raise ApiError(
                INVALID_VALUE,
                "涉及学生里有认不出的：" + "；".join(result.problems),
                detail={"field": "parties_text"},
            )
        saved.parties.clear()
        for student in result.students:
            saved.parties.append(ConflictParty(student_id=student.id, student_name=student.name))
        saved.parties_cache = "、".join(student.name for student in result.students)
        session.flush()

    return after_save


def apply_default_date(values: dict[str, Any], session: Session, row: Any = None) -> None:
    """通用：日期留空按今天（旧应用这几张表的日期默认都是今天）。"""
    if row is None and values.get("date") in (None, ""):
        values["date"] = date.today()


def chain(*hooks: Callable) -> Callable:
    """把几个保存前钩子串成一个。

    一张表往往既要把姓名解析成学生、又要补日期默认值 —— 注册表里 `before_save`
    只放得下一个，所以给一个把它们串起来的工具；返回的**回调**也会按顺序都执行。
    """
    def run(values: dict[str, Any], session: Session, row: Any = None) -> Callable[[Any], None] | None:
        callbacks = []
        for hook in hooks:
            produced = hook(values, session, row)
            if callable(produced):
                callbacks.append(produced)

        def after_save(saved: Any) -> None:
            for callback in callbacks:
                callback(saved)

        return after_save if callbacks else None

    return run


link_visit_student_with_date = chain(link_visit_student, apply_default_date)
link_talk_student_with_date = chain(link_talk_student, apply_default_date)
apply_meeting_with_date = chain(apply_meeting, apply_default_date)
apply_conflict_with_date = chain(apply_conflict, apply_default_date)
