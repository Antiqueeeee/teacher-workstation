"""交付包组装的两条不变式（`tools/build_bundle.py`）。

为什么值得单测：这两件事错了**在开发机上完全看不出来**，
要到老师的电脑上才炸 —— 而那时候我们不在现场：

1. `.bat` 的行尾与 `.command` 的可执行位：git 仓库统一存 LF，从仓库直接打包时
   `.bat` 会是 LF（双击报「不是内部或外部命令」）、`.command` 没有执行位（macOS 打不开）；
2. 打包时**不该带进去**的东西：老师自己的 `data/`、开发用的 `tests/`、
   几百 MB 的 `raw-material/` 素材。带错了轻则包巨大，重则把别人的数据发给另一个老师。
"""

from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import build_bundle  # noqa: E402


def test_normalize_scripts_fixes_line_endings_and_permissions(tmp_path: Path):
    for name in build_bundle.BAT_SCRIPTS:
        (tmp_path / name).write_bytes(b"@echo off\ncd /d \"%~dp0\"\n")
    for name in build_bundle.SH_SCRIPTS:
        (tmp_path / name).write_bytes(b"#!/bin/bash\necho hi\n")

    build_bundle.normalize_scripts(tmp_path)

    bat = (tmp_path / "启动.bat").read_bytes()
    assert b"\r\n" in bat and b"\n\n" not in bat.replace(b"\r\n", b"\n")
    assert bat.count(b"\r\n") == 2, "每一行都该是 CRLF"
    # 文件系统的权限位只在 POSIX 上有意义（Windows 的 NTFS 没有执行位，
    # os.chmod 只动只读标记）；**交付包里靠的是 zip 的属性位**，见下一个用例
    if os.name == "posix":
        for name in build_bundle.SH_SCRIPTS:
            assert (tmp_path / name).stat().st_mode & 0o111, f"{name} 没有可执行位"
    # 幂等：再跑一次不产生 \r\r\n
    build_bundle.normalize_scripts(tmp_path)
    assert (tmp_path / "启动.bat").read_bytes().count(b"\r\r\n") == 0


def test_write_zip_has_a_top_level_folder_and_exec_bits(tmp_path: Path):
    package = tmp_path / "package"
    package.mkdir()
    (package / "启动.bat").write_bytes(b"@echo off\r\n")
    (package / "启动.command").write_bytes(b"#!/bin/bash\n")
    (package / "launcher.py").write_bytes(b"print('hi')\n")
    nested = package / "backend" / "app"
    nested.mkdir(parents=True)
    (nested / "main.py").write_bytes(b"")

    archive = tmp_path / "out.zip"
    build_bundle.write_zip(package, archive, "班主任工作台-windows-x64-0.1.0")

    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        # 顶层目录只有一个（老师解压不会散一地）
        assert {name.split("/")[0] for name in names} == {"班主任工作台-windows-x64-0.1.0"}
        assert "班主任工作台-windows-x64-0.1.0/backend/app/main.py" in names
        modes = {info.filename: info.external_attr >> 16 for info in bundle.infolist()}
    assert modes["班主任工作台-windows-x64-0.1.0/启动.command"] & 0o111
    assert not modes["班主任工作台-windows-x64-0.1.0/启动.bat"] & 0o111
    # .bat 的行尾在包里也是 CRLF（老师在 Windows 上直接双击）
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.read("班主任工作台-windows-x64-0.1.0/启动.bat") == b"@echo off\r\n"


def test_package_never_carries_developer_or_private_data():
    """打包跳过名单必须覆盖这几样：老师的数据、测试、原始素材、构建产物。"""
    for name in ("data", "tests", "raw-material", "vendor", "dist", "__pycache__", ".git"):
        assert name in build_bundle.SKIP_NAMES, f"{name} 没被排除，会被打进交付包"
    # 各平台参数齐全（少一个键会在构建时才炸）
    for key in ("pbs", "pip", "host", "runtime_python", "site_packages", "label"):
        for platform, config in build_bundle.PLATFORMS.items():
            assert key in config, f"{platform} 少了 {key}"
        assert key in build_bundle.PLATFORMS["windows-x64"]


def test_macos_build_refuses_to_run_on_windows(monkeypatch: pytest.MonkeyPatch):
    """在 Windows 上构建 macOS 包必须**明确拒绝**，不能假装成功。

    原因：macOS 运行时压缩包里含符号链接（bin/python3 → python3.11），
    Windows 解压会把它们变成普通文件，到 Mac 上就坏了。
    """
    monkeypatch.delenv("TWS_BUILD_CROSS", raising=False)
    monkeypatch.setattr(build_bundle.sys, "platform", "win32")
    with pytest.raises(SystemExit) as exc:
        build_bundle.build_package("macos-arm64", offline=True)
    assert "macOS" in str(exc.value) or "darwin" in str(exc.value)
