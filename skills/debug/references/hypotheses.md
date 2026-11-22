# Testing hypotheses

## Check the plug first

Cheap things that cause expensive hunts:

- Is the code you are reading the code that runs? Stale build, old
  bundle, cached file, wrong branch, server not restarted.
- Versions: language, packages, lockfile vs installed, OS, browser.
- Config and env values: missing, wrong file loaded, wrong environment.
- Data: empty, very large, odd characters, wrong time zone, duplicates.
- The obvious: typo in a name, wrong path, wrong port, permission denied.

## One hypothesis at a time

1. State it in one line: "X happens because Y."
2. Predict: "If Y is true, then running Z will show W."
3. Pick a check that could show it wrong. If Z would show W either way,
   it proves nothing; pick another check.
4. Run it. Read the result as it is, not as you hoped.
5. Note it in the chat: hypothesis, check, result, kept or dropped.

Good checks: a debugger breakpoint, an assert, printing the one value
that differs between the hypotheses, a test with one input changed,
reading the library's source.

## Divide and conquer

When there is no good hypothesis, halve the search space:

- In time: bisect commits (`references/bisect.md`).
- In code: check the value halfway along the path. Is it already wrong
  there? Then the bug is earlier; if not, later.
- In data: halve the input (`references/reproduce.md`).

## Cause or symptom

Keep asking "why" until the answer is the place where the code first
does the wrong thing. Signs you are still at a symptom:

- The fix catches an error, adds a null check, clamps a value or adds a
  special case for one input, but you cannot say why the bad value came.
- The fix is in a different place from where the wrong value is made.
- The explanation does not cover every symptom seen.

## Three failed fixes

After three fixes that did not work, stop. Signs the design is wrong:
each fix shows a new problem somewhere else, fixes need shared state or
more coupling, or the fix keeps growing. Bring the human what you tried,
what each showed, and the design question.
