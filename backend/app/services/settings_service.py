"""设置：班级信息、存储占用、清空数据。

清空数据是**唯一的破坏性操作**，所以规矩定得死一点：

1. 要传一个确认串（`confirm="清空"`），不是点一下按钮就执行；
2. **对所有已知表生效** —— 表的清单从模型元数据取，不手工维护
   （旧应用只清种子键，懒建的表整体被丢弃，`:17617`）；
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
# 媒体文件另算（见 clear_business_data 的 keep_media）。
KEEP_TABLES = {"classes", "student_field_def", "app_state"}

CONFIRM_WORD = "清空"


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
    """每张业务表各有多少行（清空数据之前让老师看清影响）。"""
    counts = []
    for table in Base.metadata.sorted_tables:
        if table.name in KEEP_TABLES:
            continue
        # 有 class_id 的表按班统计，没有的（如媒体）统计全部
        if "class_id" in table.columns:
            count = session.scalar(
                select(func.count()).select_from(table).where(table.c.class_id == class_id)
            )
        else:
            count = session.scalar(select(func.count()).select_from(table))
        counts.append({"table": table.name, "rows": count or 0})
    return counts


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
        if table.name in KEEP_TABLES:
            continue
        if "class_id" in table.columns:
            # 媒体库**单独处理**：它与业务数据不是一回事，而且已经有专门的清理入口
            # （「存储与清理」能按日期、按学生清）。所以「清空数据」默认不动它 ——
            # 几千张照片删了找不回来，不该混在一个顺手点的按钮里
            if table.name == "media":
                continue
            result = session.execute(table.delete().where(table.c.class_id == class_id))
        else:
            result = session.execute(table.delete())
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
