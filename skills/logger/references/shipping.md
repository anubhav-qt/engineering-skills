# Sampling, retention and shipping

Set these up, in the project's own config, for where the app runs. Ask
the human first before:

- creating any account (a log or tracing service);
- adding anything that costs money;
- changing settings on a deployed app or host.

Read the project's deploy files first (Dockerfile, compose file,
`fly.toml`, `vercel.json`, `render.yaml`, Kubernetes files, CI deploy
steps) to learn where it runs. If unclear, ask.

## Shipping (where logs and traces go)

- Containers and managed hosts: log to stdout; the platform collects
  it. Do not write log files there.
- Traces and metrics: OTLP to the endpoint in
  `OTEL_EXPORTER_OTLP_ENDPOINT`, either a vendor's endpoint or an
  OpenTelemetry Collector the project runs.
- Put endpoints and keys in the host's secret settings or environment,
  never in the repo. Add the variable names (no values) to the
  project's example env file.

## Retention (how long logs are kept)

- Files on a server: rotate them (logrotate, or the logger's rotating
  handler), with a size cap and a count cap.
- Docker: cap the log driver (`max-size`, `max-file`).
- Hosted services: set the retention period in the service; ask the
  human how long (a legal or business choice), suggest 30 days for
  application logs as a start.
- Logs that hold personal data must not live longer than the project's
  privacy rules allow.

## Sampling (keeping only some)

Logs:
- Keep every error, warning and security event.
- Summary events: keep all while volume is low. When volume or cost
  grows, keep all errors and slow requests, and a fixed share of the rest
  (tail sampling), decided once per request so a request is kept or
  dropped as a whole.
- Drop health check and load balancer pings first.

Traces:
- SDK, simple: `OTEL_TRACES_SAMPLER=parentbased_traceidratio` with
  `OTEL_TRACES_SAMPLER_ARG` as a share between 0 and 1 (for example
  `0.1`). Parent based means a request keeps its parent's decision.
- Collector, better: the `tail_sampling` processor (collector-contrib)
  decides after the trace ends. Policies: `status_code` (keep errors),
  `latency` (keep slow ones), `probabilistic` (a share of the rest).

Metrics are not sampled; they are already summed.

## Prove it

- Start the app with the real settings (or `console` exporters locally)
  and see one request arrive where it should.
- For a hosted service, check in its UI or API that the event, span and
  metric arrived, or mark it "not checked yet" in the report.
