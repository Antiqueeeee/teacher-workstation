"""媒体库的端到端测试 —— 用户提的第三个痛点（照片与录音归档）。

旧应用把图片 base64 塞进那一个 localStorage 键、**整个应用没有录音能力**。
这里的用例守住新做法的几条底线：文件落盘、元数据（尺寸/时长）由后端读、
同一份文件不重复占盘、删除进回收站而不是直接抹掉、按日期清理只动录音不动照片。
"""

from __future__ import annotations

import io
import wave

from PIL import Image
from sqlalchemy import select

from app.models.class_ import Class
from app.models.student import Student
from app.storage import media_store


def _class_id(session) -> int:
    return session.scalar(select(Class.id).where(Class.deleted_at.is_(None)).limit(1))


def _student(session, name: str, sno: str) -> Student:
    student = Student(class_id=_class_id(session), name=name, sno=sno, extra={})
    session.add(student)
    session.commit()
    return student


def _contact(client, class_id: int, name: str, **overrides) -> dict:
    payload = {
        "date": "2026-09-15",
        "student_name": name,
        "channel": "电话",
        "category": "成绩",
        "content": "聊了月考成绩",
    }
    payload.update(overrides)
    response = client.post("/api/v1/contacts", json=payload, params={"classId": class_id})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _png(width: int = 800, height: int = 600, color=(200, 40, 40)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, "PNG")
    return buffer.getvalue()


def _wav(seconds: float = 1.5, rate: int = 8000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return buffer.getvalue()


def _upload(client, class_id: int, owner_id: int, name: str, data: bytes, mime: str = "application/octet-stream"):
    return client.post(
        "/api/v1/media",
        files={"file": (name, data, mime)},
        data={"ownerTable": "contacts", "ownerId": str(owner_id), "classId": str(class_id)},
    )


# ---------- 上传与元数据 ----------


def test_upload_photo_reads_size_and_makes_thumbnails(client, db_session):
    class_id = _class_id(db_session)
    student = _student(db_session, "留档照片甲", "M9001")
    contact = _contact(client, class_id, student.name)

    response = _upload(client, class_id, contact["id"], "家访现场.png", _png(800, 600), "image/png")
    assert response.status_code == 201, response.text
    media = response.json()["data"]

    assert media["kind"] == "image"
    assert media["kindLabel"] == "照片"
    # 尺寸由**后端读**，不靠用户填
    assert (media["width"], media["height"]) == (800, 600)
    assert media["thumbUrl"] and media["fileUrl"]
    assert media["originalName"] == "家访现场.png"

    # 文件真的落盘了，而且在 media/年/月/ 下
    path = media_store.absolute_path(_rel_path(db_session, media["id"]))
    assert path.exists() and "media" in str(path)

    thumb = client.get(media["thumbUrl"])
    assert thumb.status_code == 200
    assert thumb.headers["content-type"].startswith("image/jpeg")
    with Image.open(io.BytesIO(thumb.content)) as image:
        assert image.width == 320  # 列表用 320 档


def _rel_path(session, media_id: int) -> str:
    from app.models.media import Media

    return session.get(Media, media_id).rel_path


def test_upload_audio_reads_duration_without_transcoding(client, db_session):
    class_id = _class_id(db_session)
    student = _student(db_session, "留档录音甲", "M9002")
    contact = _contact(client, class_id, student.name)

    response = _upload(
        client, class_id, contact["id"], "和妈妈的电话.wav", _wav(1.5), "audio/wav"
    )
    assert response.status_code == 201, response.text
    media = response.json()["data"]

    assert media["kind"] == "audio"
    assert media["durationMs"] and 1400 <= media["durationMs"] <= 1700
    assert media["durationText"]
    assert media["playable"] is True  # wav 浏览器能放
    assert media["thumbUrl"] is None  # 只有照片有缩略图

    # 原件能取到，且是原样返回（音频不转码）
    original = client.get(media["fileUrl"])
    assert original.status_code == 200
    assert original.content == _wav(1.5)


def test_phone_audio_format_is_marked_not_playable(client, db_session):
    """手机常见的 amr/aac 浏览器放不了 —— 标出来让老师下载后播放，而不是假装能播。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "留档录音乙", "M9003")
    contact = _contact(client, class_id, student.name)

    response = _upload(client, class_id, contact["id"], "通话录音.amr", b"\x00" * 512)
    assert response.status_code == 201, response.text
    media = response.json()["data"]
    assert media["kind"] == "audio"
    assert media["playable"] is False


def test_unsupported_format_is_refused_with_a_hint(client, db_session):
    class_id = _class_id(db_session)
    student = _student(db_session, "留档格式甲", "M9004")
    contact = _contact(client, class_id, student.name)

    response = _upload(client, class_id, contact["id"], "压缩包.zip", b"PK\x03\x04")
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "MEDIA_BAD_TYPE"
    assert "照片用 jpg/png" in response.json()["error"]["message"]


def test_oversized_file_is_refused_before_writing(client, db_session, monkeypatch):
    """超限在**读的时候**就拦下，不先落盘再检查（否则盘上会留一堆没登记的垃圾）。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "留档超限甲", "M9005")
    contact = _contact(client, class_id, student.name)
    monkeypatch.setattr(media_store, "MAX_IMAGE_BYTES", 1024)

    response = _upload(client, class_id, contact["id"], "大图.png", _png(400, 400), "image/png")
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "MEDIA_TOO_LARGE"
    assert client.get(f"/api/v1/media?ownerTable=contacts&ownerId={contact['id']}").json()["data"] == []


# ---------- 归属校验 ----------


def test_attachment_needs_a_real_owner(client, db_session):
    """挂附件的记录必须真的存在 —— 否则会造出谁也看不到的孤儿附件。"""
    class_id = _class_id(db_session)
    response = _upload(client, class_id, 999999, "照片.png", _png(60, 60), "image/png")
    assert response.status_code == 404, response.text
    assert "不存在" in response.json()["error"]["message"]


def test_unknown_owner_table_is_refused(client, db_session):
    class_id = _class_id(db_session)
    response = client.post(
        "/api/v1/media",
        files={"file": ("照片.png", _png(60, 60), "image/png")},
        data={"ownerTable": "不存在表", "ownerId": "1", "classId": str(class_id)},
    )
    assert response.status_code == 400
    assert "还不支持挂附件" in response.json()["error"]["message"]


# ---------- 列表与去重 ----------


def test_same_file_is_stored_once(client, db_session):
    """同一份文件传两次不重复占盘（手机里同一张照片存两遍很常见）。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "留档去重甲", "M9006")
    contact = _contact(client, class_id, student.name)
    data = _png(400, 300)

    first = _upload(client, class_id, contact["id"], "现场.png", data, "image/png").json()["data"]
    second = _upload(client, class_id, contact["id"], "现场副本.png", data, "image/png").json()["data"]

    assert _rel_path(db_session, first["id"]) == _rel_path(db_session, second["id"])
    # 两条记录都在（老师看到两张照片），但盘上只有一份文件
    files = [item for item in (media_store.MEDIA_DIR).rglob("*") if item.is_file() and "thumbs" not in item.parts]
    assert len(files) == 1
    assert second["size"] == first["size"]  # 大小照实显示，不是 0


def test_list_shows_attachments_and_the_generic_list_counts_them(client, db_session):
    class_id = _class_id(db_session)
    student = _student(db_session, "留档列表甲", "M9007")
    contact = _contact(client, class_id, student.name)
    _upload(client, class_id, contact["id"], "现场.png", _png(120, 90), "image/png")
    _upload(client, class_id, contact["id"], "电话.wav", _wav(1.0), "audio/wav")

    listed = client.get(
        "/api/v1/media", params={"ownerTable": "contacts", "ownerId": contact["id"]}
    ).json()["data"]
    assert [item["kind"] for item in listed] == ["image", "audio"]  # 照片在前

    # 通用列表里带附件数（一次查完，不是每条记录查一次）
    rows = client.get("/api/v1/contacts", params={"classId": class_id}).json()["data"]
    assert rows[0]["attachment_count"] == 2


# ---------- 删除回收与清理 ----------


def test_delete_moves_the_file_to_trash_and_can_be_restored(client, db_session):
    class_id = _class_id(db_session)
    student = _student(db_session, "留档回收甲", "M9008")
    contact = _contact(client, class_id, student.name)
    media = _upload(client, class_id, contact["id"], "录音.m4a", _wav(1.0), "audio/mp4").json()["data"]
    original_rel = _rel_path(db_session, media["id"])

    assert client.delete(f"/api/v1/media/{media['id']}").status_code == 200
    trashed_rel = _rel_path(db_session, media["id"])
    assert trashed_rel.startswith("trash/")
    assert not media_store.absolute_path(original_rel).exists()
    assert media_store.absolute_path(trashed_rel).exists()
    # 删掉之后列表里就没有了
    assert client.get(
        "/api/v1/media", params={"ownerTable": "contacts", "ownerId": contact["id"]}
    ).json()["data"] == []

    assert client.post(f"/api/v1/media/{media['id']}/restore").status_code == 200
    restored_rel = _rel_path(db_session, media["id"])
    assert restored_rel.startswith("media/")
    assert media_store.absolute_path(restored_rel).exists()
    assert client.get(
        "/api/v1/media", params={"ownerTable": "contacts", "ownerId": contact["id"]}
    ).json()["data"][0]["id"] == media["id"]


def test_deleting_one_of_two_records_sharing_a_file_keeps_it(client, db_session):
    """两条记录引用同一个文件（去重过）时，删一条**不能**把文件挪走 —— 另一条还要用。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "留档共享甲", "M9009")
    contact = _contact(client, class_id, student.name)
    data = _png(300, 200)
    first = _upload(client, class_id, contact["id"], "同图.png", data, "image/png").json()["data"]
    second = _upload(client, class_id, contact["id"], "同图2.png", data, "image/png").json()["data"]

    assert client.delete(f"/api/v1/media/{first['id']}").status_code == 200
    assert client.get(second["fileUrl"]).status_code == 200  # 另一个还能打开


def test_purge_only_removes_audio_by_default(client, db_session):
    """按日期清理默认只动录音，不动照片（`04` §3.5 的入口）。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "留档清理甲", "M9010")
    contact = _contact(client, class_id, student.name)
    photo = _upload(client, class_id, contact["id"], "照片.png", _png(100, 100), "image/png").json()["data"]
    audio = _upload(client, class_id, contact["id"], "录音.wav", _wav(1.0), "audio/wav").json()["data"]
    photo_rel = _rel_path(db_session, photo["id"])
    audio_rel = _rel_path(db_session, audio["id"])

    result = client.post(
        "/api/v1/media/purge",
        json={"classId": class_id, "before": "2099-01-01"},
    ).json()["data"]
    assert result["removed"] == 1 and result["kinds"] == ["audio"]

    remaining = client.get(
        "/api/v1/media", params={"ownerTable": "contacts", "ownerId": contact["id"]}
    ).json()["data"]
    assert [item["id"] for item in remaining] == [photo["id"]]
    assert media_store.absolute_path(photo_rel).exists()  # 照片没动

    # 录音的**文件**必须真的从盘上消失 —— 清理的作用就在这里。
    # （这条原来写成 `assert ... if False else True`：恒真，所以「清理没删文件」
    #   那个 bug 从这条用例底下溜过去了。评审抓到的。）
    assert not (media_store.MEDIA_DIR / audio_rel.removeprefix("media/")).exists()


def test_purge_requires_an_explicit_date(client, db_session):
    class_id = _class_id(db_session)
    response = client.post("/api/v1/media/purge", json={"classId": class_id})
    assert response.status_code == 400
    assert "哪一天之前" in response.json()["error"]["message"]


def test_storage_stats_walk_the_directory(client, db_session):
    """占用是**真实遍历目录**算的（旧应用按 5 MB 估算）。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "留档占用甲", "M9011")
    contact = _contact(client, class_id, student.name)
    _upload(client, class_id, contact["id"], "照片.png", _png(500, 400), "image/png")

    stats = client.get("/api/v1/media/storage").json()["data"]
    assert stats["media"] > 0
    assert stats["mediaCount"] >= 1
    assert stats["thumbs"] > 0
    assert stats["dataDir"]


def test_contact_follow_up_list_reads_the_flag(client, db_session):
    """「需要再次联系」的记录进首页跟进清单 —— 口径在服务端，前端不各筛一遍。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "留档跟进甲", "M9012")
    _contact(client, class_id, student.name, needs_follow_up=True, result="未接通")
    _contact(client, class_id, student.name, content="已聊完", date="2026-09-16")

    rows = client.get("/api/v1/contacts/follow-ups", params={"classId": class_id}).json()["data"]
    assert len(rows) == 1
    assert rows[0]["studentName"] == "留档跟进甲"
    assert rows[0]["result"] == "未接通"


# ---------- 评审抓到的边界（这些原来一条用例都没有） ----------


def test_broken_image_is_refused_and_leaves_nothing_on_disk(client, db_session):
    """一个改了扩展名的文本文件：**报错、且盘上不留东西**。

    原先没有兜底：写盘之后生成缩略图才炸 → 客户端拿到 500，
    而盘上留着一份老师永远看不到、也删不掉的孤儿文件（评审实测）。
    """
    class_id = _class_id(db_session)
    student = _student(db_session, "坏图甲", "M9101")
    contact = _contact(client, class_id, student.name)

    response = _upload(client, class_id, contact["id"], "假的.png", b"this is not an image", "image/png")
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "MEDIA_BAD_IMAGE"
    assert _files_on_disk() == []


def _files_on_disk() -> list:
    return [
        item
        for item in media_store.MEDIA_DIR.rglob("*")
        if item.is_file() and "thumbs" not in item.parts
    ]


def test_empty_file_is_refused(client, db_session):
    class_id = _class_id(db_session)
    student = _student(db_session, "空文件甲", "M9102")
    contact = _contact(client, class_id, student.name)
    response = _upload(client, class_id, contact["id"], "空的.png", b"", "image/png")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MEDIA_EMPTY"


def test_dedup_works_across_records(client, db_session):
    """同一份文件挂到**另一条**记录上也不该再存一份（文档 §3.2 说的是「同一份文件复用」）。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "跨记录去重甲", "M9103")
    first_contact = _contact(client, class_id, student.name)
    second_contact = _contact(client, class_id, student.name, date="2026-09-16", channel="微信")
    data = _png(240, 180)

    one = _upload(client, class_id, first_contact["id"], "同图.png", data, "image/png").json()["data"]
    two = _upload(client, class_id, second_contact["id"], "同图.png", data, "image/png").json()["data"]

    assert _rel_path(db_session, one["id"]) == _rel_path(db_session, two["id"])
    assert len(_files_on_disk()) == 1


def test_restore_refuses_when_the_file_is_gone(client, db_session):
    """回收站里已经没有文件了 —— 明确说清，而不是清掉删除标记报「恢复成功」。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "恢复缺失甲", "M9104")
    contact = _contact(client, class_id, student.name)
    media = _upload(client, class_id, contact["id"], "照片.png", _png(80, 80), "image/png").json()["data"]

    assert client.delete(f"/api/v1/media/{media['id']}").status_code == 200
    # 模拟有人手工清了回收站
    for item in (media_store.TRASH_DIR).rglob("*"):
        if item.is_file():
            item.unlink()

    response = client.post(f"/api/v1/media/{media['id']}/restore")
    assert response.status_code == 404, response.text
    assert "回收站里已经没有这个文件" in response.json()["error"]["message"]


def test_purge_by_student_removes_only_that_students_audio(client, db_session):
    """「删除某学生全部音频」（`04` §3.5）—— 按学生筛，不动别人、不动照片。"""
    class_id = _class_id(db_session)
    one = _student(db_session, "清音频甲", "M9105")
    other = _student(db_session, "清音频乙", "M9106")
    contact_one = _contact(client, class_id, one.name)
    contact_other = _contact(client, class_id, other.name)

    # 两段录音**故意用不同时长**：内容一样的话会按去重复用同一份文件，
    # 那清理甲的时候文件本来就该留着（乙还在用），这条用例就测不到东西了
    audio_one = _upload(client, class_id, contact_one["id"], "甲.wav", _wav(1.0), "audio/wav").json()["data"]
    _upload(client, class_id, contact_other["id"], "乙.wav", _wav(2.5), "audio/wav")
    _upload(client, class_id, contact_one["id"], "甲的照片.png", _png(70, 70), "image/png")
    audio_one_rel = _rel_path(db_session, audio_one["id"])

    result = client.post(
        "/api/v1/media/purge",
        json={"classId": class_id, "before": "2099-01-01", "studentId": one.id},
    ).json()["data"]
    assert result["removed"] == 1 and result["studentId"] == one.id

    # 只剩乙的录音（甲的照片不动）
    remaining = client.get("/api/v1/media", params={"classId": class_id}).json()["data"]
    assert sorted(item["kindLabel"] for item in remaining if item["kind"] == "audio") == ["录音"]
    assert any(item["kind"] == "image" for item in remaining)
    assert not (media_store.MEDIA_DIR / audio_one_rel.removeprefix("media/")).exists()


def test_purge_deletes_files_even_when_records_share_them(client, db_session):
    """多条记录共用一份文件时，清理必须**真的把文件删掉**。

    原先靠循环里「还有谁在用」的即时查询判断，而会话是 autoflush=False：
    已经 delete 但没落库的行照样查得到，于是每条都以为「别人还在用」，
    结果记录删空、文件一份没删（评审实测：提示清理 4 条、磁盘没变）。
    """
    class_id = _class_id(db_session)
    student = _student(db_session, "共享清理甲", "M9107")
    contact = _contact(client, class_id, student.name)
    data = _png(150, 120)
    _upload(client, class_id, contact["id"], "同图.png", data, "image/png")
    _upload(client, class_id, contact["id"], "同图2.png", data, "image/png")
    assert len(_files_on_disk()) == 1

    result = client.post(
        "/api/v1/media/purge",
        json={"classId": class_id, "before": "2099-01-01", "kinds": ["image"]},
    ).json()["data"]
    assert result["removed"] == 2
    assert _files_on_disk() == []
    assert media_store.folder_size(media_store.MEDIA_DIR / "thumbs") == 0  # 缩略图也不再留着


def test_thumbnails_are_cleaned_up_with_the_original(client, db_session):
    """缩略图跟着原件删 —— 不然 thumbs 里的占用只增不减，老师永远清不掉。"""
    class_id = _class_id(db_session)
    student = _student(db_session, "缩略图清理甲", "M9108")
    contact = _contact(client, class_id, student.name)
    media = _upload(client, class_id, contact["id"], "照片.png", _png(500, 400), "image/png").json()["data"]
    assert media_store.folder_size(media_store.MEDIA_DIR / "thumbs") > 0

    client.post(
        "/api/v1/media/purge",
        json={"classId": class_id, "before": "2099-01-01", "kinds": ["image"]},
    )
    assert media_store.folder_size(media_store.MEDIA_DIR / "thumbs") == 0


def test_bad_owner_id_is_a_400_not_a_500(client, db_session):
    class_id = _class_id(db_session)
    response = client.get("/api/v1/media", params={"ownerTable": "contacts", "ownerId": "abc"})
    assert response.status_code == 400
    assert "要是数字" in response.json()["error"]["message"]


def test_path_traversal_is_blocked():
    """相对路径拼进 `..` 不能读到数据目录外面。

    原先用字符串前缀比较，`../<数据目录名>2/x` 这种能溜过去（前缀相同但是兄弟目录）。
    """
    import pytest

    from app.storage.media_store import MediaError

    for bad in ("../outside.txt", "../../etc/passwd", "", "media/../../outside.txt"):
        with pytest.raises(MediaError):
            media_store.absolute_path(bad)
    # 正常路径仍然可用
    assert media_store.absolute_path("media/2026/09/x.jpg").name == "x.jpg"
