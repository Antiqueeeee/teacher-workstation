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


def test_daemon_timeout_says_still_starting_when_the_child_is_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """**第一次启动很慢**（建库 + 跑全部迁移），别因此对老师报「启动失败」。

    老师第一次装必然碰上这一条：进程还在、只是还没监听端口 ——
    这时候说「失败」会让他以为要重装。
    """
    import json

    monkeypatch.setenv("TWS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(launcher, "DAEMON_WAIT_SECONDS", 0.3)
    monkeypatch.setattr(launcher, "health", lambda _port, timeout=1.0: None)

    def fake_spawn(port: int) -> None:
        # 模拟「子进程活着、状态文件已写、但还没开始监听」
        (tmp_path / launcher.PID_FILE_NAME).write_text(
            json.dumps({"pid": 123456, "port": port}), encoding="utf-8"
        )

    monkeypatch.setattr(launcher, "spawn_daemon", fake_spawn)
    assert launcher.cmd_start(daemon=True, want_browser=False, base_port=8790) == 0
    output = capsys.readouterr().out
    assert "已经在启动了" in output and "失败" not in output


def test_state_file_of_another_instance_is_not_deleted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """不能删掉**别人**写的状态文件。

    老师快速连点两下时两个启动器会同时起来（uvicorn 先跑迁移、后绑定端口，中间有空窗）。
    输的那个如果无条件删状态文件，赢家就「人间蒸发」了 ——
    表现为「状态说没在运行、停止也停不掉，但服务还占着端口」（评审实测）。
    """
    import json

    monkeypatch.setenv("TWS_DATA_DIR", str(tmp_path))
    state_file = tmp_path / launcher.PID_FILE_NAME
    state_file.write_text(json.dumps({"pid": 999999, "port": 8723}), encoding="utf-8")

    launcher.clear_state()  # 默认只删自己写的
    assert state_file.exists(), "把别的实例的状态文件删了"

    launcher.clear_state(only_if_mine=False)  # 明确要求清残留时才删
    assert not state_file.exists()


def test_base_port_follows_tws_port(monkeypatch: pytest.MonkeyPatch):
    """起始端口要跟着 `TWS_PORT` 走：应用也用这个变量拼地址与二维码，两边必须同一个起点。"""
    monkeypatch.delenv("TWS_PORT", raising=False)
    assert launcher.base_port() == launcher.DEFAULT_PORT

    monkeypatch.setenv("TWS_PORT", "9100")
    assert launcher.base_port() == 9100

    for bad in ("abc", "", "70000", "-1"):
        monkeypatch.setenv("TWS_PORT", bad)
        assert launcher.base_port() == launcher.DEFAULT_PORT, f"{bad!r} 应该退回默认端口"


def test_autostart_command_differs_per_platform(monkeypatch: pytest.MonkeyPatch):
    """自启命令两平台不一样，写错了老师那边会反复重启或弹浏览器。

    - Windows：没有守护进程，要 `--daemon`（自己脱离终端）；
    - macOS：launchd 看住**真正的服务进程**，不能再 `--daemon`（那会「派生后立刻退出」，
      配合 KeepAlive 变成每十几秒拉一个新进程）；
    - 两边都不能弹浏览器（老师会以为中了病毒）。
    """
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    windows = launcher.autostart_command()
    assert "--daemon" in windows and "--no-browser" in windows

    monkeypatch.setattr(launcher.sys, "platform", "darwin")
    macos = launcher.autostart_command()
    assert "--daemon" not in macos, "launchd 守护时不能再用 --daemon"
    assert "--no-browser" in macos


def test_launch_agent_restarts_only_after_a_crash(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(launcher.sys, "platform", "darwin")
    monkeypatch.setenv("TWS_DATA_DIR", str(tmp_path))
    plist = launcher.launch_agent_plist()
    assert "SuccessfulExit" in plist, "老师点「停止」是正常退出，不该被 launchd 立刻拉回来"
    assert "RunAtLoad" in plist
    assert "logs" in plist  # 日志落在数据目录里
    assert "_python.bat" not in plist


def test_port_free_reports_a_listening_port_as_taken(monkeypatch: pytest.MonkeyPatch):
    """有人监听时不算空闲。

    注意：**不能靠设 SO_REUSEADDR 来探测** —— Windows 上设了它，两个进程能绑同一个端口，
    实测会出现「把别家程序顶掉」或「绑上了却收不到连接」（老师看窗口说正常、手机打不开）。
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("0.0.0.0", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        assert launcher.port_free(port) is False
    # 关掉之后应该变成空闲
    assert launcher.port_free(port) is True


def test_running_from_a_zip_warns_about_the_temp_directory(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """在压缩包里直接双击时要说清楚（数据会落在临时目录、重启可能被清掉）。"""
    monkeypatch.setenv("TEMP", r"C:\Users\x\AppData\Local\Temp")
    monkeypatch.setattr(launcher, "APP_DIR", Path(r"C:\Users\x\AppData\Local\Temp\Temp1_abc.zip\pkg"))
    launcher.warn_if_running_from_temp()
    assert "解压" in capsys.readouterr().out

    monkeypatch.setattr(launcher, "APP_DIR", Path(r"D:\班主任工作台"))
    launcher.warn_if_running_from_temp()
    assert capsys.readouterr().out == ""


def test_status_json_is_machine_readable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    """外部工具（一键启动器 / 进程管理器 / AI 助手）只用 `--json` 与退出码。

    约定：没在跑时也是 `ok: true`（**接口是好的，只是没在跑**），退出码 1；
    在跑时给全 pid / port / 两个地址 / 数据目录，退出码 0。
    """
    import json

    monkeypatch.setenv("TWS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(launcher, "running", lambda: None)
    assert launcher.cmd_status(as_json=True) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": True, "running": False}

    monkeypatch.setattr(
        launcher,
        "running",
        lambda: {"pid": 4321, "port": 8723, "startedAt": "2026-09-19 10:00:00", "dataDir": str(tmp_path)},
    )
    assert launcher.cmd_status(as_json=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["running"] is True and payload["pid"] == 4321 and payload["port"] == 8723
    assert payload["local"].startswith("http://127.0.0.1:8723") and payload["lan"].startswith("http://")
    assert payload["dataDir"] == str(tmp_path)


def test_daemon_start_is_idempotent_for_external_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """`--daemon` 幂等：已经在跑时返回 0，绝不起第二个实例（外部工具会反复调用它）。"""
    monkeypatch.setenv("TWS_DATA_DIR", str(tmp_path))
    spawned: list[int] = []
    monkeypatch.setattr(launcher, "spawn_daemon", lambda port: spawned.append(port))
    monkeypatch.setattr(
        launcher, "running", lambda: {"pid": 1, "port": 8723, "dataDir": str(tmp_path)}
    )
    assert launcher.cmd_start(daemon=True, want_browser=False, base_port=8723) == 0
    assert spawned == [], "已经在跑时不该再派生新实例"
