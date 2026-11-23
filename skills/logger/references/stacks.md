# Per stack notes

Always use the project's logger first. These notes are for when there
is none. Ask the human before adding any package.

## Python

Built in: `logging`. It has no JSON output of its own, so copy
`assets/json_logging.py` into the project. It gives `setup_logging()`
(call once at startup) and `request_event()` (one summary event for a
request or job).

```python
log = logging.getLogger(__name__)
log.info("order.paid", extra={"order_id": order.id})
log.exception("payment.failed", extra={"order_id": order.id})  # inside except
```

- Pass values in `extra=`, never in the message.
- `extra` keys must not clash with LogRecord's own attributes (`name`,
  `message`, `args`, `msg`, `levelname` ...): logging raises an error.
- With trace correlation on (see `metrics-tracing.md`), the asset turns
  `otelTraceID` and `otelSpanID` into `trace_id` and `span_id`.
- If the project already uses structlog or loguru, use it instead.

## Node.js and TypeScript

Node has no structured logger built in; `console` is plain text. Two
options, ask the human which:

1. No package: copy `assets/logger.mjs`. It gives `createLogger()`,
   `child()` and `startEvent()` (one summary event per request or job).
2. pino, the common choice. With OpenTelemetry,
   `@opentelemetry/instrumentation-pino` adds `trace_id`, `span_id` and
   `trace_flags` to each line.

```js
log.info('order.paid', { orderId: order.id });          // assets/logger.mjs
logger.info({ orderId: order.id }, 'order.paid');       // pino: fields first
```

- Express, Fastify and similar: start the summary event in the first
  middleware, end it on the response's `finish` event (or in a
  `finally` around the handler).

## Go

Built in: `log/slog` (Go 1.21 and later).

```go
logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
    ReplaceAttr: redactSecrets, // func(groups []string, a slog.Attr) slog.Attr
}))
slog.SetDefault(logger)
logger.InfoContext(ctx, "order.paid", "order_id", id, "cents", total)
```

- Values as key and value pairs, never `fmt.Sprintf` in the message.
- `logger.With("request_id", id)` for a request's child logger.
- Not checked yet on this machine (Go is not installed); names checked
  in the Go source on 2026-11-23.

## Browser

No logger: see the frontend part of `how-to-log.md`.

## Other languages

Use the language's standard structured logger, or the project's. The
rules in `how-to-log.md` hold for every language. `find_log_calls.py`
reads only Python, JS/TS and Go; for others, review the diff by hand.
