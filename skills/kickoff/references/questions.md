# Kickoff questions

## How to ask

- One question per message. Wait for the answer before the next one.
- Use the ask-question tool (AskUserQuestion in Claude Code). Give 2 to 4
  options, put your pick first with "(Recommended)" after its label, and
  let the human type their own answer.
- Each option gets a one-line description of what it means.
- If there is no ask-question tool, write the options as a numbered list
  and always end it with "Type your own answer."
- If the human types their own answer, use their words as they are.
- Skip a question when the code or docs already answer it. Say what you
  found in one line instead.

## Core list, in this order

1. What is it? Ask for a short name and a one-line summary. Offer options
   drawn from the folder name and any README.
2. Who uses it? Offer the likely kinds of users.
3. What is the first version? It must be a complete product that real
   people can use, not a demo. Offer two or three scopes that each meet
   that bar.
4. Does it have a UI? If yes, where do components live? Offer
   `components` for a new project, or the folder the code already uses.
5. Will it build its own AI agents? Yes or no.
6. How long may replies be? Offer exactly these, with the first as the
   pick:
   - "5 lines at most." (Recommended)
   - "15 lines at most."
   - "No limit."
   The answer goes in AGENTS.md as written, so it must be one sentence.

## Finding the rest

After the core list, list for yourself every choice this project still
needs that is not obvious. Look for these kinds:

- How many users to expect, now and in a year.
- Whether it must scale, or is a small personal project.
- Whether to run everything ourselves (our own Kubernetes, database
  containers, logging and so on) or use managed services, which may cost
  money. Name the likely services and their rough price in the options.
- Language, framework and package manager.
- Where data lives, and its shape.
- Sign-in and who may see what.
- Where it runs and how it ships.
- Outside services it calls, and what happens when one is down.
- How it is tested end to end, and how it is profiled.

Drop any choice that has a clear standard answer for this stack, and say
it in the plan instead. Ask the rest, one at a time, biggest first.
A choice is major (and gets an ADR) when undoing it later would mean
rewriting large parts of the code.
