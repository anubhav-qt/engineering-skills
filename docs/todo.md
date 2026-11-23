# Todo

Skills for the `engineering` plugin, in build order. Names are final only
once a skill is done. Each skill: web research first, then a proposal,
then one decision at a time, then build, test, plant bugs, live run.

## Skills

- [x] kickoff: plan a project one decision at a time, set up AGENTS.md, docs and skills folder.
- [x] test: prove a change works (tests, browser checks, profiling, planted bugs). Renamed to feature-test.
- [x] full-test: test the whole PR before sending it (full suite, type checks, lint, key user journeys, regressions across the app).
- [x] Rename test to feature-test, and narrow it to only what the feature touches (no full suite, no full type check), leaving the rest to full-test.
- [x] security: live attack testing of the running app on this machine, proof for every hole, read-only on a deployed app after a yes.
- [ ] security follow-up: flag typosquatted dependency names (open in docs/security-research.md).
- [x] debug: reproduce first, find the real cause, never patch the symptom, keep a test for it.
- [x] logger: add logs, metrics and traces only where they help, test them, and prove fake secrets stay out.
- [ ] logger follow-up: find_log_calls.py lists log calls inside Python docstring examples (listed, never flagged).
- [ ] visibility-handling: SEO, AEO, accessibility and anything that makes the product visible on the web; used only when needed.
- [ ] SHIP-IT: final commits, push, PR, deploy, and a rollback plan. Command `/software-engineering:SHIP-IT`, title "SHIP-IT" (no "!", it is not allowed in skill names).
- [ ] When building SHIP-IT: add staging to it (deploy to staging, check, then production), and make kickoff ask about staging (is there one, where, how to deploy).

## Launch

- [ ] Show HN post.
- [ ] r/ClaudeAI post.
- [ ] Post on X.
- [ ] Submit to hesreallyhim/awesome-claude-code through its web form, by hand, on or after 2026-12-06 (repo must be 14 days old, or have 100 stars).
- [ ] Social preview image for the GitHub repo.
- [ ] Plugin icon (.claude-plugin/icon.png, square PNG, 512 to 2048 px).
