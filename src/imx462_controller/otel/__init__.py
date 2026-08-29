"""OpenTelemetry helpers.

Exposes a ``get_tracer`` that degrades to no-op spans when the OpenTelemetry SDK
is not installed (e.g. on dev machines), so camera code stays testable without
the SDK.
"""

from __future__ import annotations


class _NoopSpan:
    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def __getattr__(self, name: str):
        return lambda *args, **kwargs: None


class _NoopTracer:
    def start_as_current_span(self, *args, **kwargs) -> _NoopSpan:
        return _NoopSpan()

    def __getattr__(self, name: str):
        return lambda *args, **kwargs: None


def get_tracer(name: str):
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except ImportError:
        return _NoopTracer()
