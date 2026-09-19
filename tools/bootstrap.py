#!/usr/bin/env python3
"""「克隆即用」自举：把这个项目需要的 Python 运行时与依赖装到**项目自己目录里**，然后启动。

老师/同事拿到的是一个 git 地址（可能直接丢给 WorkBuddy 这类 AI 助手），所以第一次跑之前
不能要求他装 Python、装依赖、装 Docker。这个脚本就负责把缺的东西补齐：

1. 在 `runtime/` 里放一份**可搬移的 Python**（python-build-standalone，解压即用）；
2. 用它的 pip 把 `backend/requirements.txt` 装进**它自己**的 site-packages；
3. 然后交回 `launcher.py`（端口、二维码、后台运行、开机自启都在那边）。

**不碰老师的系统 Python**：自带运行时装在自己的目录里，不写 PATH、不动全局 site-packages。
系统里的 Python 只用来**跑这个自举脚本**（下载与安装），装完就不再用它。

用法（启动脚本会自动调它，也可以手动跑）：

    python tools/bootstrap.py            # 补齐运行时 + 依赖
    python tools/bootstrap.py --check     # 只看缺不缺，不装
    python tools/bootstrap.py --offline   # 只用 vendor/ 里缓存过的运行时与轮子
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUNTIME_DIR = REPO / "runtime"
CACHE_DIR = REPO / "vendor" / "python"
WHEEL_DIR = REPO / "vendor" / "wheels"
REQUIREMENTS = REPO / "backend" / "requirements.txt"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pbs_runtime import ensure_runtime, host_pip_platform, runtime_python  # noqa: E402


def log(message: str) -> None:
    print(message, flush=True)


def deps_installed(python: Path) -> bool:
    """运行时里依赖齐不齐。

    判据是**导入整个应用**（`import app.main`），不是手写一份依赖清单 ——
    清单必然漏（新加一个依赖就漏一个），而漏掉的表现是「老师那边启动即报错」。
    数据目录指到临时目录，避免真去碰项目里的库。
    """
    with tempfile.TemporaryDirectory(prefix="tws-bootstrap-") as tmp:
        result = subprocess.run(
            [str(python), "-c", "import app.main"],
            capture_output=True,
            cwd=str(REPO / "backend"),
            env={**os.environ, "PYTHONPATH": str(REPO / "backend"), "TWS_DATA_DIR": tmp},
        )
    return result.returncode == 0


def install_deps(python: Path, *, offline: bool) -> None:
    """用**自带运行时自己的 pip** 装依赖（不进系统 site-packages）。"""
    args = [str(python), "-m", "pip", "install", "--no-warn-script-location", "-r", str(REQUIREMENTS)]
    if offline:
        wheel_dir = WHEEL_DIR / host_pip_platform()
        args += ["--no-index", "--find-links", str(wheel_dir)]
    log("  安装依赖（只装进自带运行时，不动你电脑上的 Python）：")
    result = subprocess.run(args)
    if result.returncode != 0:
        raise SystemExit(
            "依赖没装上。\n"
            f"  联网环境：检查网络后重跑；离线环境：把轮子放到 {WHEEL_DIR} 再带 --offline 跑。"
        )


def bootstrap(*, offline: bool = False) -> Path:
    log(f"为这个项目准备 Python 运行时（装在 {RUNTIME_DIR}，不碰你系统里的 Python）")
    if offline and not CACHE_DIR.exists():
        raise SystemExit(f"离线模式，但 {CACHE_DIR} 里没有缓存过的运行时")
    python = ensure_runtime(RUNTIME_DIR, CACHE_DIR, log=log)

    if deps_installed(python):
        log("  依赖已齐（跳过安装）")
    else:
        install_deps(python, offline=offline)
        if not deps_installed(python):
            raise SystemExit("依赖装完了但仍然 import 不了 —— 请把上面的输出发给技术同事")
    log("准备好了。")
    return python


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把这个项目的 Python 运行时与依赖装到项目自己目录里")
    parser.add_argument("--offline", action="store_true", help="只用 vendor/ 里缓存的东西，不联网")
    parser.add_argument("--check", action="store_true", help="只检查，不安装")
    args = parser.parse_args(argv)

    if args.check:
        python = runtime_python(RUNTIME_DIR)
        if not python.exists():
            print("缺运行时：runtime/ 还不存在")
            return 1
        if not deps_installed(python):
            print("有运行时，但依赖不齐")
            return 1
        print(f"都齐了：{python}")
        return 0

    # 系统 Python 只用来跑这个脚本：太旧就用不了（如实说，而不是抛一堆语法错误）
    if sys.version_info < (3, 9):
        raise SystemExit(
            f"用来跑自举的 Python 太旧了（{sys.version.split()[0]}）—— 需要 3.9 以上。\n"
            "  这只是**引导用的** Python；装好之后服务用的是自带运行时，与你系统里的 Python 无关。"
        )
    if not REQUIREMENTS.exists():
        raise SystemExit(f"找不到 {REQUIREMENTS}")

    python = bootstrap(offline=args.offline)
    print(f"自带的 Python：{python}")
    print(f"下一步直接跑服务：{python} launcher.py（启动脚本会自动这么做）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
