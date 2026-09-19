#!/usr/bin/env python3
"""启动脚本的静态检查（「一错就双击没反应」的那类问题）。

三件事，都是真的踩过的：

1. **`.bat` 必须是 CRLF**。只有 LF 的 .bat 会被 cmd 拼成乱七八糟的命令
   （实测报「'xxx' 不是内部或外部命令」，而且报的是半句话）；
2. **`.bat` 只允许 ASCII**。cmd 解析 .bat 用的是**当前代码页**，中文注释会被切成
   半截当命令执行（实测报「'…老师不需要点它。' is not recognized」）。
   中文提示一律交给 Python 打印（`launcher.py` 已经把这些话说完了）；
3. **`.command` / `.sh` 必须是 LF 且有可执行位**（macOS 双击才会跑）。

另外核对：老师要双击的那几个脚本都在、`launcher.py` 支持脚本里用到的那些开关。

用法：
    python tools/check_launch_scripts.py
退出码：0 = 通过；1 = 有问题。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# 老师要双击的脚本（Windows / macOS 各一套）
BAT_SCRIPTS = ("启动.bat", "后台启动.bat", "停止.bat", "状态.bat", "设置开机自启.bat", "取消开机自启.bat")
SH_SCRIPTS = ("启动.command", "后台启动.command", "停止.command", "状态.command", "设置开机自启.command", "取消开机自启.command")
HELPERS = ("_python.bat", "_python.sh")


def check_bat(path: Path, problems: list[str]) -> None:
    data = path.read_bytes()
    if b"\r\n" not in data:
        problems.append(f"{path.name}：没有 CRLF 行尾 —— cmd 会把它当乱命令（必须是 CRLF）")
    # 有裸 LF（不是 CRLF 的一部分）也说明换行不统一
    if re.search(rb"(?<!\r)\n", data):
        problems.append(f"{path.name}：混着裸 LF 行尾，请统一成 CRLF")
    try:
        data.decode("ascii")
    except UnicodeDecodeError as exc:
        line = data[: exc.start].count(b"\n") + 1
        problems.append(f"{path.name}:{line}：含非 ASCII 字符（中文注释会让 cmd 报「不是内部或外部命令」）")


def check_sh(path: Path, problems: list[str]) -> None:
    data = path.read_bytes()
    if b"\r\n" in data:
        problems.append(f"{path.name}：含 CRLF —— macOS 的 shell 脚本要 LF，否则 `bash` 可能报错")
    text = data.decode("utf-8")
    if path.suffix == ".command":
        if not data.startswith(b"#!"):
            problems.append(f"{path.name}：缺少 shebang（`#!/bin/bash`），双击不会执行")
        if not text.startswith("#!/bin/bash"):
            problems.append(f"{path.name}：shebang 不是 `#!/bin/bash`（macOS 双击靠它找解释器）")


def main() -> int:
    problems: list[str] = []

    for name in BAT_SCRIPTS + HELPERS[:1]:
        path = REPO / name
        if not path.exists():
            problems.append(f"缺少 {name}")
            continue
        check_bat(path, problems)

    for name in SH_SCRIPTS + HELPERS[1:]:
        path = REPO / name
        if not path.exists():
            problems.append(f"缺少 {name}")
            continue
        check_sh(path, problems)

    # launcher.py 要支持脚本里用到的开关
    launcher = REPO / "launcher.py"
    if not launcher.exists():
        problems.append("缺少 launcher.py")
    else:
        text = launcher.read_text(encoding="utf-8")
        for flag in ("--daemon", "--stop", "--status", "--install-autostart", "--remove-autostart", "--detached"):
            if f'"{flag}"' not in text:
                problems.append(f"launcher.py 里没有 {flag}（启动脚本会用到它）")

    # 那几个脚本要真的能互相找到：.bat 里引用的 helper 必须存在
    for name in BAT_SCRIPTS:
        path = REPO / name
        if path.exists() and "_python.bat" not in path.read_text(encoding="utf-8", errors="ignore"):
            problems.append(f"{name}：没有调用 _python.bat 找运行时")

    check_gitattributes(problems)

    if problems:
        print(f"X 启动脚本检查发现 {len(problems)} 个问题：")
        for item in problems:
            print(f"    {item}")
        return 1
    print(
        f"OK 启动脚本检查通过：{len(BAT_SCRIPTS)} 个 .bat（ASCII + CRLF）、"
        f"{len(SH_SCRIPTS)} 个 .command（LF + shebang）、launcher.py 的开关齐全、行尾规则已声明"
    )
    return 0


def check_gitattributes(problems: list[str]) -> None:
    """`.gitattributes` 里必须声明这几个脚本的行尾规则。

    为什么这也算「启动脚本检查」：git 仓库里统一存 LF，**只在 checkout 时**按
    `eol=` 转成工作区的行尾。没有 `*.bat text eol=crlf` 这条，克隆出来的 .bat 就是 LF，
    双击直接报「不是内部或外部命令」；而**从仓库直接打 zip**（交付包的常见做法）
    连 checkout 都没有，构建脚本得自己把 .bat 转成 CRLF、给 .command 加可执行位。
    """
    path = REPO / ".gitattributes"
    if not path.exists():
        problems.append("缺少 .gitattributes（行尾规则没了，交付出去的脚本可能是坏的）")
        return
    rules: dict[str, list[str]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            rules[parts[0]] = parts[1:]

    for pattern, need in (("*.bat", "eol=crlf"), ("*.command", "eol=lf"), ("*.sh", "eol=lf")):
        if need not in rules.get(pattern, []):
            problems.append(
                f".gitattributes 里缺少 `{pattern} text {need}` —— 克隆/打包出来的行尾会跟"
                f"{pattern} 的硬要求打架"
            )


if __name__ == "__main__":
    sys.exit(main())
