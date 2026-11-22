---
name: test
description: Prove a code change works before calling it done. Tests it end to end, tries every changed input and button in the browser, profiles when speed matters, then plants bugs one at a time to check the tests catch them. Use when finishing a feature or bug fix, or when the human asks to test, verify or prove something works.
---

# Test

"Done" means proven, not believed. Every claim in the final report comes
with the command that showed it and what that command printed.

## Steps

1. Find what changed. Read the diff (`git diff`, plus new files) and work
   out what a user can now do, or what bug is now gone.

2. Make sure tests cover it, following `references/testing.md`. For a bug
   fix, the new test must fail on the old code first. Watch it fail.

3. Run the whole test suite, not only the new tests. If something fails,
   fix the code, never the test (unless the test itself is wrong, and then
   say so in the report).

4. If anything a user sees changed, test it in the browser as
   `references/ui.md` says: every changed input and button, every edge
   case.

5. If the change touches a loop, a query, big data, startup, or anything
   on a hot path, profile it as `references/profiling.md` says. Otherwise
   skip it and say why in the report.

6. Plant bugs in the changed code, one at a time, as
   `references/planted-bugs.md` says:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/plant_bugs.py" \
     --bugs <bugs.json> --test "<test command>" --root <project folder>
   ```

   Every bug must be caught. For each survivor, add the missing test and
   run the script again, or explain why that bug changes nothing.

7. Report to the human, within the reply length the project asks for:
   - what was checked, with the command and its result for each;
   - what was skipped and why;
   - anything not run, marked "not checked yet".

## Gotchas

- Never edit, skip, loosen or delete a test to make it pass, and never
  special-case test inputs in the code. If a test is wrong, say so.
- A test you never saw fail proves nothing. Planting bugs is how you see
  it fail.
- "Tests pass" is a claim. The command and its output are the proof.
- If the tests already fail before you start, stop and tell the human;
  the planted-bug script will refuse to run anyway.
- If the script says an earlier run did not finish, a file may still hold
  a planted bug. Compare it with the `.plant-bugs.bak` file next to it,
  restore it if needed, delete the backup, then go on.
