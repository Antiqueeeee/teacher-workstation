"""日志配置。

存在的理由很直白：`config.LOG_DIR` 建了目录却没人往里写，
出问题只能靠人回忆 —— 而老师自己部署、我们不在现场，日志是唯一的线索。

写入 `data/logs/app.log`，按大小轮转，保留 5 份；同时输出到控制台，
方便开发时直接看。日志内容不得含学生姓名、电话、身份证、媒体路径（见 `05` §6）。
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.config import LOG_DIR

LOG_FILE = LOG_DIR / "app.log"
_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """配置根日志。重复调用安全（已有 handler 就只调级别）。"""
    root = logging.getLogger()
    root.setLevel(level)

    if any(isinstance(handler, RotatingFileHandler) for handler in root.handlers):
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(console)

    # uvicorn 自己的 logger 也接进来，否则请求日志和业务日志分家
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True

    logging.getLogger(__name__).info("日志已启用：%s", LOG_FILE)
