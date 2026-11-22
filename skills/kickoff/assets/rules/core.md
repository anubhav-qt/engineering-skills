
## Where things live

- `docs/plan.md`: the plan everyone agreed on.
- `docs/todo.md`: small tasks and todos.
- `docs/adr/`: one file per major decision, nothing smaller.
- `.claude/skills/`: this project's skills. Before a task, look there and use
  any skill whose description fits.

## Commands

None yet. Add each build, test and run command here as it appears.

## Working rules

### Talking with the human

- Plan as much as you like, but ask the human one decision at a time.
- Ask every question as a quiz: a few options, your pick first and marked
  as recommended, and room for the human's own answer.
- Never take a decision that is not obvious. Ask, with a recommendation.
- Say everything in plain one-liners a child could follow. No emojis.
- Reply length: {{reply_cap}}
- Never guess. Check it first (read it, run it, look at it). If you have
  not checked it, say "not checked yet".

### How work is done

- Plan first. Write code only after every decision is made.
- The goal is not the fastest finish. It is fully tested, production
  ready, well thought out, simple and beautiful.
- Follow a proper engineering standard: tests, reviews of your own work,
  clear names, small pieces.

### Code

- Keep code very simple and easy to read. The most beautiful code is the
  easiest to read and still does the job.
- No one-liners that pack several steps together.
- No clever or nested conditionals where a plain if/else reads better.

### Testing

- Code that works in theory is not done. Test it end to end, profile it,
  and fix the slow parts.
- After the tests pass, plant one mistake at a time (a wrong number, a
  skipped check, a flipped condition) and run the tests. Each mistake
  must make a test fail. If one does not, add a test that catches it.
  Then undo the mistake.

### Docs

- Keep this file alive: update it with each change to code, docs or ADRs,
  so a new session understands the project from it. Keep it short.
- Everything else goes in `docs/`.
- ADRs only for major changes. Everything smaller goes in `docs/todo.md`.

### Commits and PRs

- One line only: `<type>: <message>`, where type is feat, fix, chore,
  docs, refactor, test or perf. Straight to the point.
- No em dashes anywhere, ever.
- Only PRs get a longer description.
- Never add AI attribution: no AI co-author lines, no "generated with"
  lines.
