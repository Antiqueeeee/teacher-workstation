"""「克隆即用」自举的两块砖（`tools/pbs_runtime.py` 与 `tools/bootstrap.py`）。

这条路的要害是**别碰老师自己的 Python 环境**：系统里的 Python 只允许当引导
（下载运行时、装依赖到项目目录），跑服务的永远是项目自带的那个。
所以这里盯三件事：

1. 平台映射与资源名对得上（下错平台 = 老师的电脑上跑不起来）；
2. 运行时里没有依赖时要能发现（判据是**导入整个应用**，不是手写依赖清单 —— 清单必然漏）；
3. 离线模式没有缓存时要**明确报错**，不能装一半。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import bootstrap  # noqa: E402
import pbs_runtime  # noqa: E402


def test_host_platform_maps_windows_and_macos(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pbs_runtime.sys, "platform", "win32")
    assert pbs_runtime.host_platform() == "x86_64-pc-windows-msvc"

    monkeypatch.setattr(pbs_runtime.sys, "platform", "darwin")
    monkeypatch.setattr(pbs_runtime.platform, "machine", lambda: "arm64")
    assert pbs_runtime.host_platform() == "aarch64-apple-darwin"
    monkeypatch.setattr(pbs_runtime.platform, "machine", lambda: "x86_64")
    assert pbs_runtime.host_platform() == "x86_64-apple-darwin"

    monkeypatch.setattr(pbs_runtime.sys, "platform", "linux")
    assert pbs_runtime.host_platform() is None, "没有方案的平台要明确返回 None，别硬猜"


def test_asset_name_and_url_are_consistent():
    asset = pbs_runtime.asset_name("x86_64-pc-windows-msvc")
    assert asset == f"cpython-{pbs_runtime.PBS_PYTHON}+{pbs_runtime.PBS_RELEASE}-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
    assert pbs_runtime.asset_url("x86_64-pc-windows-msvc").endswith("/" + asset)
    assert pbs_runtime.PBS_BASE.startswith("https://")


def test_runtime_python_layout_differs_per_platform(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pbs_runtime.sys, "platform", "win32")
    assert pbs_runtime.runtime_python(Path("/x/runtime")).name == "python.exe"
    monkeypatch.setattr(pbs_runtime.sys, "platform", "darwin")
    assert pbs_runtime.runtime_python(Path("/x/runtime")) == Path("/x/runtime/bin/python3")


def test_deps_check_imports_the_whole_app():
    """判据是导入 `app.main`：手写依赖清单会漏（新加一个依赖就漏一个）。

    这里用**当前解释器**（测试环境里依赖是齐的）验证这个判据真的会去导入应用。
    """
    assert bootstrap.deps_installed(Path(sys.executable)) is True


def test_deps_check_reports_missing_dependencies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """项目里没有应用代码时（比如只克隆了一半）要报「不齐」，而不是假装通过。"""
    (tmp_path / "backend").mkdir()
    monkeypatch.setattr(bootstrap, "REPO", tmp_path)
    assert bootstrap.deps_installed(Path(sys.executable)) is False


def test_offline_bootstrap_without_cache_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """离线自举但没缓存过运行时：明确报错，别装一半留个坏目录。"""
    monkeypatch.setattr(bootstrap, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(bootstrap, "CACHE_DIR", tmp_path / "vendor" / "python")
    with pytest.raises(SystemExit) as exc:
        bootstrap.bootstrap(offline=True)
    assert "离线" in str(exc.value)


def test_requirements_file_is_where_bootstrap_expects_it():
    assert bootstrap.REQUIREMENTS.exists(), "自举要按 backend/requirements.txt 装依赖"
    text = bootstrap.REQUIREMENTS.read_text(encoding="utf-8")
    assert "fastapi" in text and "segno" in text


def test_bootstrap_uses_the_runtimes_own_pip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """依赖必须装进**自带运行时自己的** site-packages（不是系统的）。"""
    calls: list[list[str]] = []

    class FakeResult:
        returncode = 0

    monkeypatch.setattr(
        bootstrap.subprocess, "run", lambda args, *a, **k: (calls.append(list(args)), FakeResult())[1]
    )
    fake_python = tmp_path / "runtime" / "python.exe"
    bootstrap.install_deps(fake_python, offline=False)
    assert calls, "应该调用了 pip"
    assert calls[0][:5] == [str(fake_python), "-m", "pip", "install", "--no-warn-script-location"]
    assert str(bootstrap.REQUIREMENTS) in calls[0]
    assert "-m" in calls[0] and "pip" in calls[0]


def test_check_mode_reports_missing_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    monkeypatch.setattr(bootstrap, "RUNTIME_DIR", tmp_path / "runtime")
    assert bootstrap.main(["--check"]) == 1
    assert "缺运行时" in capsys.readouterr().out
