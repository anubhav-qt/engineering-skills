"""JSON logs with Python's built-in logging: one line per event.

Copy this file into the project (for example app/json_logging.py) when
the project has no logger yet. It needs only the standard library.

    from app.json_logging import setup_logging, request_event
    import logging

    setup_logging()  # once, at startup
    log = logging.getLogger(__name__)

    log.info("order.paid", extra={"order_id": order.id, "cents": total})

    with request_event(log, "job.invoice", invoice_id=invoice.id) as event:
        event["lines"] = len(lines)  # add fields as the work goes on

Each line is one JSON object: time (UTC), level, event, logger, the
fields from extra, and error details when there is an exception. Field
names that look secret are replaced with "[redacted]". JSON escapes line
breaks, so user input cannot forge a new line.
"""

import contextlib
import datetime
import json
import logging
import sys
import time

REDACTED = "[redacted]"
SECRET_KEYS = {
    "password", "passwd", "pwd", "passphrase", "secret", "token",
    "access_token", "refresh_token", "id_token", "api_key", "apikey",
    "authorization", "cookie", "set_cookie", "session", "session_id",
    "private_key", "card_number", "cvv", "ssn",
}

# Attributes every LogRecord has; anything else came from extra=.
STANDARD_ATTRIBUTES = set(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime"}

# Field names OpenTelemetry's logging instrumentation adds.
TRACE_ATTRIBUTES = {
    "otelTraceID": "trace_id",
    "otelSpanID": "span_id",
}
SKIPPED_ATTRIBUTES = {"otelServiceName", "otelTraceSampled"}


def is_secret_key(key):
    normalized = str(key).lower().replace("-", "_")
    return normalized in SECRET_KEYS


def redact(value):
    """Replace values under secret-looking keys, at any depth."""
    if isinstance(value, dict):
        cleaned = {}
        for key, inner in value.items():
            if is_secret_key(key):
                cleaned[key] = REDACTED
            else:
                cleaned[key] = redact(inner)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [redact(inner) for inner in value]
    return value


def utc_time(created):
    moment = datetime.datetime.fromtimestamp(created, tz=datetime.timezone.utc)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        try:
            return self.format_json(record)
        except Exception as error:  # a log line must never break the app
            fallback = {
                "time": utc_time(record.created),
                "level": record.levelname.lower(),
                "event": "log.format_failed",
                "error.type": type(error).__name__,
            }
            return json.dumps(fallback)

    def format_json(self, record):
        line = {
            "time": utc_time(record.created),
            "level": record.levelname.lower(),
            "event": record.getMessage(),
            "logger": record.name,
        }
        for key, value in record.__dict__.items():
            if key in STANDARD_ATTRIBUTES or key in SKIPPED_ATTRIBUTES:
                continue
            if key in TRACE_ATTRIBUTES:
                if value and value != "0":
                    line[TRACE_ATTRIBUTES[key]] = value
                continue
            if is_secret_key(key):
                line[key] = REDACTED
            else:
                line[key] = redact(value)
        if record.exc_info:
            error = record.exc_info[1]
            line["error.type"] = type(error).__name__
            line["error.stack"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str, ensure_ascii=False)


def setup_logging(level="INFO", stream=None):
    """Send every log to one JSON handler. Call once, at startup."""
    if stream is None:
        stream = sys.stdout
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    for old in list(root.handlers):
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(level)


@contextlib.contextmanager
def request_event(logger, name, **fields):
    """One summary event for a request or job, logged when it ends, even
    if it raises. Add fields to the yielded dict as the work goes on."""
    event = dict(fields)
    started = time.monotonic()
    try:
        yield event
    except Exception as error:
        event["outcome"] = "error"
        event["error.type"] = type(error).__name__
        event["duration_ms"] = round((time.monotonic() - started) * 1000, 1)
        logger.error(name, extra=event, exc_info=True)
        raise
    event["outcome"] = "ok"
    event["duration_ms"] = round((time.monotonic() - started) * 1000, 1)
    logger.info(name, extra=event)
