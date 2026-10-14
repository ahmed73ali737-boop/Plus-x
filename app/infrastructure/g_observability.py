"""G-Factory HTTP telemetry source dependency; no bodies, logs, identities or raw URLs.

An absent OTEL_EXPORTER_OTLP_ENDPOINT disables collection without importing the SDK.
Use a trusted base endpoint (HTTP/protobuf), e.g. http://collector:4318.
"""
from __future__ import annotations
import os
import time
from urllib.parse import urlsplit

METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
# Disable FastAPI's native automatic exporters. The shared middleware owns collection.
# Older FastAPI versions accept this as an unused extra constructor argument.
FASTAPI_TELEMETRY = {"tracing": False, "metrics": False, "logs": False, "operation_spans": False, "auto_configure": False}


def install_observability(app, service_name: str) -> bool:
    if getattr(app.state, "g_observability", None) is not None:
        raise RuntimeError("G observability is already installed")
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return False
    url = urlsplit(endpoint)
    if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("OTEL_EXPORTER_OTLP_ENDPOINT must be an HTTP(S) base URL without credentials or query")
    if not service_name or len(service_name) > 100:
        raise ValueError("A bounded service name is required")
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.metrics.view import View, ExplicitBucketHistogramAggregation
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    environment = os.getenv("G_DEPLOYMENT_ENVIRONMENT", "development")
    if environment not in {"development", "testing", "staging", "production"}:
        environment = "unknown"
    resource = Resource({"service.name": service_name, "deployment.environment.name": environment})
    ratio = float(os.getenv("G_TRACE_SAMPLE_RATIO", "0.1"))
    if not 0 <= ratio <= 1:
        raise ValueError("G_TRACE_SAMPLE_RATIO must be between 0 and 1")
    traces = TracerProvider(resource=resource, sampler=TraceIdRatioBased(ratio), shutdown_on_exit=False)
    traces.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces", timeout=2)))
    reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=endpoint.rstrip("/") + "/v1/metrics", timeout=2))
    metrics = MeterProvider(resource=resource, metric_readers=[reader], shutdown_on_exit=False,
                            views=[View(instrument_name="http.server.request.duration", aggregation=ExplicitBucketHistogramAggregation(
                                boundaries=(.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10)))])
    state = HttpTelemetry(traces, metrics)
    app.state.g_observability = state
    app.add_middleware(HttpTelemetryMiddleware, telemetry=state)
    return True


class HttpTelemetry:
    def __init__(self, traces, metrics):
        self.traces, self.metrics = traces, metrics
        self.tracer = traces.get_tracer("G.Factory.Http")
        self.duration = metrics.get_meter("G.Factory.Http").create_histogram("http.server.request.duration", unit="s")
        self.closed = False

    def flush(self):
        return self.traces.force_flush(3000) and self.metrics.force_flush(3000)

    def close(self):
        if not self.closed:
            self.closed = True
            self.traces.shutdown()
            self.metrics.shutdown(timeout_millis=3000)


class HttpTelemetryMiddleware:
    def __init__(self, app, telemetry):
        self.app, self.telemetry = app, telemetry

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            try:
                await self.app(scope, receive, send)
            finally:
                self.telemetry.close()
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        from opentelemetry.trace import Status, StatusCode, SpanKind
        started, status = time.perf_counter(), 500

        async def observed_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        with self.telemetry.tracer.start_as_current_span("HTTP request", kind=SpanKind.INTERNAL,
                                                        record_exception=False, set_status_on_exception=False) as span:
            try:
                await self.app(scope, receive, observed_send)
            except BaseException:
                status = 500
                raise
            finally:
                route = getattr(scope.get("route"), "path", None)
                route = route if isinstance(route, str) and len(route) <= 256 else "unmatched"
                method = scope.get("method")
                attributes = {"http.request.method": method if method in METHODS else "OTHER",
                              "http.route": route, "http.response.status_code": status}
                span.set_attributes(attributes)
                if status >= 500:
                    span.set_attribute("error.type", "server_error")
                    span.set_status(Status(StatusCode.ERROR))
                self.telemetry.duration.record(time.perf_counter() - started, attributes)
