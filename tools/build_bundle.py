#!/usr/bin/env python3
"""把**交付包**组装出来：自带 Python 运行时 + 全部依赖 + 代码 + 双击脚本 → 一个压缩包。

老师拿到的东西必须能直接跑（他们的电脑不联网、装不了 Python、也没有管理员权限），
所以这里做四件事：

1. 下一份**可搬移的** CPython（python-build-standalone 的 `install_only`，专为分发设计，
   解压到任意目录都能跑）→ 放进 `runtime/`；
2. 按 `backend/requirements.txt` 把**全部依赖的轮子**下到 `vendor/wheels/`（构建机联网时做一次），
   再解开进 `runtime/` 的 site-packages —— 目标机器不需要 pip、不需要网络；
3. 把代码、`launcher.py`、双击脚本、使用说明拷进去；
4. 交付包里的**行尾与权限**按各平台的要求收拾好（`.bat` 要 CRLF、`.command` 要可执行位 ——
   从 git 仓库直接拷出来时这两样都不对，见 CONTRIBUTING §10），最后打 zip。

用法：

    # Windows x64（在 Windows 上构建）
    python tools/build_bundle.py --platform windows-x64

    # macOS（**必须在 macOS 上构建**，原因见 --help 里的说明）
    python tools/build_bundle.py --platform macos-arm64

    # 已经下过一遍（vendor/ 里有缓存）时不再联网
    python tools/build_bundle.py --platform windows-x64 --offline

产物：`dist/班主任工作台-<平台>-<版本>.zip`（里面的顶层目录就是老师解压出来的那个文件夹）。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VENDOR = REPO / "vendor"
DIST = REPO / "dist"
STAGE = REPO / "build" / "_stage"

# python-build-standalone：可搬移的 CPython，专为「拷走就能跑」设计
PBS_RELEASE = "20260901"
PBS_PYTHON = "3.11.16"
PBS_BASE = f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_RELEASE}"

PLATFORMS = {
    "windows-x64": {
        "pbs": "x86_64-pc-windows-msvc",
        "pip": "win_amd64",
        "host": "win32",
        "runtime_python": "python.exe",
        "site_packages": "Lib/site-packages",
        "label": "Windows 64 位",
    },
    "macos-arm64": {
        "pbs": "aarch64-apple-darwin",
        "pip": "macosx_11_0_arm64",
        "host": "darwin",
        "runtime_python": "bin/python3",
        "site_packages": "lib/python3.11/site-packages",
        "label": "macOS（Apple 芯片）",
    },
    "macos-x64": {
        "pbs": "x86_64-apple-darwin",
        "pip": "macosx_10_9_x86_64",
        "host": "darwin",
        "runtime_python": "bin/python3",
        "site_packages": "lib/python3.11/site-packages",
        "label": "macOS（Intel 芯片）",
    },
}

# 放进交付包的东西（顺序即解压后的目录顺序，不影响功能）
INCLUDE_FILES = (
    "launcher.py",
    "使用说明.md",
    "README.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
)
INCLUDE_DIRS = ("backend", "frontend", "docs")
# 双击脚本：Windows 与 macOS 两套都带上（老师哪台机器都能用同一份包）
BAT_SCRIPTS = (
    "_python.bat",
    "启动.bat",
    "后台启动.bat",
    "停止.bat",
    "状态.bat",
    "设置开机自启.bat",
    "取消开机自启.bat",
)
SH_SCRIPTS = (
    "_python.sh",
    "启动.command",
    "后台启动.command",
    "停止.command",
    "状态.command",
    "设置开机自启.command",
    "取消开机自启.command",
)
# 不该进交付包的东西（开发用、体积大、或含隐私的素材）
SKIP_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "tests",
    "data",
    "runtime",
    "dist",
    "vendor",
    "raw-material",
    ".git",
    ".validation",
    "build",
    "*.pyc",
}


def log(message: str) -> None:
    print(message, flush=True)


def download(url: str, target: Path) -> Path:
    """下载到本地缓存（已存在就不重复下 —— 构建机可能只联网一次）。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0:
        log(f"  已缓存：{target.name}（{target.stat().st_size / 1024 / 1024:.1f} MB）")
        return target
    log(f"  下载：{url}")
    tmp = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, open(tmp, "wb") as out:
        shutil.copyfileobj(response, out, length=1024 * 1024)
    tmp.replace(target)
    log(f"  完成：{target.name}（{target.stat().st_size / 1024 / 1024:.1f} MB）")
    return target


def fetch_runtime(platform: dict, offline: bool) -> Path:
    asset = f"cpython-{PBS_PYTHON}+{PBS_RELEASE}-{platform['pbs']}-install_only_stripped.tar.gz"
    target = VENDOR / "python" / asset
    if not target.exists() and offline:
        raise SystemExit(f"离线模式但缓存里没有 {asset} —— 先联网跑一次，或手动放进 {target.parent}")
    return download(f"{PBS_BASE}/{asset}", target)


def fetch_wheels(platform: dict, offline: bool) -> None:
    """把依赖的轮子下到 vendor/wheels（按目标平台下，跨平台构建也成立）。"""
    wheels = VENDOR / "wheels" / platform["pip"]
    wheels.mkdir(parents=True, exist_ok=True)
    if offline:
        if not any(wheels.glob("*.whl")):
            raise SystemExit(f"离线模式但 {wheels} 里没有轮子 —— 先联网跑一次")
        log(f"  离线：用已有轮子 {len(list(wheels.glob('*.whl')))} 个")
        return
    command = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "-r",
        str(REPO / "backend" / "requirements.txt"),
        "--dest",
        str(wheels),
        "--only-binary=:all:",
        "--platform",
        platform["pip"],
        "--python-version",
        "3.11",
        "--implementation",
        "cp",
    ]
    log("  拉依赖轮子（只下轮子、不编译）：")
    subprocess.run(command, check=True)


def extract_runtime(tarball: Path, destination: Path) -> None:
    """解开运行时。`install_only` 包里的顶层目录是 `python/`，这里摊平成 `runtime/`。"""
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    with tarfile.open(tarball, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            # 去掉顶层 `python/`（PBS 的 install_only 布局）
            parts = Path(member.name).parts
            if len(parts) < 2 or parts[0] != "python":
                continue
            member.name = str(Path(*parts[1:]))
            archive.extract(member, destination, filter="tar")
    log(f"  运行时解压到 {destination.relative_to(REPO)}")


def install_deps(platform: dict, runtime: Path, offline: bool) -> None:
    """把轮子解开到运行时的 site-packages（跨平台可行：只是解包，不执行）。

    用**构建机的 pip** 做这件事，但目标目录是交付包里的运行时 —— 装完就与构建机无关了。
    """
    site_packages = runtime / platform["site_packages"]
    site_packages.mkdir(parents=True, exist_ok=True)
    wheels = VENDOR / "wheels" / platform["pip"]
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-index",
        "--find-links",
        str(wheels),
        "--target",
        str(site_packages),
        "--only-binary=:all:",
        "--platform",
        platform["pip"],
        "--python-version",
        "3.11",
        "--implementation",
        "cp",
        "--upgrade",
        "-r",
        str(REPO / "backend" / "requirements.txt"),
    ]
    subprocess.run(command, check=True)
    log(f"  依赖装进 {site_packages.relative_to(REPO)}")


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def copy_tree(src: Path, dst: Path) -> None:
    """拷目录，跳过开发用的东西（缓存、测试、数据、素材）。"""
    for item in src.iterdir():
        if item.name in SKIP_NAMES or item.name.endswith(".pyc"):
            continue
        target = dst / item.name
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            copy_tree(item, target)
        else:
            copy_file(item, target)


def normalize_scripts(package: Path) -> None:
    """把双击脚本的行尾与权限收拾成各平台要求的样子。

    为什么必须做：git 仓库里统一存 LF，只在 checkout 时按 `.gitattributes` 转换；
    **从仓库直接打 zip 连 checkout 都没有** —— 交付包里 .bat 会是 LF（双击报错）、
    .command 没有可执行位（macOS 打不开）。
    """
    for name in BAT_SCRIPTS:
        path = package / name
        if not path.exists():
            continue
        data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        path.write_bytes(data.replace(b"\n", b"\r\n"))
    for name in SH_SCRIPTS:
        path = package / name
        if path.exists():
            # Windows 上 os.chmod 只动只读标记（NTFS 没有 POSIX 权限位）—— 尽力而为。
            # 真正管用的是打进 zip 时写的 external_attr（见 write_zip）
            path.chmod(0o755)
    log(f"  行尾与权限已收拾：{len(BAT_SCRIPTS)} 个 .bat → CRLF，{len(SH_SCRIPTS)} 个脚本 → 755")


def _zip_mode(path: Path) -> int:
    """放进 zip 时给这个文件什么权限位。

    **不能一律 0644**：`runtime/bin/python3` 这类文件必须是可执行的，否则整包在 macOS 上
    「交付即坏」（`.command` 里的 `[ ! -x "$PY" ]` 成立 → 退回系统 python3 → 没装
    开发者工具的 Mac 直接弹窗要装 CLI 工具）。
    Windows 的 NTFS 没有 POSIX 权限位（stat 里恒为 0666），所以那里按后缀判断。
    """
    if path.suffix in {".command", ".sh"}:
        return 0o755
    if path.suffix.lower() in {".bat", ".cmd"}:
        # Windows 的批处理不需要（也不看）zip 里的权限位；
        # 另外 CPython 在 Windows 上会把 .bat 的 stat() 报成「可执行」，
        # 真按它写进去会让别的解压工具困惑
        return 0o644
    mode = path.stat().st_mode
    return 0o755 if mode & 0o111 else 0o644


def write_zip(package: Path, archive: Path, root: str) -> None:
    """打 zip：带**顶层目录**（右键「解压到当前文件夹」也不会散一地），
    并给 `.command` / `.sh` 写上可执行位（macOS 双击靠它）。"""
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(package.rglob("*")):
            if path.is_dir():
                continue
            relative = f"{root}/{path.relative_to(package).as_posix()}"
            info = zipfile.ZipInfo(relative, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (_zip_mode(path) << 16)
            bundle.writestr(info, path.read_bytes())


def build_package(platform_key: str, offline: bool) -> Path:
    platform = PLATFORMS[platform_key]
    log(f"构建 {platform['label']} 交付包")

    if sys.platform != platform["host"] and not os.environ.get("TWS_BUILD_CROSS"):
        raise SystemExit(
            f"这个包要在 {platform['host']} 上构建，当前是 {sys.platform}。\n"
            "  原因：macOS 的运行时压缩包里含**符号链接**（bin/python3 → python3.11），\n"
            "  在 Windows 上解压会把它们变成普通文件，到了 Mac 上就坏了。\n"
            "  如果确实要跨平台构建，设 TWS_BUILD_CROSS=1 自己承担风险（未验证）。"
        )

    log("1) 取运行时")
    tarball = fetch_runtime(platform, offline)
    runtime = STAGE / "runtime"
    extract_runtime(tarball, runtime)

    log("2) 取依赖轮子")
    fetch_wheels(platform, offline)

    log("3) 把依赖装进运行时（只是解开轮子，不执行任何东西）")
    install_deps(platform, runtime, offline)

    log("4) 组装交付包")
    package = STAGE / "package"
    if package.exists():
        shutil.rmtree(package)
    package.mkdir(parents=True)
    runtime.rename(package / "runtime")

    for name in INCLUDE_FILES + BAT_SCRIPTS + SH_SCRIPTS:
        src = REPO / name
        if not src.exists():
            raise SystemExit(f"缺少 {name} —— 交付包里必须有它（先跑 tools/check_launch_scripts.py）")
        copy_file(src, package / name)
    for name in INCLUDE_DIRS:
        copy_tree(REPO / name, package / name)
    normalize_scripts(package)

    log("4) 打 zip")
    DIST.mkdir(parents=True, exist_ok=True)
    version = _app_version()
    archive = DIST / f"班主任工作台-{platform_key}-{version}.zip"
    root = f"班主任工作台-{platform_key}-{version}"
    write_zip(package, archive, root)
    log(f"  产物：{archive.relative_to(REPO)}（{archive.stat().st_size / 1024 / 1024:.1f} MB）")
    return archive


def _app_version() -> str:
    sys.path.insert(0, str(REPO / "backend"))
    from app.config import APP_VERSION

    return APP_VERSION


def verify(package: Path, platform_key: str) -> None:
    """构建完就地验一遍：用**交付包里的运行时**导入全部依赖，并真起一次服务。

    不验的话，最可能的失败（少一个依赖、运行时搬不动）要到老师的电脑上才暴露。
    """
    platform = PLATFORMS[platform_key]
    python = package / "runtime" / platform["runtime_python"]
    if not python.exists():
        raise SystemExit(f"交付包里没有运行时：{python}")
    # **导入整个应用**，而不是手写一份依赖清单：手写的那份必然漏（新加依赖就漏一个），
    # 而漏掉的表现是「交付包在老师的电脑上启动即报错」。app.main 会把依赖全拉起来。
    env = {**os.environ, "TWS_DATA_DIR": str(package / "data"), "PYTHONPATH": str(package / "backend")}
    imports = (
        "import app.main;"
        "from app.services.access_info import qr_svg;"
        "assert qr_svg('http://127.0.0.1:8723/').startswith('<svg');"
        "print('应用与依赖导入 OK（含二维码依赖）')"
    )
    subprocess.run([str(python), "-c", imports], check=True, cwd=package, env=env)

    if sys.platform != platform["host"]:
        log("（跨平台构建，跳过「真起一次服务」那步）")
        return

    log("  起一次服务、请求 /health 与 /system/access …")
    env = {**os.environ, "TWS_DATA_DIR": str(package / "data"), "PYTHONPATH": str(package / "backend")}
    process = subprocess.Popen(
        [str(python), str(package / "launcher.py"), "--daemon", "--no-browser"],
        cwd=package,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    process.wait(timeout=60)
    status = subprocess.run(
        [str(python), str(package / "launcher.py"), "--status"],
        cwd=package,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    log("  " + status.stdout.strip().replace("\n", "\n  "))
    # 顺手把新功能也验一下：访问地址 / 二维码在**交付包里**要真的能用，
    # 而且地址里的端口必须是**它实际监听的端口**（8723 被占用时会改用别的端口，
    # 二维码指错端口的话老师扫了就是打不开 —— 这个 bug 真出现过）
    probe = (
        "import json, urllib.request, pathlib;"
        f"state = json.loads(pathlib.Path(r'{package / 'data' / 'server.json'}').read_text(encoding='utf-8'));"
        "port = state['port'];"
        "data = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{port}/api/v1/system/access').read())['data'];"
        "assert data['lan'].startswith('http://') and data['qrSvg'].startswith('<svg');"
        "assert data['port'] == port, f'地址里的端口 {data[\"port\"]} 与实际端口 {port} 不一致';"
        "print('访问地址与二维码 OK：' + data['lan'])"
    )
    subprocess.run([str(python), "-c", probe], check=True, cwd=package, env=env)
    subprocess.run([str(python), str(package / "launcher.py"), "--stop"], cwd=package, env=env, check=False)
    if status.returncode != 0:
        raise SystemExit("交付包起来了但状态查询失败 —— 别急着交付，先看上面的输出")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="组装交付包（自带 Python 运行时 + 依赖）")
    parser.add_argument("--platform", required=True, choices=sorted(PLATFORMS), help="目标平台")
    parser.add_argument("--offline", action="store_true", help="只用 vendor/ 里的缓存，不联网")
    parser.add_argument("--check", action="store_true", help="构建后不删中间目录（便于查看）")
    parser.add_argument("--verify-only", action="store_true", help="只验证已有的中间产物")
    args = parser.parse_args(argv)

    package = STAGE / "package"
    if not args.verify_only:
        archive = build_package(args.platform, args.offline)
        log(f"完成：{archive}")
    verify(package, args.platform)
    if not args.check and package.exists():
        shutil.rmtree(package, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
