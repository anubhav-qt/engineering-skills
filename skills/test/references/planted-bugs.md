# Planting bugs

A planted bug is a small, real mistake put into the code on purpose. If
the tests still pass with it in, they would not catch that mistake for
real either.

## Choosing bugs

Plant bugs only in the code that changed. One bug per line at most. Pick
mistakes a person could really make:

- Flip a condition: `<` to `<=`, `==` to `!=`, `and` to `or`.
- Off by one: `+ 1` to `+ 2`, `range(n)` to `range(n - 1)`.
- Drop a line: remove a `return`, a `save()`, a check, a call.
- Wrong value: `True` to `False`, an empty string, `None`, `0`.
- Skip a branch: `if x:` to `if False:`.

Each bug in the file must change exactly one piece of text that appears
only once in that file. Include enough of the line to make it unique.

## The bugs file

A JSON list. `file` is relative to `--root`. `why` is a short note shown
in the report.

```json
[
  {
    "file": "src/cart.py",
    "find": "if quantity > stock:",
    "replace": "if quantity >= stock:",
    "why": "off by one on stock limit"
  }
]
```

Keep the bugs file outside the project, or delete it after.

## Running it

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/plant_bugs.py" \
  --bugs <bugs.json> --test "<test command>" --root <project folder>
```

It runs the tests once with no bug (and stops if they fail), then once
per bug, and always puts the file back. A test run that hangs counts as
caught; the time limit is 10 times the clean run, at least 60 seconds,
or `--timeout <seconds>`.

Each line says `caught`, `SURVIVED` or `unusable`:

- `SURVIVED`: add a test that catches it, then run again.
  If the bug truly changes nothing (the code behaves the same either
  way), say so in the report instead.
- `unusable`: the find text matched zero or several times. Fix the entry.

## The project's own mutation tool

If the project already has a mutation testing tool set up (mutmut,
Stryker, PIT, cargo-mutants or similar), also run it on the changed files
only, and treat its survivors the same way. Do not add one if it is not
there.
