# How to write a log line

## Shape

- One JSON object per line (or the project's existing format).
- A constant event name as the message: `order.paid`, `user.login`,
  `payment.failed`. Lowercase, dot separated, noun then past verb.
- Values in fields, never in the message. `f"paid {id}"` cannot be
  searched or counted, and lets user input forge a line.
- Stable field names, reused across the app: `user_id`, `order_id`,
  `duration_ms`, `outcome`, `error.type`. Follow the project's names
  when it has them (camelCase in JS projects is fine; stay consistent).
- Times in UTC, ISO 8601, milliseconds.

## Fields every line should carry (when known)

- `request_id` (or `trace_id` when tracing is on);
- `user_id` (an id, never an email or name);
- `service` and `version` (set once in the logger's base fields);
- for errors: `error.type`, `error.code`, and the stack at error level.

## Request id

- Make it at the edge: the first middleware. Reuse an incoming
  `X-Request-Id` (or `traceparent` when tracing) only from a trusted
  proxy.
- Put it on every log of that request (a child logger or context var).
- Send it to every outside call, and return it in error replies so a
  user's report can be matched to the logs.

## Keeping secrets out

Never log: passwords, tokens, API keys, session ids, cookies, the
Authorization header, connection strings, private keys, card numbers,
CVV, government ids, health data.

- Redact in one place: the logger's setup (both files in `assets/` do
  this by field name). A rule at every call gets forgotten.
- Log ids, not objects. A whole user, request or response object drags
  personal data along with it.
- Emails, names, phones, addresses: only when the event truly needs
  them, and mask them (`l***@example.com`).
- Hash a session id if two lines must be linked by it.
- The leak check (`check_log_leaks.py`) proves the redaction works.

## Logging must never hurt the app

- A failure to build or write a line must never fail the request
  (both asset loggers fall back to a `log.format_failed` line).
- No logging per item in hot loops; count and log once.
- Bounded size: no unbounded lists or bodies in a field. Cut long
  strings (for example to 1,000 characters).
- Logs go to stdout in containers and managed hosts; files only when the
  project already writes files (then rotation is needed, see
  `shipping.md`).

## Log injection

User input with a line break can fake a whole log line. JSON lines
escape it. In a plain text format, replace `\r` and `\n` in every value
before logging. Parameterized calls alone do not stop it.

## Frontend

- No `console.*` in shipped browser code: anyone can open the console,
  and it is noise.
- Errors go to the project's error tracker only if one is already set
  up. Do not add one without asking.
- Development-only output must be stripped from the production build,
  not just hidden.
