"""应用配置：数据目录、数据库地址、监听地址与全局常量。

约定（见 CONTRIBUTING.md）：
- 数据目录默认在 `backend/data/`，可用环境变量 `TWS_DATA_DIR` 覆盖；
- 服务监听内网地址，手机与电脑都通过它访问（部署环境不联网，不得引入任何外网依赖）。
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "班主任工作台"
APP_VERSION = "0.1.0"

# backend/ 目录
BASE_DIR = Path(__file__).resolve().parent.parent
# 仓库根目录
REPO_DIR = BASE_DIR.parent

DATA_DIR = Path(os.environ.get("TWS_DATA_DIR", BASE_DIR / "data")).resolve()
MEDIA_DIR = DATA_DIR / "media"
LOG_DIR = DATA_DIR / "logs"
DB_PATH = DATA_DIR / "workbench.sqlite"
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"

HOST = os.environ.get("TWS_HOST", "0.0.0.0")  # 0.0.0.0 才能被同一局域网的其他设备访问
PORT = int(os.environ.get("TWS_PORT", "8723"))

# 前端静态资源（无构建步骤，直接托管源码目录）
FRONTEND_DIR = REPO_DIR / "frontend"

# 分页
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 200


def ensure_dirs() -> None:
    """确保运行所需目录存在（首次启动时调用）。"""
    for path in (DATA_DIR, MEDIA_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)
