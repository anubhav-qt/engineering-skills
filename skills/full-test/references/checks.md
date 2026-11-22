# Finding, running and sorting the checks

## Find what CI runs

CI is the real list of checks that matter. Read, in this order:

1. CI config: `.github/workflows/*.yml`, `.gitlab-ci.yml`,
   `.circleci/config.yml`, `azure-pipelines.yml`,
   `bitbucket-pipelines.yml`, `Jenkinsfile`, `.buildkite/`.
   Take the jobs that run on pull requests.
2. The project's task runner: `package.json` scripts, `Makefile`,
   `justfile`, `Taskfile.yml`, `tox.ini`, `noxfile.py`, `pyproject.toml`.
   CI often calls one of these; run the same target.
3. `AGENTS.md`, `CLAUDE.md` and the README, for commands CI does not list.

If there is no CI, use the project's own lint, type check, build and test
commands. If a kind of check does not exist (no linter, no types), skip
it and say so in the report. Do not add tools the project does not use.

## The checks file

A JSON list, in the order to run:

```json
[
  {"name": "install", "command": "npm ci"},
  {"name": "lint", "command": "npm run lint"},
  {"name": "type-check", "command": "npx tsc --noEmit"},
  {"name": "build", "command": "npm run build"},
  {"name": "tests", "command": "npm test", "timeout": 3600}
]
```

`timeout` is in seconds (default 1800). Names use letters, digits, `-`
and `_`. Every check runs even after one fails, and each one's full
output goes to a log file the script names at the end.

## Clean install from the lockfile

The copy has no installed packages. Install with the frozen form, which
fails if the lockfile does not match the manifest:

| Tool | Command |
| --- | --- |
| npm | `npm ci` |
| pnpm | `pnpm install --frozen-lockfile` |
| yarn (berry) | `yarn install --immutable` |
| bun | `bun install --frozen-lockfile` |
| uv | `uv sync --locked` |
| poetry | `poetry check --lock && poetry install` |
| pip with a requirements file | `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` |
| cargo | `cargo build --locked` |
| go | `go mod download && go mod verify` |

## Production build

Run the real build command, not only the dev server. Dev servers hide
case-sensitive imports, missing files and tree-shaking breakage, and some
bundlers (Vite, esbuild) skip type errors, so the type check is its own
step.

## Migrations

Only if the PR adds or changes a migration. Use a fresh, throwaway
database (a container, or a temp SQLite file), never a shared or real
one. Run every migration up. If the project supports going down, run
the new ones down, then up again. Add these as checks in the file.

## Sorting a failure

Read the log, then ask in this order:

1. Is it already broken on the target branch? Set up the `base` copy the
   same way (install first) and run the failing check there:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/run_checks.py" \
     --checks <folder>/checks.json --root <folder>/base \
     --log-dir <folder>/logs-base --only install --only <name>
   ```

   If it fails there the same way, it is not this PR's. Note it, do not
   fix it, do not block on it.

   For lint and type checks, compare the problem lists. Old problems
   (same file, rule and message on the target branch) do not block. Only
   the ones this PR adds do.

2. Is it flaky? Write a check that runs only the failing test, and run it
   five times on the same code with `--repeat 5`. Mixed results mean
   flaky: report it as a bug with the likely cause (clock, randomness,
   network, order, shared state, timing). Never retry it to green.

3. Is the fix obvious? Lint, format, a type error, a syntax error, a
   broken import, a missing file, or a test the PR plainly broke with one
   clear fix. Fix it in the human's folder, then:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/pr_copy.py" refresh <folder>
   ```

   and rerun that check with `--only <name>`.

4. Anything else is the human's call: a test that may itself be wrong, a
   change in behavior, a failure in code the PR did not touch, a fix that
   needs a new dependency, or two good ways to fix it. Bring each one
   with what you found and your pick.
