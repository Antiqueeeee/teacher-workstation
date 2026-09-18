"""媒体接口：上传、原件、缩略图、删除回收、占用统计。

前端不拼文件路径 —— 附件列表里的每一项都带 `fileUrl` / `thumbUrl`，
界面只管把它们放到 `<img>` / `<audio>` 里。

**不做页内录音**（用户已确认，见 `05` §7）：没有 `MediaRecorder`、不要麦克风权限，
音频是老师用手机录完之后**上传归档**的。这里只负责收下来、读元数据、原样存着。
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.errors import INVALID_VALUE, NOT_FOUND, ApiError
from app.db.engine import get_session
from app.models.media import Media
from app.services import media_service
from app.services.class_scope import resolve_class_id
from app.services.media_service import list_all, list_for, to_dict
from app.schemas.registry import CONTACT
from app.services.params import as_date
from app.storage import media_store

router = APIRouter(prefix="/media", tags=["媒体库"])

DOWNLOAD_MIME = "application/octet-stream"


def _maybe_class(request: Request, session: Session) -> int | None:
    """`classId` 传了就用它，没传也不报错（附件列表跟着记录走，不必强制带班级）。"""
    raw = request.query_params.get("classId")
    if raw in (None, ""):
        return None
    return resolve_class_id(CONTACT, raw, session)


def _class_id(request: Request, session: Session) -> int:
    """整个班的附件视图用 —— 这个必须有班级（不然「这个班」无从谈起）。"""
    return resolve_class_id(CONTACT, request.query_params.get("classId"), session)


@router.post("", status_code=201)
def upload(
    request: Request,
    file: UploadFile = File(...),
    ownerTable: str = Form(...),
    ownerId: int = Form(...),
    note: str = Form(""),
    classId: str = Form(""),
    session: Session = Depends(get_session),
):
    """上传一个附件（照片 / 录音 / 视频 / 文档）。

    归属（哪张表的哪条记录）由前端传，服务层会**校验那条记录真的存在** ——
    不校验的话，一个拼错的表名就会造出谁也看不到的孤儿附件。
    """
    class_id = resolve_class_id(CONTACT, classId or request.query_params.get("classId"), session)
    media = media_service.save_media(
        session,
        class_id=class_id,
        owner_table=ownerTable,
        owner_id=ownerId,
        upload=file,
        note=note,
    )
    # **在返回之前提交**：文件已经落盘了，若数据库这一步失败，客户端却收到「上传成功」，
    # 盘上就会留下一份谁也看不到、也删不掉的孤儿文件（评审实测：yield 依赖的提交
    # 发生在响应之后，失败时客户端已经拿到 201）。提交失败就把文件收掉。
    _commit_or_cleanup(session, media)
    return {"ok": True, "data": to_dict(media)}


def _commit_or_cleanup(session: Session, media) -> None:
    """提交数据库；失败就把刚落盘的文件收掉，再让错误正常报出去。

    媒体与别的表不同：**盘上的文件不会跟着事务回滚**。不补偿的话，失败一次就多一份垃圾。
    """
    try:
        session.commit()
    except Exception:
        try:
            media_store.remove_file(media.rel_path)
        except media_store.MediaError:
            pass
        raise


@router.get("")
def list_media(request: Request, session: Session = Depends(get_session)):
    """一条记录的附件（`ownerTable` + `ownerId`），或整个班的附件（只给 `classId`）。"""
    params = request.query_params
    owner_table = (params.get("ownerTable") or "").strip()
    owner_id = params.get("ownerId")
    if owner_table and owner_id:
        media_service.owner_spec(owner_table)  # 不在注册表里 / 没声明 media_owner 就报错
        try:
            owner_pk = int(owner_id)
        except ValueError:
            raise ApiError(
                INVALID_VALUE, "ownerId 要是数字", detail={"ownerId": owner_id}
            ) from None
        return {
            "ok": True,
            "data": [
                to_dict(item)
                for item in list_for(session, owner_table, owner_pk, _maybe_class(request, session))
            ],
        }

    class_id = _class_id(request, session)
    rows = list_all(
        session,
        class_id,
        kind=(params.get("kind") or "").strip() or None,
        owner_table=owner_table or None,
    )
    return {"ok": True, "data": [to_dict(item) for item in rows]}


@router.get("/storage")
def storage():
    """真实占用（旧应用是按 5 MB 估算的，`:16711`）。"""
    return {"ok": True, "data": media_store.storage_stats()}


@router.get("/{media_id}/file")
def download(media_id: int, session: Session = Depends(get_session)):
    """原件。能不能在浏览器里直接播由 `playable` 决定，这里一律照实返回。"""
    media = media_service.get_media(session, media_id)
    try:
        path = media_store.absolute_path(media.rel_path)
    except media_store.MediaError as error:
        raise ApiError(NOT_FOUND, error.message, status=404) from None
    if not path.exists():
        raise ApiError(
            NOT_FOUND,
            f"文件不在磁盘上了（{media.original_name}）。可能是手工挪动过数据目录。",
            status=404,
            detail={"relPath": media.rel_path},
        )
    return FileResponse(
        path,
        media_type=media.mime or DOWNLOAD_MIME,
        filename=media.original_name or path.name,
    )


@router.get("/{media_id}/thumb")
def thumb(media_id: int, w: int = 320, session: Session = Depends(get_session)):
    """缩略图（图片）。列表用 320，点开看大的用 1200。"""
    media = media_service.get_media(session, media_id)
    if media.kind != "image":
        raise ApiError(INVALID_VALUE, "只有照片有缩略图", detail={"kind": media.kind})
    width = max(64, min(int(w or 320), 1600))
    path = media_store.thumbnail_for(media.rel_path, width)
    if path is None or not path.exists():
        raise ApiError(NOT_FOUND, "缩略图生成失败，请直接看原件", status=404)
    return FileResponse(path, media_type="image/jpeg")


@router.delete("/{media_id}")
def delete(media_id: int, session: Session = Depends(get_session)):
    """删除 → 进回收站（文件挪到 `data/trash/日期/`），记录标记删除，可恢复。"""
    media = media_service.get_media(session, media_id)
    media_service.delete_media(session, media)
    session.commit()  # 文件已经挪进回收站了，数据库这一步不能拖到响应之后
    return {"ok": True, "data": {"id": media_id}}


@router.post("/{media_id}/restore")
def restore(media_id: int, session: Session = Depends(get_session)):
    """从回收站恢复。"""
    media = session.get(Media, media_id)
    if media is None:
        raise ApiError(NOT_FOUND, "这个附件不存在", status=404, detail={"id": media_id})
    media_service.restore_media(session, media)
    session.commit()  # 同上：文件已经挪回来了
    return {"ok": True, "data": to_dict(media)}


@router.post("/purge")
def purge(request: Request, body: dict = Body(default_factory=dict), session: Session = Depends(get_session)):
    """按日期**真正清理**文件（默认只清录音，不动照片）。

    这是唯一会真正删文件的入口，所以要求显式传日期，且默认只覆盖 `audio`。
    """
    class_id = resolve_class_id(CONTACT, body.get("classId") or request.query_params.get("classId"), session)
    raw_date = str(body.get("before") or "").strip()
    if not raw_date:
        raise ApiError(INVALID_VALUE, "要指定清理哪一天之前的（before=YYYY-MM-DD）", detail={"field": "before"})
    kinds = tuple(body.get("kinds") or ("audio",))
    unknown = [kind for kind in kinds if kind not in media_service.kinds()]
    if unknown:
        raise ApiError(INVALID_VALUE, f"认不出的类型：{'、'.join(unknown)}", detail={"kinds": list(kinds)})
    student_raw = body.get("studentId")
    try:
        student_id = int(student_raw) if student_raw not in (None, "") else None
    except ValueError:
        raise ApiError(INVALID_VALUE, "studentId 要是数字", detail={"studentId": student_raw}) from None
    removed = media_service.purge(
        session, class_id, before=as_date(raw_date, "before"), kinds=kinds, student_id=student_id
    )
    session.commit()  # 文件已经真删了，数据库这一步不能拖到响应之后
    return {
        "ok": True,
        "data": {"removed": removed, "kinds": list(kinds), "studentId": student_id},
    }
