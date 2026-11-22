# Todo

Skills for the `engineering` plugin, in build order. Names are final only
once a skill is done. Each skill: web research first, then a proposal,
then one decision at a time, then build, test, plant bugs, live run.

## Skills

- [x] kickoff: plan a project one decision at a time, set up AGENTS.md, docs and skills folder.
- [x] test: prove a change works (tests, browser checks, profiling, planted bugs). Renamed to feature-test.
- [x] full-test: test the whole PR before sending it (full suite, type checks, lint, key user journeys, regressions across the app).
- [x] Rename test to feature-test, and narrow it to only what the feature touches (no full suite, no full type check), leaving the rest to full-test.
- [ ] security: live attack testing (network tab, console, headers, auth, injection, exposed secrets, dependency audit), beyond the built-in /security-review that only reads code.
- [ ] debug: reproduce first, find the real cause, never patch the symptom, keep a test for it.
- [ ] logger: add logging only where it helps (errors, key events, slow paths), no noise.
- [ ] visibility-handling: SEO, AEO, accessibility and anything that makes the product visible on the web; used only when needed.
- [ ] SHIP-IT: final commits, push, PR, deploy, and a rollback plan. Command `/engineering:SHIP-IT`, title "SHIP-IT" (no "!", it is not allowed in skill names).

## Launch

- [ ] Show HN post.
- [ ] r/ClaudeAI post.
- [ ] Post on X.
- [ ] Submit to hesreallyhim/awesome-claude-code through its web form, by hand, on or after 2026-12-06 (repo must be 14 days old, or have 100 stars).
- [ ] Social preview image for the GitHub repo.
- [ ] Plugin icon (.claude-plugin/icon.png, square PNG, 512 to 2048 px).
