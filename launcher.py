"""一键启动器：老师和双击脚本都走这一个入口。

为什么要有它（而不是让脚本直接敲 uvicorn）：

1. **老师机器的现状**：那台电脑只装浏览器，不装 Python、不装 Docker、不联网。
   所以交付包里自带一套 Python 运行时（`runtime/`），脚本只负责把它叫起来；
2. **双击就该能用**：自己找空闲端口、自己建数据目录、自己在浏览器里打开界面、
   自己把「手机该访问哪个地址」打出来 —— 老师不需要知道 uvicorn 是什么；
3. **重复双击不能报错**：老师最常见的动作是「再点一次」。发现已经在跑时，
   这里直接打开浏览器然后退出（而不是起第二个实例、或者报「端口被占用」）；
4. **后台运行**（`--daemon`）：真的脱离当前终端（Windows 无窗口、macOS 脱离会话），
   日志写进数据目录；停止、看状态都是同一套命令（`--stop` / `--status`），逻辑只有这一份。

命令行（`启动.bat` / `启动.command` 这些脚本只是它的薄壳）：

    python launcher.py                 # 前台启动（关掉窗口就停）
    python launcher.py --daemon        # 后台启动（无窗口，立即返回）
    python launcher.py --stop          # 停止正在跑的那个
    python launcher.py --status        # 看它跑没跑、地址是什么
    python launcher.py --no-browser    # 不自动开浏览器（脚本/测试用）

数据目录：默认**包根目录下的 `data/`**（数据库、照片录音、日志都在里面，
整包拷走就是备份）；可用环境变量 `TWS_DATA_DIR` 覆盖。开发机上直接跑 uvicorn
时仍用 `backend/data/`，两者互不影响。
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR / "backend"

DEFAULT_PORT = 8723
PORT_TRIES = 20  # 端口被占就往后找，最多试这么多个
PID_FILE_NAME = "server.json"
LOCK_FILE_NAME = "server.lock"
LOCK_STALE_SECONDS = 90  # 锁超过这么久、又没有服务在监听，就当成上次崩溃留下的
DAEMON_WAIT_SECONDS = 15.0  # 后台启动后等它起来（首次要建库跑迁移，给足时间）
STARTUP_WAIT_SECONDS = 60.0  # 只用于「等服务真的开始监听」，超了就说清楚起不来


def base_port() -> int:
    """起始端口：`TWS_PORT` 优先（**应用也用这个变量拼地址与二维码**，两边必须同一个起点）。

    只认启动器的 8723、而应用认 `TWS_PORT` 的话，老师设了 `TWS_PORT=9000` 时
    界面与二维码会写 9000、服务却在 8723/8724 上跑 —— 评审实测过这种不一致。
    """
    raw = os.environ.get("TWS_PORT")
    try:
        port = int(raw) if raw not in (None, "") else DEFAULT_PORT
    except ValueError:
        return DEFAULT_PORT
    return port if 1 <= port <= 65535 else DEFAULT_PORT


# --------------------------------------------------------------------- 小工具


def data_dir() -> Path:
    """数据目录：环境变量优先，否则用包根目录下的 `data/`。"""
    raw = os.environ.get("TWS_DATA_DIR")
    return Path(raw).expanduser().resolve() if raw else (APP_DIR / "data")


def pid_file() -> Path:
    return data_dir() / PID_FILE_NAME


def access_urls(port: int) -> tuple[str, str]:
    """本机 / 手机两个地址 —— **口径在服务层**（`app/services/access_info.py`），
    这里只负责在还没起服务时也能算（先补上 backend 路径再导入）。"""
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    from app.services.access_info import access_info  # noqa: PLC0415

    info = access_info(port)
    return info["local"], info["lan"]


def qr_lines(url: str) -> list[str]:
    """终端二维码（启动窗口里扫一下就省得手输地址）。

    取不到就返回空列表 —— 老终端/特殊编码下画不出来是常事，
    不该因此让启动失败（界面里的「手机访问」有同一张二维码）。
    """
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    try:
        from app.services.access_info import qr_terminal  # noqa: PLC0415

        rendered = qr_terminal(url)
        # 先在内存里编码一遍，确认这个终端画得出来（cp936 之类的编码会在这里露馅）
        rendered.encode(sys.stdout.encoding or "utf-8")
        return rendered.splitlines()
    except Exception:  # noqa: BLE001 - 画不出二维码是小事，不能挡住启动
        return []


def health(port: int, timeout: float = 1.0) -> dict | None:
    """这个端口上跑的是我们的服务吗？是就返回 health 数据。"""
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/v1/health", timeout=timeout
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload.get("data") if payload.get("ok") else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def port_free(port: int) -> bool:
    """这个端口能不能拿来用。

    **不用 SO_REUSEADDR**：Windows 上设了它，两个进程能绑同一个端口 ——
    实测（评审复现）会出现「我们绑上了、把原来在监听的那个程序顶掉」、
    或者两个 pid 同时监听同一端口导致连接被拒。老师那边表现就是
    「窗口说一切正常，手机就是打不开」。

    两步判断：① 能不能绑上（不设 REUSEADDR）；② 有没有人已经在监听
    （绑得上但连得上，说明对方用了 REUSEADDR，那也不能用）。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("0.0.0.0", port))
        except OSError:
            return False

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.3)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            return False  # 有人在监听：连上了
    return True


def read_state() -> dict | None:
    path = pid_file()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_state(port: int) -> None:
    state = {
        "pid": os.getpid(),
        "port": port,
        "dataDir": str(data_dir()),
        "startedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    pid_file().parent.mkdir(parents=True, exist_ok=True)
    pid_file().write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_state(*, only_if_mine: bool = True) -> None:
    """删掉状态文件。

    **默认只删自己写的**：老师快速连点两下时，两个启动器会同时起来
    （uvicorn 是「先跑迁移、后绑定端口」，这中间有约 1 秒的空窗），
    输的那个如果无条件删状态文件，赢家就被抹掉了 —— 表现为
    「`状态` 说没在运行、`停止` 也停不掉，但服务还占着端口」（评审实测）。
    """
    if only_if_mine:
        state = read_state()
        if state and int(state.get("pid") or 0) != os.getpid():
            return
    pid_file().unlink(missing_ok=True)


def acquire_lock(port: int) -> bool:
    """抢「正在启动 / 正在运行」的锁（`O_EXCL` 原子创建，Windows/macOS 都成立）。

    为什么需要它：uvicorn 是**先跑 lifespan（数据库迁移）、后绑定端口**，中间有约 1 秒
    空窗期。老师快速连点两下「启动」时，两个进程都会认为「没在跑、端口是空的」，
    于是起两个实例写同一个数据库；输的那个还会把赢家的状态文件盖掉又删掉 ——
    表现为「状态说没在运行、停止也停不掉，但服务还占着端口」（评审实测）。

    「还活着吗」不查进程表（跨平台麻烦），看两件事：锁新不新、以及有没有服务在监听。
    """
    path = data_dir() / LOCK_FILE_NAME
    data_dir().mkdir(parents=True, exist_ok=True)
    for attempt in (1, 2):
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if attempt == 2:
                return False
            age = time.time() - path.stat().st_mtime if path.exists() else LOCK_STALE_SECONDS + 1
            if age < LOCK_STALE_SECONDS or health(port) is not None:
                return False  # 有人在启动或已经在跑
            path.unlink(missing_ok=True)  # 上次崩溃留下的陈旧锁
            continue
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "port": port}, stream)
        return True
    return False


def release_lock() -> None:
    """释放锁（只放自己抢的那把）。"""
    path = data_dir() / LOCK_FILE_NAME
    if not path.exists():
        return
    try:
        holder = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        holder = {}
    if int(holder.get("pid") or 0) in (0, os.getpid()):
        path.unlink(missing_ok=True)


def running() -> dict | None:
    """正在跑的那个实例（进程活着**且**端口上确实是我们的服务），否则 None。

    两个条件都要：只看 pid 文件会把「上次关窗口没清干净」当成在跑，
    只看端口又会把别的程序（恰好占了 8723）当成自己。
    """
    state = read_state()
    if not state:
        return None
    port = int(state.get("port") or DEFAULT_PORT)
    info = health(port)
    if info is None:
        return None
    return {**state, "health": info}


AUTOSTART_NAME = "班主任工作台"
LAUNCH_AGENT_LABEL = "com.teacher-workstation.server"


def python_for_autostart() -> str:
    """开机自启要用的解释器：Windows 用 pythonw（**没有黑窗口**），其余用 python3。"""
    if sys.platform.startswith("win"):
        candidate = Path(sys.executable).with_name("pythonw.exe")
        return str(candidate if candidate.exists() else sys.executable)
    return sys.executable


def autostart_command() -> list[str]:
    """自启时要跑的命令（**两个平台不一样**）。

    - Windows：注册表只能「登录时跑一条命令」，没有守护进程 —— 所以用
      `pythonw.exe`（无窗口）+ `--daemon`（自己脱离终端）。
    - macOS：交给 launchd 守护，**它要看住真正的服务进程**，所以直接跑前台版本。
      如果这里也传 `--daemon`，进程会「派生一个子进程后立刻退出 0」，
      而 `KeepAlive` 对正常退出也会重启 → 变成每十几秒反复拉一个新进程（评审指出）。
    - 两边都带 `--no-browser`：开机自启不该弹浏览器窗口（老师会以为中了病毒）。
    """
    script = str(Path(__file__).resolve())
    if sys.platform == "darwin":
        return [python_for_autostart(), script, "--no-browser"]
    return [python_for_autostart(), script, "--daemon", "--no-browser"]


def launch_agent_plist() -> str:
    """macOS 的 LaunchAgent：登录即起、崩了才重启、没有窗口。"""
    command = autostart_command()
    args = "\n".join(f"        <string>{part}</string>" for part in command)
    log = data_dir() / "logs"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{LAUNCH_AGENT_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{args}
    </array>
    <key>WorkingDirectory</key><string>{APP_DIR}</string>
    <key>RunAtLoad</key><true/>
    <!-- 崩了才重启：老师点「停止」是正常退出，不该被 launchd 立刻拉回来 -->
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key><false/>
    </dict>
    <key>StandardOutPath</key><string>{log / "launchd.out.log"}</string>
    <key>StandardErrorPath</key><string>{log / "launchd.err.log"}</string>
</dict>
</plist>
"""


def install_autostart() -> int:
    """设置开机自启（不需要管理员权限，只改当前用户的东西）。"""
    command = " ".join(f'"{part}"' if " " in part else part for part in autostart_command())
    if sys.platform.startswith("win"):
        import winreg  # noqa: PLC0415 - 只有 Windows 才有

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ, command)
        print("已设置开机自启（任务管理器的「启动」里能看到「班主任工作台」）。")
        print("登录 Windows 后它会自动在**后台**跑起来，没有窗口。")
        return 0
    if sys.platform == "darwin":
        target = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
        target.parent.mkdir(parents=True, exist_ok=True)
        # launchd 会在**启动这个任务之前**就去打开 StandardOutPath/ErrorPath；
        # 目录不存在时登录自启会静默失败（老师那边表现就是「说设好了，其实没起来」）
        (data_dir() / "logs").mkdir(parents=True, exist_ok=True)
        target.write_text(launch_agent_plist(), encoding="utf-8")
        # 新版 macOS 建议用 bootstrap/bootout（load/unload 已过时但仍可用）——
        # 两条路都试，成一条就行；都不成才提示老师
        loaded = os.system(f'launchctl unload "{target}" >/dev/null 2>&1')  # 旧的先撤掉
        enabled = os.system(f'launchctl bootstrap gui/{os.getuid()} "{target}" >/dev/null 2>&1')
        if enabled != 0:
            enabled = os.system(f'launchctl load "{target}" >/dev/null 2>&1')
        if enabled != 0:
            print("已经把自启配置写好了，但让 launchd 立刻加载它没成功 —— 重新登录一次 macOS 就会生效。")
        else:
            print(f"已设置开机自启（{target}）。")
        print("登录 macOS 后它会自动在后台跑起来，没有窗口。")
        print(f"（日志在 {data_dir() / 'logs'}；要取消就再点一次「取消开机自启」）")
        return 0
    print("这个系统上没做开机自启（只支持 Windows 与 macOS）。")
    return 1


def remove_autostart() -> int:
    """取消开机自启（关掉的只是自启，不影响当前正在跑的实例）。"""
    if sys.platform.startswith("win"):
        import winreg  # noqa: PLC0415

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, AUTOSTART_NAME)
        except FileNotFoundError:
            print("本来就没设置开机自启。")
            return 0
        print("已取消开机自启。")
        return 0
    if sys.platform == "darwin":
        target = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
        if not target.exists():
            print("本来就没设置开机自启。")
            return 0
        # 与安装对称：bootout 优先，退回 unload（新版 macOS 建议前者）
        if os.system(f'launchctl bootout gui/{os.getuid()} "{target}" >/dev/null 2>&1') != 0:
            os.system(f'launchctl unload "{target}" >/dev/null 2>&1')
        target.unlink(missing_ok=True)
        print("已取消开机自启。")
        return 0
    print("这个系统上没做开机自启（只支持 Windows 与 macOS）。")
    return 1


def open_browser(url: str) -> None:
    import webbrowser

    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - 打不开浏览器不该让服务起不来
        print(f"（没能自动打开浏览器，请手动访问 {url}）")


def addresses(port: int) -> tuple[str, str]:
    return access_urls(port)


def alternative_addresses(port: int) -> list[str]:
    """其它网卡上可能的地址（装了 VPN / 虚拟机时会有多个，手机打不开就换一个试）。"""
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    try:
        from app.services.access_info import access_info  # noqa: PLC0415

        return [item["url"] for item in access_info(port).get("alternatives") or []]
    except Exception:  # noqa: BLE001 - 列不出候选不该挡住启动
        return []


def warn_if_running_from_temp() -> None:
    """在**压缩包临时目录**里直接双击的提醒。

    Windows 双击 zip 里的文件会把它解到 `%TEMP%\Temp1_xxx.zip\`，
    数据就落在那个临时目录里 —— 重启后可能被清理，老师的记录看起来「丢了」。
    这个场景我没法在 GUI 里复现，但路径特征很好认，认出来就明确提醒。
    """
    temp = os.environ.get("TEMP") or os.environ.get("TMP") or ""
    app = str(APP_DIR).lower()
    looks_temp = (temp and app.startswith(temp.lower().rstrip("\/"))) or f"{os.sep}temp" in app
    looks_unzipped = ".zip" in app or "temp1_" in app or "temp" in Path(app).name.lower()
    if looks_temp and looks_unzipped:
        print()
        print("!" * 58)
        print("  注意：你像是**直接在压缩包里双击**运行的。")
        print("  这样数据会存在系统临时目录里，重启电脑后可能被清掉。")
        print("  请先把压缩包**解压到一个固定文件夹**（比如桌面），再从那里双击「启动」。")
        print("!" * 58)


def banner(port: int, version: str = "", daemon: bool = False) -> None:
    local, lan = addresses(port)
    print()
    print("=" * 58)
    print("  班主任工作台已经在运行")
    print("=" * 58)
    print(f"  这台电脑上打开：  {local}")
    print(f"  手机/平板打开：    {lan}   ← 要和这台电脑连同一个 WiFi")
    lines = qr_lines(lan)
    if lines:
        print()
        print("  用手机相机/微信扫这张（等于打开上面那个地址）：")
        for line in lines:
            print(f"    {line}")
    others = alternative_addresses(port)
    if others:
        print(f"  手机连不上？也可以试：{'、'.join(others)}")
        print("                    （装了 VPN 或虚拟机时会有多个网卡地址）")
    print(f"  数据目录：        {data_dir()}")
    print(f"  日志：            {data_dir() / 'logs' / 'app.log'}")
    if version:
        print(f"  版本：            v{version}")
    print("-" * 58)
    if daemon:
        print("  这是**后台运行**，关掉这个窗口不影响使用。")
        print("  要停止：双击「停止」（或 python launcher.py --stop）")
    else:
        print("  关掉这个窗口 = 停止服务。想让它一直在后台跑，用「后台启动」。")
    if sys.platform.startswith("win"):
        print("  第一次运行时 Windows 可能问「是否允许访问网络」 —— 请勾选")
        print("  **专用网络** 并允许，否则手机会连不上。")
    print("=" * 58)
    print()


# --------------------------------------------------------------------- 命令


def cmd_status() -> int:
    state = running()
    if state is None:
        print("没有在运行。")
        return 1
    local, lan = addresses(int(state["port"]))
    print(f"正在运行：端口 {state['port']}（{state.get('startedAt', '')} 启动）")
    print(f"  这台电脑：{local}")
    print(f"  手机/平板：{lan}")
    print(f"  数据目录：{state.get('dataDir')}")
    return 0


def cmd_stop() -> int:
    state = running()
    if state is None:
        print("没有在运行（如果那个黑窗口还开着，直接关掉它就行）。")
        clear_state()
        return 0
    pid = int(state["pid"])
    print(f"正在停止（进程 {pid}，端口 {state['port']}）…")
    try:
        if sys.platform.startswith("win"):
            # /T 连子进程一起结束，避免留下孤儿进程占着端口
            os.system(f"taskkill /PID {pid} /T /F >NUL 2>&1")
        else:
            os.kill(pid, 15)
    except (ProcessLookupError, PermissionError, OSError) as exc:
        print(f"（没能结束进程：{exc}）")
    for _ in range(20):  # 等它真的退出，别让老师紧接着又启一个时撞端口
        if health(int(state["port"])) is None:
            break
        time.sleep(0.25)
    clear_state()
    print("已停止。")
    return 0


def redirect_output() -> None:
    """后台模式：把输出写进数据目录（无窗口时 stdout 是空的，出问题没处看）。"""
    log_dir = data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stream = open(log_dir / "server.out.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    sys.stdout = stream
    sys.stderr = stream


def spawn_daemon(port: int) -> None:
    """把自己再起一份（无窗口、脱离当前终端），然后立刻返回。"""
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--detached",
        "--port",
        str(port),
        "--no-browser",
    ]
    kwargs: dict = {"cwd": str(APP_DIR), "close_fds": True, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform.startswith("win"):
        # 脱离控制台：没有黑窗口，也不会被关掉的终端带走
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        # macOS/Linux：脱离会话（关掉终端不影响它）
        kwargs["start_new_session"] = True
    subprocess.Popen(command, **kwargs)


def announce_when_ready(port: int, version: str, daemon: bool, want_browser: bool) -> threading.Thread:
    """等**真的在监听**了再打 banner（顺便开浏览器）。

    为什么不在 `uvicorn.run` 之前直接打：起不来时（端口被抢、库是只读的、
    数据目录没权限）老师会先看到一屏「已经在运行」，然后窗口一闪就没 ——
    他拿不到任何原因（评审实测：console 与日志里一行错误都没有）。
    现在起不来会有明确提示，起来之前也不会假报成功。
    """

    def worker() -> None:
        deadline = time.time() + STARTUP_WAIT_SECONDS
        while time.time() < deadline:
            if health(port) is not None:
                banner(port, version, daemon)
                if want_browser:
                    open_browser(f"http://127.0.0.1:{port}/")
                return
            time.sleep(0.25)
        print("服务好像没能起来（等了半分钟还没开始监听）—— 请把这两份日志发给技术同事：")
        print(f"  {data_dir() / 'logs' / 'server.out.log'}")
        print(f"  {data_dir() / 'logs' / 'app.log'}")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread


def serve(port: int, daemon: bool, detached: bool, want_browser: bool = False) -> int:
    """真正跑服务的那一步（前台与后台都走这里）。"""
    if detached:
        redirect_output()
    data_dir().mkdir(parents=True, exist_ok=True)
    os.environ["TWS_DATA_DIR"] = str(data_dir())
    # **把实际用的端口告诉应用**：界面的「手机访问」与二维码里的地址是按
    # `app.config.PORT` 拼的。8723 被占用时启动器会改用 8724，不把这件事告诉应用，
    # 二维码就会指向一个没人监听的端口 —— 老师扫了打不开，而且看不出哪儿错了。
    os.environ["TWS_PORT"] = str(port)
    sys.path.insert(0, str(BACKEND_DIR))

    from app.config import APP_VERSION  # noqa: PLC0415 - 必须在设好环境变量之后导入
    from app.main import app  # noqa: PLC0415

    import uvicorn  # noqa: PLC0415

    warn_if_running_from_temp()
    if not acquire_lock(port):
        print("已经有实例在启动或运行了 —— 稍等一下，或用「状态」看它跑没跑。")
        return 0
    print(f"班主任工作台 v{APP_VERSION} 正在启动…（数据目录：{data_dir()}）")
    write_state(port)
    announce_when_ready(port, APP_VERSION, daemon, want_browser=want_browser)
    try:
        uvicorn.run(
            app,
            host=os.environ.get("TWS_HOST", "0.0.0.0"),
            port=port,
            log_level="info",
            # 别让 uvicorn 自己重配日志：用我们那套（写进 data/logs/app.log），
            # 否则它启动失败的报错只落在控制台上，老师关掉窗口就查不到了
            log_config=None,
        )
    except Exception as exc:  # noqa: BLE001 - 起不来的原因必须让老师看见
        print()
        print(f"启动失败：{type(exc).__name__}: {exc}")
        print("  常见原因：端口被别的程序占用、数据目录没有写权限、数据库被别的程序锁着。")
        print(f"  日志：{data_dir() / 'logs' / 'app.log'}")
        return 1
    finally:
        clear_state()
        release_lock()
        print("服务已停止。")
    return 0


def cmd_start(daemon: bool, want_browser: bool, base_port: int) -> int:
    existing = running()
    if existing is not None:
        port = int(existing["port"])
        print(f"已经在运行了（端口 {port}），直接帮你打开界面。")
        if want_browser:
            open_browser(f"http://127.0.0.1:{port}/")
        return 0

    if read_state() is not None:
        clear_state()  # pid 文件在、服务不在 → 上次没退干净，清掉再启

    port = next((p for p in range(base_port, base_port + PORT_TRIES) if port_free(p)), None)
    if port is None:
        print(f"端口 {base_port}–{base_port + PORT_TRIES - 1} 都被占用了，请先关掉占用它的程序。")
        return 1

    if not daemon:
        return serve(port, daemon=False, detached=False, want_browser=want_browser)

    # 后台：起一个脱离终端的自己，然后等它真的起来
    spawn_daemon(port)
    deadline = time.time() + DAEMON_WAIT_SECONDS
    while time.time() < deadline:
        if health(port) is not None:
            banner(port, "", daemon=True)
            if want_browser:
                open_browser(f"http://127.0.0.1:{port}/")
            return 0
        time.sleep(0.25)

    # 等超了不代表失败：**第一次启动要建数据库、跑全部迁移**，慢一些很正常
    # （老师第一次装必然碰上）。进程还在就如实说「还在启动」，别报「失败」吓人。
    state = read_state()
    if state and int(state.get("port") or 0) == port:
        print("已经在启动了 —— 第一次运行要建数据库、跑迁移，比平时慢一点，请稍等半分钟。")
        banner(port, "", daemon=True)
        return 0

    print("后台启动似乎没成功 —— 请把这两份日志发给技术同事：")
    print(f"  {data_dir() / 'logs' / 'server.out.log'}")
    print(f"  {data_dir() / 'logs' / 'app.log'}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="班主任工作台 · 一键启动器")
    parser.add_argument("--daemon", action="store_true", help="后台运行（无窗口），日志写进数据目录")
    parser.add_argument("--stop", action="store_true", help="停止正在运行的实例")
    parser.add_argument("--status", action="store_true", help="看它在不在跑")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument(
        "--port", type=int, default=None, help=f"指定端口（默认 {DEFAULT_PORT} 起，被占就往后找）"
    )
    parser.add_argument("--install-autostart", action="store_true", help="设置开机自启（后台运行）")
    parser.add_argument("--remove-autostart", action="store_true", help="取消开机自启")
    parser.add_argument("--detached", action="store_true", help=argparse.SUPPRESS)  # 内部用
    args = parser.parse_args(argv)

    if args.install_autostart:
        return install_autostart()
    if args.remove_autostart:
        return remove_autostart()
    if args.stop:
        return cmd_stop()
    if args.status:
        return cmd_status()
    if args.detached:
        return serve(args.port or DEFAULT_PORT, daemon=True, detached=True)
    return cmd_start(args.daemon, not args.no_browser, args.port or base_port())


if __name__ == "__main__":
    raise SystemExit(main())
