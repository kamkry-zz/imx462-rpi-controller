"""Programmatic OpenTelemetry setup with graceful degradation.

The OpenTelemetry SDK, OTLP exporters, and FastAPI instrumentation are imported
lazily. If any are missing or the endpoint is unreachable, the app keeps running
without observability (the SDK batches and retries in the background).
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import OtelConfig, Secrets

logger = logging.getLogger(__name__)


def _parse_headers(raw: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        headers[key.strip()] = value.strip()
    return headers


def setup_telemetry(otel_config: OtelConfig, secrets: Secrets, app: Any = None) -> bool:
    """Configure metrics, traces, and correlated logs to export over OTLP.

    Returns True if observability was successfully configured, False otherwise.
    """
    endpoint = (otel_config.endpoint or "").rstrip("/")
    if not endpoint:
        logger.info("OpenTelemetry disabled (no endpoint configured)")
        return False

    try:
        from opentelemetry import metrics, trace
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        logger.warning("OpenTelemetry packages not installed; observability disabled: %s", exc)
        return False

    headers = _parse_headers(secrets.otel_headers)
    resource = Resource.create({"service.name": otel_config.service_name})

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", headers=headers))
    )
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics", headers=headers),
        export_interval_millis=otel_config.metric_export_interval_ms,
    )
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[metric_reader]))

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs", headers=headers))
    )
    logging.getLogger().addHandler(
        LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
    )

    if app is not None:
        FastAPIInstrumentor.instrument_app(app)

    logger.info("OpenTelemetry configured; exporting OTLP to %s", endpoint)
    return True
