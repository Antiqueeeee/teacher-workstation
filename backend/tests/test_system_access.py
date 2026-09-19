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


def test_all_lan_ips_lists_every_adapter_with_the_probed_one_first(monkeypatch: pytest.MonkeyPatch):
    """装了 VPN / 虚拟机的电脑会有多个地址，探到的那个排第一，其余作为候选。

    这是评审点到的设计缺口：内核选出的「默认出口」很可能是虚拟网卡，
    那个地址手机根本连不上，而老师看不出哪儿错了 —— 所以要给得出候选。
    """

    def fake_getaddrinfo(*_args, **_kwargs):
        return [
            (2, 1, 6, "", ("10.0.0.9", 0)),      # 可能是 VPN 的地址
            (2, 1, 6, "", ("192.168.5.2", 0)),   # 真实局域网
            (2, 1, 6, "", ("127.0.0.1", 0)),     # 回环要排除
            (2, 1, 6, "", ("169.254.10.1", 0)),  # 链路本地要排除
            (2, 1, 6, "", ("192.168.5.2", 0)),   # 重复要去掉
        ]

    monkeypatch.setattr("app.services.access_info.lan_ip", lambda: "192.168.5.2")
    monkeypatch.setattr("app.services.access_info.socket.getaddrinfo", fake_getaddrinfo)

    from app.services.access_info import access_info, all_lan_ips

    assert all_lan_ips() == ["192.168.5.2", "10.0.0.9"], "探到的排第一、回环与链路本地要排除、去重"
    info = access_info(8723)
    assert info["lan"] == "http://192.168.5.2:8723/"
    assert info["alternatives"] == [{"ip": "10.0.0.9", "url": "http://10.0.0.9:8723/"}]


def test_access_endpoint_accepts_a_local_address_and_rejects_foreign_ones(
    client, monkeypatch: pytest.MonkeyPatch
):
    """`?address=` 只认本机地址 —— 否则这个接口就成了任意二维码生成器。"""
    monkeypatch.setattr("app.services.access_info.lan_ip", lambda: "192.168.5.2")

    chosen = client.get("/api/v1/system/access", params={"address": "192.168.5.2"})
    assert chosen.status_code == 200, chosen.text
    data = chosen.json()["data"]
    assert data["lan"] == "http://192.168.5.2:8723/"
    assert data["qrSvg"].startswith("<svg")

    foreign = client.get("/api/v1/system/access", params={"address": "8.8.8.8"})
    assert foreign.status_code == 400, foreign.text
    assert "不是这台电脑的地址" in foreign.json()["error"]["message"]
