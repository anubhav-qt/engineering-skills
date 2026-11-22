---
name: debug
description: Find and fix the real cause of a bug. Reproduces it first, shrinks it, tests one hypothesis at a time against evidence, bisects when it used to work, fixes the cause instead of the symptom, and keeps a test that fails without the fix. Use when something is broken, a test fails, an error or crash shows up, behavior is wrong or only fails sometimes, or the human asks to debug or fix a bug.
---

# Debug

A plausible story is not a cause. The cause is proven when a check that
could have shown it wrong did not, and the fix makes a failing test pass.

## Steps

1. Reproduce it: one command that shows the bug. Run it and watch it
   fail. If it fails only sometimes, run it in a loop:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/repeat_until_fail.py" \
     --command "<command>" --root <project folder>
   ```

   If you cannot reproduce it, or it fails only in production, follow
   `references/reproduce.md`. Never call a bug fixed you never saw fail.

2. Shrink it: the smallest input and fewest steps that still fail, as
   `references/reproduce.md` says.

3. Look before you guess. Read the whole error, the stack trace and the
   logs. Check the plug: versions, config, env values, caches, stale
   builds (the list is in `references/hypotheses.md`).

4. If it used to work, find the commit that broke it:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/find_bad_commit.py" --repo <project folder> \
     --good <commit that worked> --test "<command>" [--setup "<install>"]
   ```

   It runs in a throwaway copy. Keep the test outside the repo, as
   `references/bisect.md` says.

5. Test one hypothesis at a time, as `references/hypotheses.md` says:
   say what you expect to see if it is true, then run the check that
   could prove it wrong. Change one thing at a time, and undo changes
   that did not help. Keep a short list in the chat of what you tried
   and what it showed, so nothing is tried twice.

   Tag every temporary print or log with `DEBUG-TEMP` in a comment on
   the same line.

6. Find the cause: keep asking "why" until the answer is something you
   can fix and that explains every symptom. Then search the code for
   the same mistake elsewhere.

7. Write a test for it that fails now, for the right reason (the
   cause, not a typo or a missing import). Watch it fail.

8. Fix the cause, not the symptom.
   - If the fix is local and small, fix it.
   - If it changes the design, an API, stored data, or many files,
     explain the cause and the fix and ask the human first.
   - After three failed fixes, stop. The design may be wrong; bring
     what you learned to the human instead of trying a fourth.

9. Prove the fix: the test passes. Undo the fix, watch the test fail,
   then put the fix back. For a bug that failed only sometimes, run
   `repeat_until_fail.py` with `--times` at least 5 times the runs it
   took to fail before (and at least 50).

10. Remove every temporary line, until this prints "none left":

    ```bash
    python3 "${CLAUDE_SKILL_DIR}/scripts/check_debug_prints.py" --repo <project folder>
    ```

11. Hand off to feature-test to prove the change works as a whole.

12. Report to the human, within the reply length the project asks for:
    - the cause, and the evidence that proves it;
    - the fix, and the test that fails without it;
    - the same mistake found elsewhere, if any;
    - anything not run, marked "not checked yet".

## Gotchas

- Never "fix" an intermittent bug with a sleep, a retry, a bigger
  timeout or a skipped test. That hides it.
- Never edit, loosen or delete a test to make it pass, unless the test
  itself is wrong, and then say so.
- Catching and swallowing the error, or adding a null check where the
  value should never be null, patches the symptom.
- Evidence must be able to prove you wrong. A log that would print the
  same either way proves nothing.
- Adding prints can change timing and hide a race. If the bug goes away
  when you watch it, suspect timing.
- Your last failed attempt pulls you toward small tweaks of it. After a
  failed fix, go back to the evidence, not the last error message.
