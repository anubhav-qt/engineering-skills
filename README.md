**Engineering habits for your coding agent.** A Claude Code plugin
that makes the agent plan before it codes, ask you one decision at a
time, and prove its work before it says "done".

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Claude Code plugin](https://img.shields.io/badge/Claude%20Code-plugin-d97757.svg)](#install)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-3776ab.svg)

```
/plugin marketplace add anubhav-qt/engineering-skills
/plugin install engineering@anubhav-qt
```

## Why

Coding agents are fast, but left alone they:

- guess instead of checking;
- ask ten questions in one wall of text;
- write clever code nobody wants to read;
- say "done, all tests pass" when the tests would pass with the bug in.

These skills fix that with habits a careful engineer already has.
Every rule is written down as steps, and every exact step is a tested
script, so the agent follows them the same way every time.

## See it work

kickoff asks one question at a time, with its pick first:

```
How long may replies be?

  1. 5 lines at most. (Recommended)
  2. 15 lines at most.
  3. No limit.
  4. Type your own answer.
```

feature-test plants bugs in the code you just changed, one at a time, and checks
the tests catch each one. Here the tests looked fine, and still missed
two real mistakes:

```
SURVIVED  cart.py: off by one on the top limit
SURVIVED  cart.py: let small negative percents through
caught    cart.py: skip the first price
1 of 3 bugs caught
```

A survivor means a missing test. The agent writes it and runs again:

```
caught    cart.py: off by one on the top limit
caught    cart.py: let small negative percents through
caught    cart.py: skip the first price
3 of 3 bugs caught
```

Only then does it report back, with what it checked and what it skipped:

```
I proved apply_discount works with new tests in test_cart.py.
python3 -m unittest passes: normal prices, 0%, 100%, rounding, bad percents.
I planted small bugs in apply_discount one at a time; the tests caught every one.
I skipped the browser check because nothing on a screen changed.
I skipped speed checks because the function has no loop or slow work in it.
```

## Skills

| Skill | Command | What it does |
| --- | --- | --- |
| kickoff | `/engineering:kickoff` | Plans a new or existing project with you before any code is written, then sets up the files the agent needs. |
| feature-test | `/engineering:feature-test` | Proves one change works, checking only what it touches: tests, browser checks, profiling, then planted bugs to check the tests catch real mistakes. |
| full-test | `/engineering:full-test` | Tests the whole PR just before it is sent: every CI check in a clean copy merged onto the latest target branch, the few user journeys it could break, and a review of the whole diff. |

### kickoff

Run it at the start of a project, or in an existing repo. It:

- reads the code first, so it never asks what the repo already answers;
- asks you one quiz-style question at a time, each with a recommended
  answer and room for your own (what it is, who uses it, scale,
  self-hosted or managed services, UI, how long replies should be, and
  whatever else your project needs);
- writes `AGENTS.md` with working rules for the agent, plus a one-line
  `CLAUDE.md` that imports it;
- writes `docs/plan.md`, `docs/todo.md`, ADRs for big decisions in
  `docs/adr/`, and a `.claude/skills/` folder for your project's own
  skills;
- never overwrites a file. If you already have rules, it shows what
  clashes and lets you pick, one clash at a time;
- stops before writing any code, until you say go.

It runs only when you call it.

### feature-test

The agent runs it on its own when it finishes a change, or you call it.
It checks only what the change touches, so it stays fast. It:

- reads the diff and works out what a user can now do;
- makes sure tests cover it, testing behavior rather than internals, with
  real dependencies where it can; for a bug fix, it writes the failing
  test first and watches it fail;
- runs only the tests related to the change (the whole suite when config,
  dependencies or shared code changed), and fixes the code, never the test;
- for anything on screen, clicks through every changed input and button
  in the browser with edge cases (empty, too long, odd characters,
  double clicks, disabled states, keyboard only, phone width);
- profiles when the change can make things slower;
- plants small bugs in the changed code one at a time, with a script that
  always puts the file back, and adds tests for any bug that slips
  through;
- reports each check with the command that proved it, and marks anything
  it could not run as "not checked yet".

The rules come from the author's own practice plus published advice on
testing, flaky tests, profiling, and mutation testing (including Google's
work on running mutation testing on changed code only).

### full-test

The agent runs it right before it opens or updates a PR, or you call it.
It:

- makes a throwaway copy of the PR merged onto the latest target branch
  (whatever the PR merges into, not always `main`), with your uncommitted
  changes, so your folder is never touched and ignored files like `.env`
  cannot make a check pass by accident;
- reads your CI config and runs the same checks, cheapest first: clean
  install from the lockfile, lint, type check, production build, the
  full test suite, and migrations on a throwaway database if they changed;
- runs every check even after one fails, so one run shows every problem;
- fixes obvious failures itself (lint, types, a broken import) and brings
  you only real decisions;
- runs a failing check on the target branch too, so old problems never
  block your PR, and reruns a failing test on the same code to tell
  flaky from broken, never retrying until green;
- walks only the few user journeys this PR could break, in the browser;
- scans the whole diff for debug leftovers, focused or skipped tests,
  conflict markers, secrets (shown cut short), env and key files.

The rules come from published advice on pre-merge checks, merge skew,
test selection, flaky tests and self-review.

## Install

In Claude Code, run these two commands:

```
/plugin marketplace add anubhav-qt/engineering-skills
/plugin install engineering@anubhav-qt
```

Or from a terminal:

```bash
claude plugin marketplace add anubhav-qt/engineering-skills
```

```bash
claude plugin install engineering@anubhav-qt
```

To try a local copy without installing:

```bash
claude --plugin-dir path/to/engineering-skills
```

The scripts need Python 3.9 or newer, standard library only.

## How the skills are built

Each skill follows the same rules it teaches:

- `SKILL.md` stays short: the steps and the gotchas only.
- Exact, repeatable steps live as code in `scripts/`, with tests.
- Long guidance lives in `references/`, read only when needed.
- Templates live in `assets/`.

```
skills/
  kickoff/        SKILL.md, scripts/, references/, assets/
  feature-test/   SKILL.md, scripts/, references/
  full-test/      SKILL.md, scripts/, references/
tests/       unit tests for the scripts
```

## Development

Run the tests from the repo root:

```bash
python3 -m unittest discover tests
```

Check the plugin:

```bash
claude plugin validate .
```

## License

MIT. See [LICENSE](LICENSE).
