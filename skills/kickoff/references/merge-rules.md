# Merging rules into an existing project

The script never edits an existing AGENTS.md. Run this flow when its
report ends with "Rules to merge into AGENTS.md:", or when it says
"updated CLAUDE.md" and that file holds rules of its own.

Ask every question the way `questions.md` says: one at a time, quiz style,
your pick first.

Never say "mine", "yours" or "ours": it is unclear who they mean. Call
the two sides "the project's rule" and "the kickoff rule", every time.

1. Gather the project's rules: everything in AGENTS.md, plus every line
   of CLAUDE.md other than `@AGENTS.md`. The kickoff rules are the
   printed block (or, when AGENTS.md was just created, its "Working rules"
   section).

2. Ask which rules lead:
   - "Keep the project's rules, add kickoff rules where they do not
     clash." (Recommended)
   - "Use the kickoff rules instead of the project's."

3. If the kickoff rules lead: replace the project's rules with them. Keep
   everything that is not a rule (what the project is, commands, notes on
   the code) exactly as it was.

4. If the project's rules lead, go through the kickoff rules one by one:
   - A project rule already says the same thing: skip it.
   - No project rule clashes with it: add it under "## Working rules" in
     AGENTS.md, with no question.
   - It clashes with a project rule: ask, one clash per question, quoting
     both word for word with their side named. Options: "Keep the
     project's rule", "Use the kickoff rule". Recommend the one that fits
     this project better, and say why in its description. Then remove the
     losing rule from whichever file holds it.

5. Add the kickoff "Where things live" and "Commands" sections if
   AGENTS.md has nothing like them. They are not rules, so no question is
   needed.

6. Tell the human what was added and which clashes were settled.
