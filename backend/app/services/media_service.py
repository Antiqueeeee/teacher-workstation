"""媒体的业务规则：归属校验、去重、删除回收、按日期清理。

「附件挂在哪条记录上」这件事必须校验 —— 不校验的话，一个拼错的表名就会造出
**谁也看不到的孤儿附件**（占着盘、界面上找不到）。所以归属表有一份白名单，
而且会确认那条记录真的存在。

白名单随着「沟通留档」类模块的落地逐条增加（阶段 4 先有 `contacts`，
阶段 5 补 `visits` / `talks` / `meetings` / `class_activities` / `events` / `conflicts`）。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, NOT_FOUND, ApiError
from app.models.media import KIND_ORDER, MEDIA_KINDS, Media
from app.storage import media_store
from app.storage.media_store import MediaError

def owner_spec(owner_table: str):
    """哪张表能挂附件 —— **从注册表读**（表声明里的 `media_owner`），不在这里维护名单。

    原先是一份手写的白名单，加一个模块就要记得改两处 —— 而漏改的表现是
    「这个模块还不支持挂附件」，加模块的人得翻到媒体服务里才知道为什么。
    """
    from app.schemas.registry import get_spec  # 局部导入：注册表构建期不依赖本模块

    spec = get_spec(owner_table)
    if spec is None or not spec.media_owner:
        raise ApiError(
            INVALID_VALUE,
            f"「{owner_table}」这个模块不支持挂附件",
            detail={"field": "ownerTable"},
        )
    return spec


def owner_label(owner_table: str) -> str:
    try:
        return owner_spec(owner_table).title
    except ApiError:
        return owner_table


def _require_owner(session: Session, class_id: int, owner_table: str, owner_id: int):
    spec = owner_spec(owner_table)
    owner = session.get(spec.model, owner_id)
    if owner is None or getattr(owner, "deleted_at", None) is not None:
        raise ApiError(
            NOT_FOUND,
            f"要挂附件的那条{owner_label(owner_table)}不存在，可能已被删除。请先保存记录，再传附件。",
            status=404,
            detail={"ownerId": owner_id},
        )
    if getattr(owner, "class_id", class_id) != class_id:
        raise ApiError(
            INVALID_VALUE,
            "这条记录不属于当前班级，不能挂附件",
            detail={"ownerId": owner_id},
        )
    return owner


def _existing_shas(session: Session, class_id: int) -> dict[str, Media]:
    """**这个班**已有的内容指纹 —— 同一份文件复用，不再占盘。

    按班查而不是按「同一条记录」查：文档 §3.2 说的是「同一份文件重复上传复用已有文件」，
    同一张照片挂到第二条沟通记录上同样不该再存一份（评审实测原先会存两份）。
    并发首次上传同一文件时两边都看不到对方，会各写一份 —— 去重是尽力而为，不是保证。
    """
    rows = session.scalars(
        select(Media).where(Media.deleted_at.is_(None), Media.class_id == class_id)
    )
    return {row.sha256: row for row in rows if row.sha256}


def save_media(
    session: Session,
    *,
    class_id: int,
    owner_table: str,
    owner_id: int,
    upload: Any,
    note: str = "",
) -> Media:
    """上传一个附件。内容重复时复用已有文件（不重复占盘），另建一条记录。"""
    owner = _require_owner(session, class_id, owner_table, owner_id)
    existing = _existing_shas(session, class_id)

    try:
        stored = media_store.store_upload(upload, existing_sha=set(existing))
    except MediaError as error:
        raise ApiError(error.code, error.message) from None

    reused = existing.get(stored.sha256) if stored.reused else None
    if reused is not None:
        rel_path = reused.rel_path
        width, height, duration = reused.width, reused.height, reused.duration_ms
    else:
        rel_path, width, height, duration = (
            stored.rel_path,
            stored.width,
            stored.height,
            stored.duration_ms,
        )

    order = session.scalar(
        select(Media.sort_order)
        .where(Media.owner_table == owner_table, Media.owner_id == owner_id)
        .order_by(Media.sort_order.desc())
        .limit(1)
    )
    media = Media(
        class_id=class_id,
        owner_table=owner_table,
        owner_id=owner_id,
        # 归属记录带有学生时一并记下来：既能按学生清理（`04` §3.5），
        # 也让「这个附件跟谁有关」在库里说得清，不必回头 join 各业务表
        student_id=getattr(owner, "student_id", None),
        kind=stored.kind,
        original_name=stored.original_name,
        rel_path=rel_path,
        mime=stored.mime,
        # 大小照实记：去重复用时也显示真实大小（记 0 的话界面上显示「0 B」，
        # 而老师看到的是两张各有大小的照片）
        size_bytes=stored.size_bytes,
        width=width,
        height=height,
        duration_ms=duration,
        sha256=stored.sha256,
        playable=stored.playable,
        sort_order=(order or 0) + 1,
        note=note or "",
    )
    session.add(media)
    session.flush()
    return media


def list_for(session: Session, owner_table: str, owner_id: int, class_id: int | None = None) -> list[Media]:
    """一条记录的附件列表：照片在前、音视频在后，同类按添加顺序。"""
    query = select(Media).where(
        Media.deleted_at.is_(None),
        Media.owner_table == owner_table,
        Media.owner_id == owner_id,
    )
    if class_id is not None:
        query = query.where(Media.class_id == class_id)
    rows = list(session.scalars(query))
    return sorted(rows, key=lambda item: (KIND_ORDER.get(item.kind, 9), item.sort_order, item.id))


def list_all(
    session: Session, class_id: int, *, kind: str | None = None, owner_table: str | None = None
) -> list[Media]:
    """整个班的附件（媒体库页面用）。"""
    query = select(Media).where(Media.deleted_at.is_(None), Media.class_id == class_id)
    if kind:
        query = query.where(Media.kind == kind)
    if owner_table:
        query = query.where(Media.owner_table == owner_table)
    rows = list(session.scalars(query))
    return sorted(rows, key=lambda item: (item.created_at, item.id), reverse=True)


def get_media(session: Session, media_id: int, *, include_deleted: bool = False) -> Media:
    """取一条附件记录。默认只认未删除的。

    `include_deleted=True` 给「从回收站恢复」用 —— 它要找的**正是**那条已删除的记录
    （这里的 deleted_at 是软删除标记，不代表文件没了）。
    """
    media = session.get(Media, media_id)
    if media is None or (media.deleted_at is not None and not include_deleted):
        raise ApiError(NOT_FOUND, "这个附件不存在，可能已被删除", status=404, detail={"id": media_id})
    return media


def delete_media(session: Session, media: Media) -> str:
    """删除 → 进回收站（可恢复），不是直接抹掉文件。

    只有**没有别的记录引用同一个文件**时才挪文件（按 sha256 复用过的文件可能
    被多条记录引用，挪走会让另一条记录的附件也失效）。
    """
    from app.db.base import utcnow

    media.deleted_at = utcnow()
    shared = session.scalars(
        select(Media).where(
            Media.id != media.id,
            Media.deleted_at.is_(None),
            Media.sha256 == media.sha256,
            Media.rel_path == media.rel_path,
        )
    ).first()
    if shared is None:
        try:
            # 挪完之后**路径要写回记录**，否则回收站形同虚设：文件挪走了、库里还指着
            # 老路径，恢复时也找不到它（这条是测试抓出来的）
            media.rel_path = media_store.move_to_trash(media.rel_path)
        except MediaError:
            pass
    return media.rel_path


def restore_media(session: Session, media: Media) -> Media:
    """从回收站恢复：把文件挪回媒体目录，清掉删除标记。

    文件不在（有人手工清了 `data/trash/`）时**明确拒绝** —— 不能清掉删除标记就说
    「恢复成功」，那样记录指着一条不存在的路径，取原件时 404，还说「可能手工挪过数据目录」，
    把责任推给老师（评审实测）。
    """
    if media.deleted_at is None:
        return media
    restored = media_store.restore_from_trash(
        media.rel_path, extension=media_store.extension_of(media.rel_path)
    )
    if restored == media.rel_path:
        raise ApiError(
            NOT_FOUND,
            "回收站里已经没有这个文件了，没法恢复。它可能在 trash 目录里被手工清掉了。",
            status=404,
            detail={"relPath": media.rel_path},
        )
    media.rel_path = restored
    media.deleted_at = None
    session.flush()
    return media


def purge(
    session: Session,
    class_id: int,
    *,
    before: date,
    kinds: tuple[str, ...] = ("audio",),
    student_id: int | None = None,
) -> int:
    """按日期**真正清理**媒体文件（默认只清录音，不动照片 —— `04` §3.5 的入口）。

    这是唯一会真正删文件的入口，所以要求显式传日期；可以再按学生过滤
    （对应「删除某学生全部音频」那个入口）。

    **文件的删法不能看「还有谁在用」的即时查询**：会话是 `autoflush=False`，
    循环里已经 `session.delete()` 但还没落库的行照样查得到，于是每一条都以为
    「别人还在用」，最后记录删空了、文件一份没删（评审实测：提示清理 4 条、磁盘没变）。
    这里改成先把「要留下的路径」一次收齐，再逐条决定是否落盘删除。
    """
    all_rows = list(session.scalars(select(Media).where(Media.class_id == class_id)))

    def is_target(media: Media) -> bool:
        if media.kind not in kinds:
            return False
        if student_id is not None and media.student_id != student_id:
            return False
        return bool(media.created_at and media.created_at.date() <= before)

    targets = [media for media in all_rows if is_target(media)]
    keep_paths = {media.rel_path for media in all_rows if not is_target(media)}

    removed = 0
    for media in targets:
        if media.rel_path not in keep_paths:
            try:
                media_store.remove_file(media.rel_path)
            except MediaError:
                pass
        session.delete(media)
        removed += 1
    session.flush()
    return removed


def attach_counts(
    session: Session, owner_table: str, rows: list[Any], class_id: int | None = None
) -> None:
    """给一页记录批量填上附件数（`row.attachment_count`）。

    一次分组查询搞定，不是每条记录查一次 —— 列表页一页 20 条就是 20 次查询。
    由通用列表在序列化前调用（`spec.media_owner`），支持附件的模块都不必自己写。
    """
    ids = [row.id for row in rows]
    if not ids:
        return
    query = (
        select(Media.owner_id, func.count())
        .where(
            Media.deleted_at.is_(None),
            Media.owner_table == owner_table,
            Media.owner_id.in_(ids),
        )
        .group_by(Media.owner_id)
    )
    if class_id is not None:
        query = query.where(Media.class_id == class_id)
    counts = dict(session.execute(query).all())
    for row in rows:
        row._attachment_count = counts.get(row.id, 0)


def to_dict(media: Media) -> dict[str, Any]:
    """给前端的形状：附件本身 + 能直接用的 URL（界面不拼路径）。"""
    return {
        "id": media.id,
        "kind": media.kind,
        "kindLabel": media.kind_label,
        "originalName": media.original_name,
        "mime": media.mime,
        "size": media.size_bytes,
        "sizeText": media.size_text,
        "width": media.width,
        "height": media.height,
        "durationMs": media.duration_ms,
        "durationText": media.duration_text,
        "playable": media.playable,
        "note": media.note,
        "createdAt": media.created_at.isoformat(timespec="seconds") if media.created_at else None,
        "fileUrl": f"/api/v1/media/{media.id}/file",
        "thumbUrl": f"/api/v1/media/{media.id}/thumb" if media.kind == "image" else None,
        # 点开放大用的图：前端不拼路径（拼错了只有点开才发现）
        "largeUrl": f"/api/v1/media/{media.id}/thumb?w=1200" if media.kind == "image" else None,
        "studentId": media.student_id,
        "ownerTable": media.owner_table,
        "ownerId": media.owner_id,
    }


def kinds() -> tuple[str, ...]:
    return MEDIA_KINDS
