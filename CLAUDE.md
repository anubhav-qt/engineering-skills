# engineering-skills

Open-source agent skills, shipped as one Claude Code plugin named
`software-engineering` (marketplace `anubhav-qt`). Commands look like
`/software-engineering:<skill>`.

## Layout

- `skills/<name>/`: `SKILL.md` (steps and gotchas, under 500 lines),
  `scripts/` (tested Python), `references/` (detail, each with an
  `Updated:` date), `assets/` (templates, browser JS).
- Skills: kickoff, feature-test, full-test, debug, logger, security,
  visibility-handling. Next: SHIP-IT.
- `tests/`: unittest for every script; `*_app.py` are shared local test
  servers.
- `docs/todo.md`: roadmap and small todos. `docs/*-research.md`: research
  and dated decisions per skill (kept uncommitted).
- `.claude-plugin/`: plugin and marketplace manifests.

## Rules

- Scripts: Python 3.9, standard library only, plain readable code.
- Every skill: web research, decisions one at a time, build, tests,
  planted bugs, a live run. Names are final only once a skill is done.
- kickoff never names other skills; the others may hand off to each
  other (for example to feature-test after a fix).

## Checks

```bash
python3 -m unittest discover tests
claude plugin validate .
```
