"""媒体文件落盘：校验、写盘、缩略图、去重、删除与回收。

这一层只跟**文件**打交道，不知道 HTTP，也不碰数据库会话（除了去重查一下）。
上层 `services/media_service.py` 负责把文件记录与业务记录关联起来。

设计上的几条（来自 `04` §3.2）：

- **原件保持原始像素**，另生成 320 / 1200 两档缩略图（列表用 320，点开看 1200）；
- **按 sha256 去重**：同一份文件重复上传复用已有文件，不重复占盘；
- 图片读 **EXIF 方向并自动旋转**（旧应用没处理，手机上拍的照片经常躺着）；
- 音频**只读元数据、不转码**（不引入 ffmpeg）：`amr` 之类浏览器放不了的格式，
  标识出来让老师下载后播放，而不是假装能播；
- 删除进**回收站**（`data/trash/<日期>/`），可恢复；真正清理由「按日期清理」入口做。
"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from app.config import DATA_DIR, MEDIA_DIR

# 单文件大小上限（图片与音视频分开，和文档一致）
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_MEDIA_BYTES = 50 * 1024 * 1024

ALLOWED_IMAGE = {"jpg", "jpeg", "png", "webp", "gif", "bmp"}
ALLOWED_AUDIO = {"m4a", "mp3", "amr", "aac", "wav", "ogg", "opus", "3gp", "flac"}
ALLOWED_VIDEO = {"mp4", "mov", "m4v", "webm", "avi"}
ALLOWED_DOC = {"pdf", "doc", "docx", "xls", "xlsx", "txt"}

EXT_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "amr": "audio/amr",
    "aac": "audio/aac",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "opus": "audio/opus",
    "flac": "audio/flac",
    "3gp": "audio/3gpp",
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "m4v": "video/x-m4v",
    "webm": "video/webm",
    "avi": "video/x-msvideo",
    "pdf": "application/pdf",
}

# 浏览器普遍放不了的音频编码：标识出来，给「下载后播放」而不是假装能播
BROWSER_UNFRIENDLY_AUDIO = {"amr", "aac", "3gp", "opus"}

THUMB_WIDTHS = (320, 1200)
TRASH_DIR = DATA_DIR / "trash"

# 一个文件的生命周期里可能出现的问题（给上层转成中文提示）
class MediaError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class StoredFile:
    """落盘结果 —— 上层据此建 `media` 记录。"""

    rel_path: str
    original_name: str
    kind: str
    extension: str
    mime: str
    size_bytes: int
    sha256: str
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    playable: bool = True
    reused: bool = False


def extension_of(filename: str) -> str:
    return Path(filename or "").suffix.lower().lstrip(".")


def detect_kind(extension: str) -> str | None:
    if extension in ALLOWED_IMAGE:
        return "image"
    if extension in ALLOWED_AUDIO:
        return "audio"
    if extension in ALLOWED_VIDEO:
        return "video"
    if extension in ALLOWED_DOC:
        return "doc"
    return None


def rel_path_of(path: Path) -> str:
    """绝对路径 → 相对数据目录的路径（存库用相对路径，整目录拷走就能用）。"""
    return path.resolve().relative_to(DATA_DIR.resolve()).as_posix()


def absolute_path(rel_path: str) -> Path:
    """相对路径 → 绝对路径。**只接受我们自己存进去的相对路径** ——
    拼进 `..` 就能读到数据目录外的文件，所以这里拦住（即便调用方是内部代码）。"""
    candidate = (DATA_DIR / rel_path).resolve()
    if not str(candidate).startswith(str(DATA_DIR.resolve())):
        raise MediaError("MEDIA_BAD_PATH", "文件路径不合法")
    return candidate


def _read_upload(upload: Any) -> bytes:
    """把上传流读成 bytes 并检查大小。超限立刻报错，不先落盘再检查。"""
    upload.file.seek(0) if hasattr(upload, "file") else None
    data = upload.file.read() if hasattr(upload, "file") else upload.read()
    limit = MAX_MEDIA_BYTES
    if len(data) > limit:
        raise MediaError(
            "MEDIA_TOO_LARGE",
            f"文件太大（{len(data) / 1024 / 1024:.1f} MB），单个文件上限 {limit // 1024 // 1024} MB。"
            "录音传到电脑上压缩一下，或切成几段再传。",
        )
    if not data:
        raise MediaError("MEDIA_EMPTY", "这个文件是空的")
    return data


def _store(extension: str, data: bytes) -> Path:
    today = date.today()
    folder = MEDIA_DIR / f"{today.year:04d}" / f"{today.month:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}.{extension}"
    path.write_bytes(data)
    return path


def _thumb_path(original: Path, width: int) -> Path:
    folder = MEDIA_DIR / "thumbs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{original.stem}_{width}.jpg"


def make_thumbnails(original: Path) -> None:
    """生成两档缩略图。**顺带按 EXIF 方向把原件摆正**（旧应用没做，手机照片常躺着）。"""
    with Image.open(original) as image:
        fixed = ImageOps.exif_transpose(image)
        if fixed is not image and fixed.size != image.size:
            # 方向确实需要调整：把摆正后的原件写回去（保持格式）
            if original.suffix.lower() in {".jpg", ".jpeg"}:
                fixed.convert("RGB").save(original, quality=92)
            elif original.suffix.lower() == ".png":
                fixed.save(original)
        for width in THUMB_WIDTHS:
            thumb = fixed.copy()
            thumb.thumbnail((width, width * 4))  # 只按宽缩，长图不裁
            if thumb.mode not in ("RGB", "L"):
                thumb = thumb.convert("RGB")
            thumb.save(_thumb_path(original, width), "JPEG", quality=82)


def thumbnail_for(rel_path: str, width: int = 320) -> Path | None:
    """取最接近的缩略图；没生成过就现生成一张（例如 w=800 这种请求）。"""
    original = absolute_path(rel_path)
    if not original.exists():
        return None
    candidates = [w for w in THUMB_WIDTHS if w >= width]
    if candidates:
        existing = _thumb_path(original, min(candidates))
        if existing.exists():
            return existing
    try:
        with Image.open(original) as image:
            thumb = ImageOps.exif_transpose(image)
            thumb.thumbnail((width, width * 4))
            if thumb.mode not in ("RGB", "L"):
                thumb = thumb.convert("RGB")
            target = MEDIA_DIR / "thumbs" / f"{original.stem}_{width}.jpg"
            target.parent.mkdir(parents=True, exist_ok=True)
            thumb.save(target, "JPEG", quality=82)
            return target
    except Exception:  # noqa: BLE001 - 读不了图就别让整个请求挂掉，交给上层当「没有缩略图」
        return None


def read_image_size(path: Path) -> tuple[int | None, int | None]:
    try:
        with Image.open(path) as image:
            return image.width, image.height
    except Exception:  # noqa: BLE001
        return None, None


def read_duration_ms(path: Path, extension: str) -> int | None:
    """读音频/视频时长。读不出来返回 None（不猜、不靠用户填）。"""
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(path)
        if audio is not None and getattr(audio, "info", None) is not None:
            length = getattr(audio.info, "length", None)
            if length:
                return int(length * 1000)
    except Exception:  # noqa: BLE001 - amr 之类 mutagen 不认识，就当读不出来
        return None
    return None


def store_upload(upload: Any, *, existing_sha: set[str] | None = None) -> StoredFile:
    """把上传的文件落盘，返回元数据。**重复内容复用已有文件**（按 sha256）。"""
    original_name = str(getattr(upload, "filename", "") or "未命名")
    extension = extension_of(original_name)
    kind = detect_kind(extension)
    if kind is None:
        raise MediaError(
            "MEDIA_BAD_TYPE",
            f"不支持的格式「.{extension or '未知'}」。"
            "照片用 jpg/png，录音用 m4a/mp3/amr/aac/wav，视频用 mp4/mov。",
        )

    data = _read_upload(upload)
    if kind == "image" and len(data) > MAX_IMAGE_BYTES:
        raise MediaError(
            "MEDIA_TOO_LARGE",
            f"照片太大（{len(data) / 1024 / 1024:.1f} MB），单张上限 {MAX_IMAGE_BYTES // 1024 // 1024} MB。",
        )

    digest = hashlib.sha256(data).hexdigest()
    playable = not (kind == "audio" and extension in BROWSER_UNFRIENDLY_AUDIO)

    if existing_sha and digest in existing_sha:
        # 同一份内容已经有一份文件了：复用它的路径，不再占盘（照片重复传很常见）
        return StoredFile(
            rel_path="",  # 上层用查到的已有记录补上
            original_name=original_name,
            kind=kind,
            extension=extension,
            mime=EXT_MIME.get(extension, "application/octet-stream"),
            size_bytes=len(data),
            sha256=digest,
            playable=playable,
            reused=True,
        )

    path = _store(extension, data)
    width = height = duration = None
    if kind == "image":
        width, height = read_image_size(path)
        make_thumbnails(path)
    elif kind in ("audio", "video"):
        duration = read_duration_ms(path, extension)

    return StoredFile(
        rel_path=rel_path_of(path),
        original_name=original_name,
        kind=kind,
        extension=extension,
        mime=EXT_MIME.get(extension, "application/octet-stream"),
        size_bytes=len(data),
        sha256=digest,
        width=width,
        height=height,
        duration_ms=duration,
        playable=playable,
    )


def move_to_trash(rel_path: str) -> str:
    """把一个文件挪进回收站，返回新的相对路径（恢复时挪回来用）。

    校验失败（文件不在）时原样返回 —— 记录该删还是要删，不能因为文件丢了就卡住。
    """
    source = absolute_path(rel_path)
    if not source.exists():
        return rel_path
    folder = TRASH_DIR / date.today().isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / source.name
    shutil.move(str(source), str(target))
    return rel_path_of(target)


def restore_from_trash(rel_path: str, *, extension: str) -> str:
    """把回收站里的文件挪回媒体目录（放回新的年/月目录）。"""
    source = absolute_path(rel_path)
    if not source.exists():
        return rel_path
    today = date.today()
    folder = MEDIA_DIR / f"{today.year:04d}" / f"{today.month:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{uuid.uuid4().hex}.{extension}"
    shutil.move(str(source), str(target))
    return rel_path_of(target)


def remove_file(rel_path: str) -> None:
    """真正删掉一个文件（按日期清理用）。文件不在就什么也不做。"""
    path = absolute_path(rel_path)
    if path.exists():
        path.unlink()


def folder_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def storage_stats() -> dict[str, Any]:
    """真实遍历目录算占用（旧应用是按 5 MB 估算，`:16711`）。"""
    from app.config import DB_PATH

    media_size = 0
    media_count = 0
    if MEDIA_DIR.exists():
        for item in MEDIA_DIR.rglob("*"):
            if item.is_file() and "thumbs" not in item.parts:
                media_size += item.stat().st_size
                media_count += 1
    return {
        "dataDir": str(DATA_DIR),
        "database": DB_PATH.stat().st_size if DB_PATH.exists() else 0,
        "media": media_size,
        "mediaCount": media_count,
        "thumbs": folder_size(MEDIA_DIR / "thumbs"),
        "trash": folder_size(TRASH_DIR),
    }
