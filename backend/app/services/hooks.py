"""保存前钩子的小工具。

**这个模块不能 import 注册表**（`schemas.registry`）：表声明（`schemas/specs/*.py`）
会 import 服务层的钩子，而注册表要等声明都导入完才建好 —— 一条链上只要有一环
回头 import 注册表，就是循环导入（踩过一次：把 `chain` 放在 `table_write` 里，
而 `table_write` 要 FieldSpec）。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from sqlalchemy.orm import Session

def chain(*hooks: Callable) -> Callable:
    """把几个保存前钩子串成一个。

    声明里 `before_save` 只放得下一个，而一张表往往既要把姓名解析成学生、
    又要补日期默认值 —— 所以给一个把它们串起来的工具；返回的**回调**也按顺序都执行。
    """
    def run(values: dict[str, Any], session: Session, row: Any = None) -> Callable | None:
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


def default_today(*, field: str = "date", on_create_only: bool = True) -> Callable:
    """生成一个「这个日期字段留空就按今天」的保存前钩子。

    旧应用几类记录的日期默认值都是今天；这里统一做一次，免得每张表各写一遍
    （而各写一遍的结果是有的表留空报「必填」、有的表悄悄填今天）。
    """
    def hook(values: dict[str, Any], _session: Session, row: Any = None) -> None:
        if on_create_only and row is not None:
            return
        if values.get(field) in (None, ""):
            from datetime import date as _date

            values[field] = _date.today()

    return hook



