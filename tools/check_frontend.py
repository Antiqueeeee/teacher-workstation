#!/usr/bin/env python3
"""前端静态检查（无构建步骤的项目更需要这个）。

检查三件事，都是「一错就白屏」的类型：

1. `frontend/src/**/*.js` 里的相对 import 路径是否真实存在（打错一个字母，页面直接空白）；
2. `index.html` 引用的样式与脚本文件是否都在；
3. 有没有指向外网的资源（部署环境离线，任何 CDN 都会在目标机器上失效）。

用法：
    python tools/check_frontend.py
退出码：0 = 通过；1 = 有问题。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FRONTEND = REPO / "frontend"
INDEX = FRONTEND / "index.html"

# 相对 import：`import x from './a.js'` / `export ... from '../b.js'`
IMPORT_RE = re.compile(r"""(?:from|import)\s*['"](\.[^'"]+)['"]""")
# index.html 里的本地资源引用
ATTR_RE = re.compile(r"""(?:href|src)\s*=\s*["'](/[^"']+)["']""")
# 指向外网的资源（离线环境不允许）
REMOTE_RE = re.compile(r"""(?:href|src)\s*=\s*["'](https?:)?//""", re.IGNORECASE)


def check_imports(problems: list[str]) -> int:
    count = 0
    for path in sorted((FRONTEND / "src").rglob("*.js")):
        count += 1
        text = path.read_text(encoding="utf-8")
        for spec in IMPORT_RE.findall(text):
            target = (path.parent / spec).resolve()
            if not target.exists():
                problems.append(f"{path.relative_to(REPO)} → import '{spec}' 找不到目标文件")
    return count


def check_index(problems: list[str]) -> None:
    if not INDEX.exists():
        problems.append("frontend/index.html 不存在")
        return
    text = INDEX.read_text(encoding="utf-8")

    if REMOTE_RE.search(text):
        problems.append("index.html 里引用了外网资源（部署环境离线，必须去掉）")

    for ref in ATTR_RE.findall(text):
        target = FRONTEND / ref.lstrip("/")
        if not target.exists():
            problems.append(f"index.html → 引用的 {ref} 不存在")


def main() -> int:
    problems: list[str] = []
    js_count = check_imports(problems)
    check_index(problems)

    if problems:
        print(f"X 前端检查发现 {len(problems)} 个问题（已检查 {js_count} 个 js 文件）：")
        for item in problems:
            print(f"    {item}")
        return 1

    print(f"OK 前端检查通过：{js_count} 个 js 文件的 import 均可解析，index.html 引用完整且无外网资源")
    return 0


if __name__ == "__main__":
    sys.exit(main())
