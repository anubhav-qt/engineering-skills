---
name: kickoff
description: Plan a new or existing project with the human before any code is written. Asks one quiz-style decision at a time, then lays out AGENTS.md, CLAUDE.md, docs/plan.md, docs/todo.md, docs/adr/ and .claude/skills/. Run only when the human calls it.
disable-model-invocation: true
---

# Kickoff

Plan first, build later. The human makes every choice that is not obvious;
you bring each one with a recommendation, one at a time.

## Steps

1. Look before you ask. If the folder has code, read the README, the
   package manifests, any AGENTS.md or CLAUDE.md, and `docs/`. Note which
   questions they already answer.

2. Ask the core list in `references/questions.md`, one question per
   message, in the quiz style it describes.

3. Find every other choice this project needs (same file, "Finding the
   rest") and ask them the same way, biggest first.

4. Lay out the files with the script. It never overwrites anything:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/setup_project.py" <project folder> \
     --name "<name>" \
     --summary "<one line>" \
     --reply-cap "<the reply length answer>" \
     [--components-dir <folder>] \
     [--agents]
   ```

   Pass `--components-dir` only when there is a UI, and `--agents` only
   when the project builds its own agents. Read its report: each line
   says created, updated, kept or skipped. If the project already had
   rules of its own, follow `references/merge-rules.md` before going on.

5. Write the plan:
   - `docs/plan.md` from `assets/plan-template.md`, filled with what was
     decided.
   - One ADR per major decision in `docs/adr/NNNN-short-name.md`, from
     `docs/adr/template.md`, numbered from 0001.
   - The first tasks in `docs/todo.md` as `- [ ]` lines, in build order.
   - Known build, test and run commands under "Commands" in AGENTS.md.

6. Stop. Tell the human, within the reply length they picked, what was
   made and what the first task is. Write no code and make no commit
   until they say go.

## Gotchas

- Never merge rules by appending blindly. Two rules that clash leave the
  agent guessing; the human picks, as `references/merge-rules.md` says.
- A "skipped" line means a broken link, a non-UTF-8 file, or a file in the
  way. Tell the human and let them fix it; do not work around it by hand.
- If the folder is inside another git repo, the script does not make a
  new one. That is on purpose.
- Every value passed to the script must be one line. Put longer detail in
  `docs/plan.md`, not in `--summary`.
