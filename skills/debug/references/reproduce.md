# Reproducing a bug

## One command

The reproduction is one command anyone can run that fails because of the
bug. Best is a test in the project's test runner. Next best is a small
script that exits non-zero when the bug shows.

Write down what "wrong" looks like before running it: the exact error,
the wrong value, or the missing output. Then run it and compare.

## Shrink it

Smaller reproductions point at the cause and run faster.

- Cut the input in half. If it still fails, keep the half; if not, try
  the other half. Repeat until nothing more can go.
- Remove steps, options, data rows and code paths one at a time.
- Swap real services for the smallest real thing that still fails (a
  local database, a fixture file). Do not mock away the part that fails.
- Stop when removing any one more thing makes the bug go away.

## Only fails sometimes

- Loop it with `repeat_until_fail.py`. Note the run it failed on: that
  is roughly how rare it is.
- Make it fail more often: run tests in a random or reversed order, run
  in parallel, add load (CPU, memory, many requests), shorten timeouts,
  use the language's race detector (`go test -race`, ThreadSanitizer).
- Look for shared state first: globals, caches, files, ports, the clock,
  random seeds, test order, network calls.
- Prints can change timing and hide a race. Prefer counters or recording
  to memory, printed at the end.

## Cannot reproduce

Usually the difference is in the environment, not the code. Compare:
versions (language, packages, OS, browser), config and env values, data
(size, odd characters, empty values), time (zone, date, daylight
saving), load and concurrency, permissions, network.

When it happens only in production:

- Read what exists first: logs, traces, error reports, metrics around
  the time it happened.
- Never change production to experiment. Never touch real user data.
- Ask the human for what you cannot see: the exact input, the request,
  the user's steps, a log export.
- If more data is needed, add a few targeted log lines that would tell
  your hypotheses apart, and ask the human to ship them. These are not
  `DEBUG-TEMP` lines: write them as proper logs worth keeping.
- If it still cannot be reproduced, say so. Do not call it fixed; say
  what was changed, why it should help, and how to confirm it.
