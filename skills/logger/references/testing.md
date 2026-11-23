# Testing logs, spans and metrics

A key log is one someone would act on: errors, security events, the
summary event. Each gets a test. Assert on fields and level, never on
the exact text of a line.

Every test must also prove the line is there. A test that only checks
"no secret in the logs" passes when nothing was logged at all.

## Logs

- Python (pytest): the `caplog` fixture. Set the level explicitly, then
  assert on `caplog.records`:

  ```python
  def test_failed_payment_is_logged(caplog):
      caplog.set_level(logging.INFO, logger="shop")
      pay(order_with_declined_card)
      [record] = [r for r in caplog.records if r.getMessage() == "payment.failed"]
      assert record.levelname == "ERROR"
      assert record.order_id == 7
  ```

  With unittest: `self.assertLogs("shop", level="INFO")`.
- Node: give the logger a write function (`assets/logger.mjs` takes
  `options.write`) or, for pino, a destination stream (`pino-test` is
  made for this), then parse each JSON line and assert on fields.
- Go: build the `slog` logger on a `bytes.Buffer`, then decode each
  JSON line.
- Test the error path too: make the outside call fail (fake or stub at
  the boundary) and assert the error is logged once, not twice.

## Spans and metrics

Use in-memory exporters, so the test reads what would have been sent.

- Python:
  - spans: `InMemorySpanExporter` from
    `opentelemetry.sdk.trace.export.in_memory_span_exporter`, behind a
    `SimpleSpanProcessor`; read with `get_finished_spans()`.
  - metrics: `InMemoryMetricReader` from
    `opentelemetry.sdk.metrics.export`; read with `get_metrics_data()`.
- Node:
  - spans: `InMemorySpanExporter` from `@opentelemetry/sdk-trace-base`;
    read with `getFinishedSpans()`.
  - metrics: `InMemoryMetricExporter` from `@opentelemetry/sdk-metrics`
    (takes an aggregation temporality); read with `getMetrics()`.
- Go:
  - spans: `tracetest.NewInMemoryExporter()` from
    `go.opentelemetry.io/otel/sdk/trace/tracetest`; read with
    `GetSpans()`.
  - metrics: `metric.NewManualReader()` from
    `go.opentelemetry.io/otel/sdk/metric`; read with `Collect(ctx, &rm)`.

Assert: the span exists with the right name, kind, key attributes and
error status on failure; the metric exists with the right name and
attributes, and its count went up by the expected amount. Also assert no
metric attribute holds an id or raw URL.

## The leak check

1. `check_log_leaks.py --print-canaries` prints fake values: a password,
   a token, an API key, an email and a card number.
2. Write a test or journey that pushes them through the changed code: a
   login with the fake password, a request with the fake token in the
   Authorization header, a signup with the fake email, a payment form
   with the fake card. The script also sets them as `LOG_CANARY_*`
   environment values, so the test can read them from there.
3. Run it with `--command` and `--expect` (an event name the run logs).
   Add `--log-file` for each file the app writes logs to.
4. Exit 0 is clean. Exit 1 shows every line that leaked. Exit 2 means
   the check proved nothing (the command failed, hung, or `--expect`
   never showed up): fix that, never ignore it.

The email may appear on purpose when an event truly needs it; then it
must be masked, and the check proves the mask works.

## The real run

Tests can pass while the real output is wrong. Start the app the way it
runs for real, go through the changed flow once, and read:

- the actual log lines: one summary event, readable fields, no secrets;
- with metrics and tracing: run with `OTEL_TRACES_EXPORTER=console` and
  `OTEL_METRICS_EXPORTER=console` (or the project's local setup) and see
  the spans and metrics appear.
