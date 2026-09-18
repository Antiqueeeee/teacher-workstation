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
from app.models.contact import ContactLog
from app.models.media import KIND_ORDER, MEDIA_KINDS, Media
from app.storage import media_store
from app.storage.media_store import MediaError

# 归属表白名单：表名 → 模型。要挂附件的新模块在这里登记。
OWNER_TABLES: dict[str, Any] = {
    "contacts": ContactLog,
}
OWNER_LABELS = {"contacts": "家长联系记录"}


def owner_label(owner_table: str) -> str:
    return OWNER_LABELS.get(owner_table, owner_table)


def _require_owner(session: Session, class_id: int, owner_table: str, owner_id: int):
    model = OWNER_TABLES.get(owner_table)
    if model is None:
        raise ApiError(
            INVALID_VALUE,
            f"「{owner_table}」这个模块还不支持挂附件",
            detail={"field": "ownerTable"},
        )
    owner = session.get(model, owner_id)
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


def _existing_shas(session: Session, class_id: int, owner_table: str, owner_id: int) -> dict[str, Media]:
    """同一批附件里已经有的内容指纹 —— 用来做**批内去重**（同一张照片传两次很常见）。"""
    rows = session.scalars(
        select(Media).where(
            Media.deleted_at.is_(None),
            Media.class_id == class_id,
            Media.owner_table == owner_table,
            Media.owner_id == owner_id,
        )
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
    _require_owner(session, class_id, owner_table, owner_id)
    existing = _existing_shas(session, class_id, owner_table, owner_id)

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


def list_for(session: Session, owner_table: str, owner_id: int) -> list[Media]:
    """一条记录的附件列表：照片在前、音视频在后，同类按添加顺序。"""
    rows = list(
        session.scalars(
            select(Media).where(
                Media.deleted_at.is_(None),
                Media.owner_table == owner_table,
                Media.owner_id == owner_id,
            )
        )
    )
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


def get_media(session: Session, media_id: int) -> Media:
    media = session.get(Media, media_id)
    if media is None or media.deleted_at is not None:
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
    """从回收站恢复：把文件挪回媒体目录，清掉删除标记。"""
    if media.deleted_at is None:
        return media
    media.rel_path = media_store.restore_from_trash(
        media.rel_path, extension=media_store.extension_of(media.rel_path)
    )
    media.deleted_at = None
    session.flush()
    return media


def purge(session: Session, class_id: int, *, before: date, kinds: tuple[str, ...] = ("audio",)) -> int:
    """按日期清理媒体文件（默认只清录音，不动照片 —— `04` §3.5 的入口）。

    这是**真正删文件**的动作：先删文件再删记录，界面上会二次确认并说明清了几个。
    """
    rows = list(
        session.scalars(
            select(Media).where(Media.class_id == class_id, Media.kind.in_(kinds))
        )
    )
    removed = 0
    for media in rows:
        if media.created_at.date() > before:
            continue
        others = session.scalars(
            select(Media).where(
                Media.id != media.id, Media.rel_path == media.rel_path
            )
        ).first()
        if others is None:
            try:
                media_store.remove_file(media.rel_path)
            except MediaError:
                pass
        session.delete(media)
        removed += 1
    session.flush()
    return removed


def attach_counts(session: Session, owner_table: str, rows: list[Any]) -> None:
    """给一页记录批量填上附件数（`row.attachment_count`）。

    一次分组查询搞定，不是每条记录查一次 —— 列表页一页 20 条就是 20 次查询。
    挂在通用列表的输出里（`spec.media_owner`），所以每个支持附件的模块都不用自己写。
    """
    ids = [row.id for row in rows]
    if not ids:
        return
    counts = dict(
        session.execute(
            select(Media.owner_id, func.count())
            .where(
                Media.deleted_at.is_(None),
                Media.owner_table == owner_table,
                Media.owner_id.in_(ids),
            )
            .group_by(Media.owner_id)
        ).all()
    )
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
        "ownerTable": media.owner_table,
        "ownerId": media.owner_id,
    }


def kinds() -> tuple[str, ...]:
    return MEDIA_KINDS
