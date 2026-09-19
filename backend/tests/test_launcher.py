"""启动器的两条口径（`launcher.py`）。

这两条错了都不会有报错，只会让老师「扫了打不开、连不上」，而他在自己电脑上
根本查不出原因 —— 所以它们值得有测试守着：

1. **端口要传给应用**：8723 被占用时启动器会改用 8724，而界面/二维码里的地址是按
   `app.config.PORT` 拼的。不把实际端口告诉应用，二维码就会指向没人监听的端口
   （实测踩到：包跑在 8724，`/system/access` 却回 8723）；
2. **地址口径只有一处**：启动窗口与界面必须拿到同一个地址（都来自
   `services/access_info.py`）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import launcher  # noqa: E402


def test_serve_tells_the_app_which_port_it_actually_uses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """启动器必须把实际端口写进 TWS_PORT（应用靠它拼地址与二维码）。"""
    monkeypatch.setenv("TWS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("TWS_PORT", raising=False)

    captured: dict = {}
    import uvicorn

    # 不去真的占端口：把 uvicorn.run 换掉，只看它拿到的参数
    monkeypatch.setattr(uvicorn, "run", lambda _app, **kwargs: captured.update(kwargs))

    assert launcher.serve(8725, daemon=False, detached=False) == 0
    assert captured["port"] == 8725
    assert os.environ["TWS_PORT"] == "8725", "没告诉应用实际端口 —— 二维码会指到默认端口上"
    assert captured["host"] == os.environ.get("TWS_HOST", "0.0.0.0"), "默认要监听 0.0.0.0，手机才连得上"


def test_serve_writes_and_clears_its_state_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """状态文件（data/server.json）是「关掉窗口没清干净」与「真在跑」的唯一判据。"""
    monkeypatch.setenv("TWS_DATA_DIR", str(tmp_path))
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda _app, **kwargs: None)
    launcher.serve(8726, daemon=False, detached=False)

    state_file = tmp_path / launcher.PID_FILE_NAME
    # 服务退出后不该留下状态文件（否则下次启动要先当成「上次没退干净」清一遍）
    assert not state_file.exists()


def test_addresses_come_from_the_service_layer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """启动窗口里的地址与界面里的地址**必须同一份实现**（services/access_info.py）。"""
    local, lan = launcher.addresses(8727)
    from app.services.access_info import access_info

    expected = access_info(8727)
    assert (local, lan) == (expected["local"], expected["lan"])
    assert lan != local


def test_terminal_qr_is_optional(monkeypatch: pytest.MonkeyPatch):
    """终端画不出二维码（老编码/异常）时返回空列表，而不是让启动失败。"""
    monkeypatch.setattr(
        "app.services.access_info.qr_terminal",
        lambda _url: (_ for _ in ()).throw(RuntimeError("terminal cannot render")),
    )

    assert launcher.qr_lines("http://192.168.5.2:8723/") == []
