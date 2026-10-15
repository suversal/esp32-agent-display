from __future__ import annotations

import argparse
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiohttp import web

from .config import load_config
from .server import create_app


def main() -> None:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="AI 编程助手状态桥接服务")
    parser.add_argument("--config", type=Path, default=Path("~/.config/agent-display/config.toml").expanduser())
    parser.add_argument("--host", help="覆盖监听地址")
    parser.add_argument("--port", type=int, help="覆盖端口")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.host is not None:
        config.host = args.host
    if args.port is not None:
        config.port = args.port
    config.validate()
    log_path = Path(config.log_path).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    file_handler = RotatingFileHandler(log_path, maxBytes=1_048_576, backupCount=3, encoding="utf-8")
    log_path.chmod(0o600)
    logging.basicConfig(
        level=config.log_level.upper(), format="%(asctime)s %(levelname)s %(message)s",
        handlers=[file_handler, logging.StreamHandler()],
    )
    logging.getLogger("agent-display").info("Starting bridge on %s:%d", config.host, config.port)
    # Disabling the access log keeps the WebSocket query token out of logs.
    web.run_app(create_app(config), host=config.host, port=config.port, access_log=None, print=None)


if __name__ == "__main__":
    main()
