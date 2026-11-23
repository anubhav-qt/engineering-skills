# Where a log earns its place

Ask of every log: who acts on it, or what cause would it help find? If
nobody and nothing, leave it out.

## Always

1. Handled errors, once, where they are handled. Not at every layer the
   error passes through. A catch either logs and handles, or rethrows.
2. Failures of outside calls: database, payment, email, other services,
   with the call's name, duration and error code.
3. Security events (from the OWASP Logging Cheat Sheet):
   - login success and failure, logout, password reset, MFA changes;
   - access denied, and requests with a bad or tampered token or session;
   - input that fails validation on the server;
   - admin actions and role or permission changes;
   - access to sensitive data, export and import, file uploads;
   - consent given or withdrawn;
   - odd business steps: out of order, or trying to go past a limit.
4. Startup and shutdown: version, config source (never config values),
   and whether logging itself started.

## One summary event per request or job

Instead of many lines along the way, gather fields as the work goes and
log once when it ends (a "wide event" or "canonical log line"):

- built in middleware or a wrapper, so every request gets one;
- handlers only add fields: ids of what was touched, business context
  (plan, tier, amount), counts (rows, retries), the decision taken;
- logged in a `finally`, so it goes out even when the work throws;
- long jobs: one event per job, or one per stage if stages take minutes.

Health checks and load balancer pings get no event, or a sampled one.

## Slow paths

Log a warning when an outside call or a known heavy step passes a
threshold the project cares about, with its duration. If metrics are set
up, the duration histogram already covers the normal case; the log is
for the outliers.

## Never

- "entering function" or "step 3 done" lines;
- inside loops that run per item, row or message (count instead, and put
  the count on the summary event);
- the same failure at several layers;
- user actions that are product analytics, not operations;
- whole request or response bodies, or whole objects.

## Levels

- error: someone should act. If nobody would act, it is not an error.
- warn: unexpected, but the work still finished (a retry worked, a
  fallback was used, a slow call).
- info: the summary event, startup and shutdown, security events that
  went fine (a login).
- debug: detail for local work; off in production by default.

Security failures (access denied, bad token) are warn, or error if the
project alerts on them. Follow the project's own levels when it has them.
