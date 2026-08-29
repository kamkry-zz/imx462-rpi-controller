from __future__ import annotations

from imx462_controller.logging import uvicorn_log_config


def test_uvicorn_loggers_propagate():
    config = uvicorn_log_config()
    loggers = config["loggers"]
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        assert loggers[name]["propagate"] is True
