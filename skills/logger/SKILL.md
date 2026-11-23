---
name: logger
description: Add logs, metrics and traces only where they help, the project's own way, and prove them. Places logs at errors, security events and one summary event per request or job; keeps secrets and noise out; adds metrics and tracing to deployed apps or ones that call other services; sets up sampling, retention and shipping; then tests every key log, span and metric and proves fake secrets never reach the logs. Use when a change adds a request handler, job, error path, login or outside call, when code has no useful logs, when logs are noisy or leak data, or when the human asks for logging, metrics, tracing or observability.
---

# Logger

A log earns its place when someone would act on it, or would need it to
find a cause later. Everything else is noise, and noise hides the lines
that matter.

This skill covers only the code the change touches. It looks at the
whole app only when the human asks, or when the app has no logging at
all.

## Steps

1. Read first. Find the project's logger, its setup, field names, how
   errors are handled, and any metrics or tracing tool already there.
   Follow them; never add a second logger. List what the change adds so
   far:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/find_log_calls.py" --repo <project folder> [--base <target branch>]
   ```

2. No logger yet: use the language's built-in one (`references/stacks.md`).
   Ask the human before adding any package.

3. Decide where logs go, as `references/where-to-log.md` says: handled
   errors (once, where handled), the security events, one summary event
   per request or job, slow outside calls. Nothing else.

4. Write them as `references/how-to-log.md` says: a constant event name,
   values in fields, the right level, a request id, redaction in one
   place, and logging that can never break the request.

5. Browser code ships with no `console` calls. Send errors to an error
   tracker only if the project already has one.

6. Metrics and tracing, only if the app is deployed or calls other
   services, as `references/metrics-tracing.md` says: the project's tool,
   else OpenTelemetry; auto instrumentation, a few hand spans, and the
   rate, errors and duration metrics.

7. Set up sampling, retention and shipping, as `references/shipping.md`
   says. Ask before creating any account, adding a paid service, or
   changing a deployed app's settings.

8. Remove noise in the files the change touches: bare prints, step by
   step lines, the same error logged twice. List noise in other files
   in `docs/todo.md`; do not touch it.

9. Test them, as `references/testing.md` says: each key log fires with
   the right level and fields; each key span and metric is recorded.
   Then prove fake secrets stay out:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/check_log_leaks.py" --print-canaries
   python3 "${CLAUDE_SKILL_DIR}/scripts/check_log_leaks.py" --root <project folder> \
     --command "<test or journey>" --expect "<event name>" [--log-file <path>]
   ```

10. Run the real app, go through the changed flow, and read the actual
    lines, spans and metrics it gives out. A test can pass while the
    real output is empty or unreadable.

11. Run `find_log_calls.py` again until it prints "nothing flagged".
    A command-line tool's prints are its real output: put the comment
    `logger: cli` once in that file. Mark any other line `logger: keep`
    only when it truly must stay, and say why in the report.

12. Hand off to feature-test to prove the change works as a whole.

13. Report to the human, within the reply length the project asks for:
    - what was added, removed and set up, and why each log earns its place;
    - the test and the leak check that prove it, with what they printed;
    - what needs the human (an account, a paid service, a deployed setting);
    - anything not run, marked "not checked yet".

## Gotchas

- Logging an error and then rethrowing it logs it twice. Log where it is
  handled, or rethrow; never both.
- A catch that neither logs nor rethrows hides the error. Never swallow.
- A message built from values (`f"paid {id}"`) cannot be searched or
  counted, and lets user input forge lines. Constant message, values in
  fields.
- Whole request or response bodies and whole objects carry personal
  data along with them. Log ids, not objects.
- User ids and raw URLs go in logs and spans, never in metric labels:
  every new label value costs memory, and past the limit alerts go
  quietly wrong.
- A check that sees no logs at all passes for the wrong reason. The leak
  check needs `--expect`; a log test must also assert the line is there.
- Pick an `--expect` text that only the app's logs print, not the test
  runner's own output.
- Log tests (`caplog`, `assertLogs`) catch records before they are
  written, so they print nothing. The leak check needs a run where the
  app's real log setup writes out: a journey script or the started app.
