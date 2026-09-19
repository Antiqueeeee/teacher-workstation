"""访问地址与二维码。

要害：**「手机该访问哪个地址」只有一处实现**（`services/access_info.py`），
启动窗口、设置页、二维码都从它取 —— 两处各算一遍迟早出现「窗口写 127.0.0.1、
界面写内网地址」这种自相矛盾，而老师拿着手机连不上根本看不出是哪儿错了。
"""

from __future__ import annotations

import pytest

from app.services.access_info import access_info, lan_ip, qr_svg, qr_terminal


def test_access_info_gives_both_addresses():
    info = access_info(8723)
    assert info["local"] == "http://127.0.0.1:8723/"
    assert info["lan"].startswith("http://") and info["lan"].endswith(":8723/")
    # 局域网地址里是**本机 IP**，不是 127.0.0.1（否则手机永远连不上）
    assert lan_ip() in info["lan"]
    assert info["lan"] != info["local"]


def test_lan_ip_falls_back_when_there_is_no_network(monkeypatch: pytest.MonkeyPatch):
    """断网/没有网卡时退回 127.0.0.1 —— 至少本机能用，而不是抛异常。"""

    class BrokenSocket:
        def __init__(self, *_args, **_kwargs):
            raise OSError("no route")

    monkeypatch.setattr("app.services.access_info.socket.socket", BrokenSocket)
    assert lan_ip() == "127.0.0.1"


def test_qr_svg_encodes_the_url_it_is_given():
    """二维码内容必须**就是传进去的地址**（不能是别的、也不能是界面自己拼的）。"""
    first = qr_svg("http://192.168.5.2:8723/")
    second = qr_svg("http://192.168.5.2:8724/")
    assert first.startswith("<svg") and "qrline" in first
    assert first != second, "不同地址必须画出不同的二维码"
    # 同一个地址两次结果一致（无随机性）
    assert first == qr_svg("http://192.168.5.2:8723/")


def test_terminal_qr_is_rendered_for_the_startup_window():
    rendered = qr_terminal("http://192.168.5.2:8723/")
    assert rendered.strip(), "启动窗口要能画出二维码（否则老师只能手输地址）"
    assert any(char in rendered for char in "█▀▄"), "应该用块字符画出来"


def test_access_endpoint_returns_the_lan_url_and_a_qr_for_it(client):
    """接口给的二维码，编码的必须是接口自己给的那个 `lan` 地址。

    这条盯的是最容易犯的错：把 `local`（127.0.0.1）编进二维码 ——
    老师扫了之后手机上打开的是「手机自己的 127.0.0.1」，等于打不开。
    """
    response = client.get("/api/v1/system/access")
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    assert data["local"].startswith("http://127.0.0.1:")
    assert data["lan"].startswith("http://") and "127.0.0.1" not in data["lan"]
    assert data["qrSvg"].startswith("<svg")
    # 与「用 lan 生成的那张」逐字节一致 → 说明编进去的就是 lan
    assert data["qrSvg"] == qr_svg(data["lan"])
    assert data["qrSvg"] != qr_svg(data["local"])
