"""媒体文件：照片、录音、视频。

这是用户提的第三个痛点（「和家长沟通之后留档，照片和录音」）的落点。

与旧应用（`04` §3.1）的结构差别：

1. 旧应用把图片以 **base64 data URL 塞进那一个 localStorage 键**（头像 240px、多图 1200px、
   JPEG 0.82），于是配额是硬伤、导出会涨到几百 MB。这里**文件落盘**、库里只存元数据；
2. 旧应用**整个应用没有录音能力**。这里的音频是老师用手机录完之后**上传归档**的
   —— 本项目不触发录制、不要麦克风权限（用户已确认，见 `05` §7）；
3. 旧应用的 `meetings.photo` / `events.photo` 字段错配、照片字段是死的。这里用
   **多态归属**（`owner_table` + `owner_id`）统一表达「这条记录挂了哪些附件」，
   各模块只管声明自己支持哪几类。
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin

# 前三类是照片与音视频；`doc` 是顺手能收的文档（奖状扫描件之类）
MEDIA_KINDS = ("image", "audio", "video", "doc")
KIND_LABELS = {"image": "照片", "audio": "录音", "video": "视频", "doc": "文档"}
KIND_ORDER = {"image": 0, "audio": 1, "video": 2, "doc": 3}


class Media(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "media"
    __table_args__ = (
        # 「这条记录挂了哪些附件」是最主要的查询，按归属建索引
        Index("ix_media_owner", "owner_table", "owner_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # 多态归属：哪张表的哪条记录（如 contacts / 37）
    owner_table: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False)

    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    # 上传时的原始文件名 —— 老师认得出「这是跟张伟妈妈的_20260912.m4a」
    original_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    # 相对**数据目录**的路径（`media/2026/09/xxx.m4a`）。存相对路径，整个数据目录
    # 拷到另一台机器上仍然可用；删除时这个路径会指向 `trash/…`
    rel_path: Mapped[str] = mapped_column(String(255), nullable=False)
    mime: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, default=None)
    height: Mapped[int | None] = mapped_column(Integer, default=None)
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    # 文件内容指纹：同一份文件重复上传时复用已有文件，不再占盘
    sha256: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    # 浏览器能不能直接播。amr/aac 这类手机上常见、浏览器放不了的格式，
    # 界面上给「下载后播放」而不是假装能播（后端不转码，避免引入 ffmpeg）
    playable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    @property
    def size_text(self) -> str:
        size = float(self.size_bytes or 0)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} GB"

    @property
    def duration_text(self) -> str:
        if not self.duration_ms:
            return ""
        total = round(self.duration_ms / 1000)
        minutes, seconds = divmod(total, 60)
        return f"{minutes}:{seconds:02d}" if minutes else f"{seconds} 秒"
