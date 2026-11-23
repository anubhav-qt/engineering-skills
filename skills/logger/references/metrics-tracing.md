# Metrics and tracing

Only for apps that are deployed, or that call other services. A local
script or tool gets logs only.

Use the project's tool if it has one (Datadog, Prometheus client, Sentry
performance, ...). Otherwise use OpenTelemetry: free, vendor neutral,
one SDK for logs, metrics and traces.

## What to add

1. Auto (zero-code) instrumentation. It covers the edges: the web
   framework, HTTP clients, database drivers.
   - Python: `pip install opentelemetry-distro opentelemetry-exporter-otlp`,
     then `opentelemetry-bootstrap -a install`, then run the app as
     `opentelemetry-instrument python app.py`.
   - Node: `npm install @opentelemetry/api @opentelemetry/auto-instrumentations-node`,
     then `node --require @opentelemetry/auto-instrumentations-node/register app.js`
     (or put the `--require` in `NODE_OPTIONS`).
   - Go: no zero-code SDK; wrap handlers with
     `otelhttp.NewHandler(handler, "name")` from
     `go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp`.
   These add packages: ask the human first.

2. A few hand spans, only for the app's own key steps that auto
   instrumentation cannot see: a pricing calculation, a batch stage, a
   queue job. Not for every function.
   - Name: a low cardinality action, `checkout.price_cart`, never with
     ids inside the name.
   - Kind: server and client for calls, producer and consumer for
     queues, internal for in-process work.
   - Attributes: set them when the span starts; ids go here.
   - Status: leave unset on success; set error on failure and record
     the exception.

3. The three RED metrics per entry point (most come free with auto
   instrumentation; add by hand only what is missing):
   - rate: a counter of requests or jobs;
   - errors: the same counter with an outcome attribute, or its own;
   - duration: a histogram named `{operation}.duration`.
   Naming: lowercase, dot separated; reuse the OpenTelemetry semantic
   conventions before inventing; prefix custom names with the app's
   name; no `_total` suffix.

## Cardinality (the trap)

Every unique mix of metric attributes costs memory. The SDK keeps 2000
per metric by default, then folds the rest into one overflow point
(`otel.metric.overflow=true`). Totals stay right, but filters on a
dropped attribute undercount, so an error alert can quietly stop firing.

- Metric attributes: route templates (`/orders/{id}`), method, status
  class, outcome. Small, fixed sets.
- Never: user ids, raw URLs, emails, request ids. Those go in logs and
  span attributes.

## Logs and traces together

- Python: `opentelemetry-instrumentation-logging`; set
  `OTEL_PYTHON_LOG_CORRELATION=true` and records get `otelTraceID` and
  `otelSpanID` (the asset logger renames them to `trace_id`, `span_id`).
- Node with pino: `@opentelemetry/instrumentation-pino` adds `trace_id`,
  `span_id`, `trace_flags`.
- When a trace id exists, the summary event carries it, so a log line
  leads straight to its trace.

## Settings (environment, read by every SDK)

- `OTEL_SERVICE_NAME`: always set it (default is `unknown_service`).
- `OTEL_EXPORTER_OTLP_ENDPOINT`: where to send; default
  `http://localhost:4317` (gRPC) or `http://localhost:4318` (HTTP).
- `OTEL_TRACES_EXPORTER`, `OTEL_METRICS_EXPORTER`, `OTEL_LOGS_EXPORTER`:
  `otlp` (default), `console`, or `none`. Use `console` to look at the
  output locally.
- Sampling: see `shipping.md`.
