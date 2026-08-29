"""Logging configuration.

Uvicorn sets ``propagate: False`` on its loggers by default, which prevents its
access/error logs from reaching the OpenTelemetry log handler attached to the
root logger. We force propagation so those logs are exported over OTLP.
"""

from __future__ import annotations

import copy

from uvicorn.config import LOGGING_CONFIG


def uvicorn_log_config() -> dict:
    """Return uvicorn's logging config with propagation enabled on its loggers."""
    config = copy.deepcopy(LOGGING_CONFIG)
    for logger in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        entry = config.setdefault("loggers", {}).setdefault(logger, {})
        entry["propagate"] = True
    return config
