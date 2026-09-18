"""跨模块共享的词表。

`SUBJECTS` 同时被作业情况与成绩分析使用；`DEFAULT_FULL_MARKS` 是各科满分默认值。
放在这里而不是各自模块里：**同一个词表在同一个项目里只能有一份** ——
两边各写一遍，改一处忘一处，出现的就是「作业里能选到地理、成绩里选不到」这类
不报错的不一致。
"""

from __future__ import annotations

# 与旧应用一致（`:6220` 的 SUBJECTS）
SUBJECTS = ("语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理")

# 与旧应用一致（`:12009` 的 DEFAULT_FULL）：语数英 150，其余 100。
# 这是**新建考试时各科满分的默认值**，每场考试可以单独改（见 exam_subjects 表）
DEFAULT_FULL_MARKS = {
    "语文": 150,
    "数学": 150,
    "英语": 150,
    "物理": 100,
    "化学": 100,
    "生物": 100,
    "政治": 100,
    "历史": 100,
    "地理": 100,
}


def subject_order(subject: str) -> int:
    """科目在词表里的位置，用来给列表排序 —— 别名/未知科目排在最后。"""
    try:
        return SUBJECTS.index(subject)
    except ValueError:
        return len(SUBJECTS)
