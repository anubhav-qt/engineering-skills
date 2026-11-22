# Self-review of the whole diff

Read the PR as a reviewer would, as if someone else wrote it. Tests do not
look for any of this.

## 1. Run the scanner

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/scan_diff.py" \
  --repo <project folder> --base <target printed by setup>
```

It lists lines the PR adds that look like debug leftovers, conflict
markers, focused or skipped tests, TODO notes and possible secrets, plus
new env files, key files, generated files and large files. Secrets are
shown cut short.

A finding is something to look at, not always a mistake. A `console.log`
in a CLI tool, or a TODO with a tracked task, can be fine.

## 2. Read the whole diff

```bash
git diff "$(git merge-base <target> HEAD)"
```

plus every new file (`git status` lists the untracked ones). Look for what the scanner cannot see:

- `print` calls and logging added only to debug;
- commented-out code;
- changes unrelated to the PR (reformatting, stray edits): they belong in
  their own PR;
- config, env variables or feature flags that changed by accident;
- names that no longer say what the code does;
- code that is clever where plain code would read better.

## 3. Act on it

- Obvious leftovers (debug prints, commented-out code, a stray `.only`):
  remove them in the human's folder.
- A possible secret: never commit it. Stop and tell the human, even if it
  looks fake; if it was ever committed, it must be rotated, not only
  deleted.
- Anything that needs judgment (an unrelated change, a skipped test, a
  large file): bring it to the human with your pick.
