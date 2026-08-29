"""Application entrypoint."""

from __future__ import annotations

import logging
import os
import sys

import uvicorn

from .api.app import create_app
from .config import ConfigError, load_config, load_secrets
from .logging import uvicorn_log_config


def main() -> None:
    config_path = os.environ.get("IMX462_CONFIG", "config.yaml")
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"Fatal: {exc}", file=sys.stderr)
        raise SystemExit(1)

    secrets = load_secrets(".env")

    level = getattr(logging, config.logging.level.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    app = create_app(config, secrets)
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
        log_config=uvicorn_log_config(),
    )


if __name__ == "__main__":
    main()
