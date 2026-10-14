# G shared HTTP observability dependency

Canonical source owner: G-Factory, existing `OPS-OBS`; this is a generated source dependency.
Configure `OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318` (HTTP/protobuf base URL).
Leave the endpoint unset to disable collection. Install Python optional requirements before enabling it.
`G_TRACE_SAMPLE_RATIO` defaults to 0.1, must be in [0,1]; metrics count all observed requests.
Only service name, environment, method, source route template, status, duration and constant error type are collected.
No bodies, query strings, identities, tenant IDs, auth headers, exception text or application logs are collected.
This is server HTTP timing, not CPU profiling, audit history, business reporting or an authorization boundary.
Use a private collector/gateway with reviewed access, TLS, retention and operational limits for deployment.
Consumer native build and provider acceptance are separate gates; local probes use synthetic data.
