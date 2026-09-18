"""作业：把「未交名单」解析成学生关联，并算出提交率。

**这条规则只在这里实现一次。** 旧应用在这件事上有三套互不相通的口径（见
`models/homework.py` 的说明），结果是同一个「提交率」在列表、学生档案、首页各是一个数。

两个刻意的取舍：
1. `total`（应交人数）是创建时的快照，之后不会因为学生转入转出而变 ——
   否则「上周的提交率」会自己变化，历史数据失去可比性；
2. 应交 0 人时提交率返回 `None`（界面显示「—」），**不假装 100%** ——
   旧应用在这种边界上返回 100，看起来像「全都交了」。
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, ApiError
from app.models.homework import HomeworkUnsubmitted
from app.services.roster import count_class_students, resolve_names, split_names


def compute_rate(total: int | None, unsubmitted: int) -> int | None:
    """提交率 = (应交 − 未交) / 应交。应交 0 人时返回 None。"""
    if not total or total <= 0:
        return None
    missing = max(0, min(unsubmitted, total))  # 名单比应交人数还多时按应交人数封顶
    return round((total - missing) / total * 100)


def effective_rate(mode: str, manual: Any, total: int | None, unsubmitted: int) -> int | None:
    """生效的提交率：手工模式用手填值（夹在 0–100），否则按名单算。"""
    if mode == "手工" and manual not in (None, ""):
        return max(0, min(int(manual), 100))
    return compute_rate(total, unsubmitted)


def apply_homework(values: dict[str, Any], session: Session, row: Any = None) -> Callable[[Any], None]:
    """作业的保存前钩子：解析名单、补齐应交人数，落库后再写子表并算出提交率。

    返回的**回调**在行拿到 id 之后执行 —— 未交名单是子表，必须先有作业 id。
    """
    # 名单是子表关系，不是列：从 values 里摘出来（normalize 只是按声明校验过它）
    text = values.pop("unsubmitted_names", None)
    class_id = values.get("class_id") or getattr(row, "class_id", None)

    if values.get("total") in (None, ""):
        # 没填就取当前全班人数（快照），而不是留 0 —— 留 0 会让提交率永远是「—」
        values["total"] = count_class_students(session, class_id) if class_id else 0

    def after_save(saved: Any) -> None:
        if text is not None:
            result = resolve_names(session, split_names(text), saved.class_id)
            if not result.ok:
                # 认不出人时**整条不写**：把问题说清楚，让人改名单，而不是猜
                raise ApiError(
                    INVALID_VALUE,
                    "未交名单里有认不出的学生：" + "；".join(result.problems),
                    detail={"field": "unsubmitted_names"},
                )
            saved.unsubmitted.clear()
            for student in result.students:
                saved.unsubmitted.append(
                    HomeworkUnsubmitted(student_id=student.id, student_name=student.name)
                )
            session.flush()

        # 提交率在这里算：它依赖上面刚写好的子表，也算唯一一处口径
        saved.rate = effective_rate(saved.rate_mode, saved.rate_manual, saved.total, len(saved.unsubmitted))

    return after_save
