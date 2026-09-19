"""自带 Python 运行时的下载与解压 —— **构建交付包与「克隆即用」自举共用这一份**。

老师的电脑上不装 Python、也不算 Docker，所以运行时要随项目走。两处会用：
`tools/build_bundle.py`（我这边打交付包）与 `tools/bootstrap.py`（老师/助手克隆下来第一次跑）。
两处各写一份平台映射与下载逻辑，迟早会出现「包里的运行时和自举装的不是同一个版本」。

用的是 python-build-standalone 的 `install_only` 发行版：可搬移，解压到任意目录都能跑，
正是为「拷走就能用」设计的。
"""

from __future__ import annotations

import platform
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

PBS_RELEASE = "20260901"
PBS_PYTHON = "3.11.16"
PBS_BASE = f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_RELEASE}"

# 本机平台 → python-build-standalone 的平台标识（没有的平台上就自举不了，如实报错）
HOST_PBS = {
    "win32": "x86_64-pc-windows-msvc",
    "darwin": None,  # 需要按芯片判断，见 host_platform()
}


def host_platform() -> str | None:
    """本机对应的 PBS 平台标识；不支持的平台返回 None。"""
    if sys.platform == "win32":
        return "x86_64-pc-windows-msvc"
    if sys.platform == "darwin":
        machine = platform.machine().lower()
        return "aarch64-apple-darwin" if machine in {"arm64", "aarch64"} else "x86_64-apple-darwin"
    return None


def host_pip_platform() -> str:
    """本机在 pip 眼里的平台标签（离线自举时按它找轮子目录，与 build_bundle 的布局一致）。"""
    if sys.platform == "win32":
        return "win_amd64"
    if sys.platform == "darwin":
        return "macosx_11_0_arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "macosx_10_9_x86_64"
    return "linux_x86_64"


def asset_name(platform_id: str) -> str:
    return f"cpython-{PBS_PYTHON}+{PBS_RELEASE}-{platform_id}-install_only_stripped.tar.gz"


def asset_url(platform_id: str) -> str:
    return f"{PBS_BASE}/{asset_name(platform_id)}"


def runtime_python(runtime_dir: Path) -> Path:
    """运行时里的解释器路径（Windows 与 macOS 的布局不同）。"""
    if sys.platform == "win32":
        return runtime_dir / "python.exe"
    return runtime_dir / "bin" / "python3"


def download(url: str, target: Path, *, log=print) -> Path:
    """下载到本地（已存在就跳过，便于重试）。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0:
        log(f"  已缓存：{target.name}")
        return target
    log(f"  下载运行时：{url}")
    tmp = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, open(tmp, "wb") as out:
        shutil.copyfileobj(response, out, length=1024 * 1024)
    tmp.replace(target)
    log(f"  完成：{target.name}（{target.stat().st_size / 1024 / 1024:.1f} MB）")
    return target


def extract_runtime(tarball: Path, destination: Path, *, log=print) -> None:
    """解开运行时（`install_only` 包里顶层是 `python/`，这里摊平成 `runtime/`）。"""
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    with tarfile.open(tarball, "r:gz") as archive:
        for member in archive.getmembers():
            parts = Path(member.name).parts
            if len(parts) < 2 or parts[0] != "python":
                continue
            member.name = str(Path(*parts[1:]))
            archive.extract(member, destination, filter="tar")
    log(f"  运行时已就位：{destination}")


def ensure_runtime(runtime_dir: Path, cache_dir: Path, *, log=print) -> Path:
    """确保 `runtime_dir` 里有可用的解释器，返回它的路径。

    已经装过就直接用（离线也能跑）；没装过就下一份、解开。
    """
    existing = runtime_python(runtime_dir)
    if existing.exists():
        log(f"  已有运行时：{existing}")
        return existing

    platform_id = host_platform()
    if platform_id is None:
        raise SystemExit(
            f"这个系统（{sys.platform}）暂时没有自带运行时的方案。\n"
            "  Windows 与 macOS 都支持；其它系统请让技术同事处理。"
        )
    tarball = download(asset_url(platform_id), cache_dir / asset_name(platform_id), log=log)
    extract_runtime(tarball, runtime_dir, log=log)
    python = runtime_python(runtime_dir)
    if not python.exists():
        raise SystemExit(f"解开之后没找到解释器：{python}")
    return python


def python_is_new_enough(executable: str, minimum: tuple[int, int] = (3, 9)) -> bool:
    """这个 Python 够不够用来跑自举脚本（我们只用它下载与安装，不用它跑服务）。"""
    import subprocess

    code = f"import sys; raise SystemExit(0 if sys.version_info >= {minimum!r} else 1)"
    try:
        return subprocess.run([executable, "-c", code], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def main() -> int:  # pragma: no cover - 命令行入口，供人手动验证
    """手动预装运行时（一般不需要，启动脚本会自动调）。"""
    repo = Path(__file__).resolve().parent.parent
    python = ensure_runtime(repo / "runtime", repo / "vendor" / "python")
    print(python)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
