---
name: full-test
description: Test the whole PR just before it is sent. In a throwaway copy merged onto the latest target branch, runs every check CI runs (clean install, lint, type check, production build, the full test suite), walks the few user journeys the PR could break, and self-reviews the whole diff. Fixes obvious failures itself and brings only real decisions to the human. Use right before opening or updating a pull request, or when the human asks to check the whole branch or PR.
---

# Full test

Runs once per PR, after each feature was proven on its own with
feature-test. It answers one question: is this PR safe to send?

## Steps

1. Make the copy. It finds the branch the PR merges into (the open PR's
   base, else the remote's default branch), fetches it, and merges the
   PR onto it with your uncommitted changes. Your folder is not touched.

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/pr_copy.py" setup --repo <project folder>
   ```

   Add `--target <branch>` if you know it better. Exit 1 means the PR
   does not merge cleanly: stop and bring the conflict to the human.

2. Find the checks CI runs and write them to `<folder>/checks.json`, as
   `references/checks.md` says. Order: clean install, lint and format,
   type check, production build, full test suite, then migrations if the
   PR changed any.

3. Run every check in the `pr` copy:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/run_checks.py" \
     --checks <folder>/checks.json --root <folder>/pr --log-dir <folder>/logs
   ```

4. Sort each failure, as `references/checks.md` says:
   - already failing on the target branch: note it, do not fix it;
   - flaky: report it as a bug, never retry it to green;
   - obvious (lint, format, a type error, a syntax error, a broken import,
     a test the PR plainly broke): fix it in the human's folder, never in
     the copy, then `pr_copy.py refresh <folder>` and rerun that check;
   - anything else needs the human: do not fix it.

5. If the PR changes what a user sees or does, walk the fewest journeys
   it could break, as `references/journeys.md` says. Otherwise skip this
   and say why.

6. Self-review the whole diff, as `references/self-review.md` says:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/scan_diff.py" \
     --repo <project folder> --base <target printed by setup>
   ```

7. If you fixed anything, refresh the copy and run every check once more.

8. Remove the copy, also when you stop early:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/pr_copy.py" cleanup <folder>
   ```

9. Report to the human, within the reply length the project asks for:
   - whether every check passed, with the commands;
   - what you fixed yourself, in a few words;
   - uncommitted files setup listed, which must be committed before sending;
   - each decision the human must make, one at a time;
   - anything not run, marked "not checked yet".

## Gotchas

- Fix code in the human's folder. The copy is thrown away, and so is any
  fix made in it.
- The copy has no installed packages and no ignored files like `.env`.
  That is the point: install from the lockfile there. If a check needs
  env values, use the project's example or test values; if it needs real
  ones, ask the human.
- Never skip, loosen or delete a test, never skip hooks (`--no-verify`),
  never turn a lint rule off, and never retry until green.
- Old lint or type problems already on the target branch do not block
  the PR. Only problems this PR adds do.
- Browser journeys cost the most time. Pick only the ones this PR could
  break and that matter most.
- No planted bugs here: feature-test plants them in each feature.
