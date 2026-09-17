#!/usr/bin/env python3
"""检查单文件行数是否超限。

约定见 CONTRIBUTING.md §3：单文件硬上限 600 行，没有例外。

用法：
    python tools/check_file_size.py                  # 检查项目约定的目录
    python tools/check_file_size.py --limit 400      # 临时改上限（目标值）
    python tools/check_file_size.py backend/app      # 只检查指定路径

退出码：0 = 全部通过；1 = 有文件超限。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

LIMIT = 600
SCAN_ROOTS = (
    "backend/app",
    "backend/tests",
    "frontend/src",
    "frontend/styles",
    "tools",
)
SKIP_DIRS = {"__pycache__", "node_modules", ".venv", "venv", ".git", "_out", ".mypy_cache", ".pytest_cache"}
CHECK_SUFFIXES = {".py", ".js", ".css", ".html"}

# 说明：raw-material/（含旧应用那份 18995 行的单文件）与 .validation/ 故意不在扫描范围内 ——
# 前者是只读参考，后者是本地环境。


def iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in CHECK_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def count_lines(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


def main() -> int:
    parser = argparse.ArgumentParser(description="检查单文件行数上限")
    parser.add_argument("paths", nargs="*", help="要检查的路径（默认按项目约定）")
    parser.add_argument("--limit", type=int, default=LIMIT, help=f"行数上限（默认 {LIMIT}）")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parent.parent
    targets = [Path(p) for p in args.paths] if args.paths else [repo / r for r in SCAN_ROOTS]

    violations: list[tuple[int, str]] = []
    checked = 0

    for target in targets:
        if not target.exists():
            continue
        candidates = [target] if target.is_file() else list(iter_files(target))
        for path in candidates:
            checked += 1
            lines = count_lines(path)
            if lines > args.limit:
                try:
                    shown = path.resolve().relative_to(repo)
                except ValueError:
                    shown = path
                violations.append((lines, str(shown)))

    if violations:
        print(f"X 有 {len(violations)} 个文件超过 {args.limit} 行（共检查 {checked} 个）：")
        for lines, shown in sorted(violations, reverse=True):
            print(f"    {lines:>6} 行  {shown}")
        print("\n请按 CONTRIBUTING.md §3 的拆分手法拆分后再提交。")
        return 1

    print(f"OK 全部通过：{checked} 个文件均未超过 {args.limit} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
