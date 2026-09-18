"""设置：班级信息、存储占用、清空数据。

清空数据是**唯一的破坏性操作**，所以规矩定得死一点：

1. 要传一个确认串（`confirm="清空"`），不是点一下按钮就执行；
2. **每张表都必须有明确的处置规则**（见下面的三张清单 + `unclassified_tables`）——
   早期版本对「没有 `class_id` 列的表」一律无条件 DELETE，于是清 A 班会把 B 班的
   未交名单、考试科目、调解参与人一起删光，而界面上完全看不出来（阶段 5 评审实测）；
3. 动手之前先报**会删掉多少行**，让老师看清影响；
4. 媒体文件**默认不动**（几千张照片删了找不回来），要一起删得显式说明。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, NOT_FOUND, ApiError
from app.db.base import Base
from app.models.class_ import Class
from app.storage import media_store

# 清空数据时要**保留**的表：班级本身与字段定义、应用配置是「骨架」，不是业务数据。
KEEP_TABLES = {"classes", "student_field_def", "app_state"}

# 跨班共享的表：它们没有 class_id，但**不属于某一个班** —— 清一个班不该动它们。
# 模板是全班共用的素材；课程天生跨班（任课教师一门课教几个班，清掉一个班的块
# 不等于把课程删了 —— 那些块自己带 class_id，会被正常清掉）。
SHARED_TABLES = {"templates": "全班共用的素材", "courses": "课程（可能跨班）"}

# 没有 class_id 列的**子表**：删的时候按父表的班级过滤。
# 这几张表早先会被无条件 DELETE —— 这就是上面第 2 条说的那个事故。
CHILD_TABLES = {
    "homework_unsubmitted": ("homework", "homework_id"),
    "exam_subjects": ("exams", "exam_id"),
    "conflict_parties": ("conflicts", "conflict_id"),
    "duty_members": ("duty_groups", "duty_id"),
}

# 骨架表与子表的中文名（业务表的名字从注册表取，这里只补不在注册表里的）
SKELETON_TITLES = {
    "classes": "班级本身",
    "student_field_def": "学生档案字段定义",
    "app_state": "应用配置",
    "media": "照片与录音",
    # 这四张是**子表**（跟着父表走，注册表里没有它们自己的声明）。
    # 漏了它们的话，清空确认框里会出现 `homework_unsubmitted 12` 这种英文表名 ——
    # 列了行数也看不出是什么表（评审实测点过这条）
    "homework_unsubmitted": "作业未交名单",
    "exam_subjects": "考试科目与满分",
    "conflict_parties": "矛盾调解参与人",
    "duty_members": "值日成员",
}

CONFIRM_WORD = "清空"


def unclassified_tables() -> set[str]:
    """既不是班级范围、也没归进上面三张清单的表 —— **必须为空**（有测试守着）。

    这张清单的意义在于**失败要往安全的方向倒**：新加一张没 `class_id` 的表时，
    如果没人给它定处置规则，宁可测试红掉，也不能顺手把它整表删了。
    """
    known = KEEP_TABLES | set(SHARED_TABLES) | set(CHILD_TABLES) | {"media"}
    return {
        table.name
        for table in Base.metadata.sorted_tables
        if table.name not in known and "class_id" not in table.columns
    }


def _delete_scoped(session: Session, table: Any, class_id: int):
    """删这张表里属于这个班的行。返回执行结果（拿 rowcount）。"""
    if "class_id" in table.columns:
        return session.execute(table.delete().where(table.c.class_id == class_id))
    parent_name, fk_column = CHILD_TABLES[table.name]
    parent = Base.metadata.tables[parent_name]
    parent_ids = select(parent.c.id).where(parent.c.class_id == class_id)
    return session.execute(table.delete().where(table.c[fk_column].in_(parent_ids)))


def _count_scoped(session: Session, table: Any, class_id: int) -> int:
    """这张表里属于这个班的行数（与 `_delete_scoped` 同一套归属判定）。"""
    if "class_id" in table.columns:
        return session.scalar(
            select(func.count()).select_from(table).where(table.c.class_id == class_id)
        ) or 0
    if table.name in CHILD_TABLES:
        parent_name, fk_column = CHILD_TABLES[table.name]
        parent = Base.metadata.tables[parent_name]
        parent_ids = select(parent.c.id).where(parent.c.class_id == class_id)
        return session.scalar(
            select(func.count()).select_from(table).where(table.c[fk_column].in_(parent_ids))
        ) or 0
    return session.scalar(select(func.count()).select_from(table)) or 0


def get_class(session: Session, class_id: int) -> Class:
    row = session.get(Class, class_id)
    if row is None or row.deleted_at is not None:
        raise ApiError(NOT_FOUND, "这个班级不存在", status=404, detail={"id": class_id})
    return row


# 接口这一层用驼峰、模型用下划线（与别处的 classId / ownerId 一致），
# 所以这里把两种写法都认下来 —— 认一种的后果是「填了没保存」而界面不报错
CLASS_FIELD_KEYS = {
    "name": "name",
    "grade": "grade",
    "class_no": "class_no",
    "classNo": "class_no",
    "head_teacher_name": "head_teacher_name",
    "headTeacherName": "head_teacher_name",
    "room_name": "room_name",
    "roomName": "room_name",
    "youth_branch_name": "youth_branch_name",
    "youthBranchName": "youth_branch_name",
}


def update_class(session: Session, class_id: int, values: dict[str, Any]) -> Class:
    """改班级信息。空名字要说清楚，因为它会显示在首页与简报上。"""
    row = get_class(session, class_id)
    for key, column in CLASS_FIELD_KEYS.items():
        if key in values:
            setattr(row, column, str(values.get(key) or "").strip())
    if not row.name:
        raise ApiError(INVALID_VALUE, "班级名称不能为空（首页与简报都要显示它）", detail={"field": "name"})
    session.flush()
    return row


def settings_view(session: Session, class_id: int) -> dict[str, Any]:
    """设置页要的全部信息（班级 + 占用 + 数据目录）。"""
    row = get_class(session, class_id)
    return {
        "class": {
            "id": row.id,
            "grade": row.grade,
            "classNo": row.class_no,
            "name": row.name,
            "headTeacherName": row.head_teacher_name,
            "roomName": row.room_name,
            "youthBranchName": row.youth_branch_name,
        },
        "storage": media_store.storage_stats(),
        "tableCounts": table_counts(session, class_id),
    }


def table_counts(session: Session, class_id: int) -> list[dict[str, Any]]:
    """清空数据之前让老师看清影响：**会删多少行**，以及哪些表只是保留。

    表名给中文（旧版把 `homework_unsubmitted` 这种英文表名直接摆给老师看，
    列了行数也看不出是什么表）。`kept=True` 的是共享表：它们不在清理范围内。
    """
    from app.schemas.registry import get_spec  # 局部导入：避免 services ↔ schemas 的导入环

    rows = []
    for table in Base.metadata.sorted_tables:
        if table.name in KEEP_TABLES:
            continue
        spec = get_spec(table.name)
        title = (
            spec.title
            if spec is not None
            else SKELETON_TITLES.get(table.name, SHARED_TABLES.get(table.name, table.name))
        )
        rows.append(
            {
                "table": table.name,
                "title": title,
                "rows": _count_scoped(session, table, class_id),
                "kept": table.name in SHARED_TABLES,
                "reason": SHARED_TABLES.get(table.name, ""),
            }
        )
    return rows


def clear_business_data(
    session: Session, class_id: int, *, confirm: str, keep_media: bool = True
) -> dict[str, Any]:
    """清空这个班的业务数据（班级本身与字段定义保留）。

    媒体文件默认**不动** —— 照片与录音删了找不回来，要删得显式传 `keep_media=False`。
    """
    if str(confirm or "").strip() != CONFIRM_WORD:
        raise ApiError(
            INVALID_VALUE,
            f"这是不可撤销的操作。确认的话请在确认框里输入「{CONFIRM_WORD}」两个字。",
            detail={"field": "confirm"},
        )

    before = table_counts(session, class_id)
    removed = 0

    # 先子表后主表：外键开着，先删主表会被约束拦下
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in KEEP_TABLES or table.name in SHARED_TABLES:
            continue
        # 媒体库**单独处理**：它与业务数据不是一回事，而且已经有专门的清理入口
        # （「存储与清理」能按日期、按学生清）。所以「清空数据」默认不动它 ——
        # 几千张照片删了找不回来，不该混在一个顺手点的按钮里
        if table.name == "media":
            continue
        result = _delete_scoped(session, table, class_id)
        removed += result.rowcount or 0

    if not keep_media:
        media_table = Base.metadata.tables["media"]
        rows = session.execute(
            select(media_table.c.rel_path).where(media_table.c.class_id == class_id)
        ).all()
        for (rel_path,) in rows:
            try:
                media_store.remove_file(rel_path)
            except media_store.MediaError:
                pass
        result = session.execute(media_table.delete().where(media_table.c.class_id == class_id))
        removed += result.rowcount or 0

    session.flush()
    return {"removed": removed, "before": before, "mediaKept": keep_media}
