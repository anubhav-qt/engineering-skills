# LLM and agent features

Only when the app has a chatbot, an AI feature or an agent with tools.
Based on the OWASP Top 10 for LLM Applications (2026) and for Agentic
Applications (2026). Local only for anything that writes or costs money.

## Set up

On this machine, put a canary in the system prompt for the run
(`sec-canary-<random>`), so a leak shows up exactly. Remove it at the
end.

## Checks

- Direct prompt injection: ask the feature to ignore its rules, reveal
  its instructions, or act as another user. The canary in an answer
  means the system prompt leaks. Hidden instructions alone are not
  secrets; leaked keys, other users' data or rules the app relies on
  for security are.
- Indirect prompt injection: put instructions inside content the model
  reads later: a document A uploads, a profile field, a product review,
  a web page the agent fetches, a tool result. A finding is the model
  following them, especially when B or an admin triggers it.
- Output handling: model output rendered as HTML (ask it to answer with
  `<x-sec>` and look for raw HTML), put in SQL, shell commands, file
  paths or URLs the server fetches. These are ordinary injection holes
  with the model as the carrier.
- Excessive agency: list the tools the model can call. Ask it, as B, to
  use them on A's data (read A's orders, email A, delete A's file). The
  tools must check the user, not trust the model. Actions that send,
  pay or delete need a human confirmation step.
- Sensitive data: ask for other users' data, keys, or internal URLs the
  model may have in its context or retrieval index.
- Cost: no limit on prompt size, conversation length or calls per user
  lets anyone run up the bill. Check limits exist; do not burn money to
  prove it.

## What is not a finding

A model saying something rude or off-topic, or "jailbreaking" into
harmless text, is a product issue, not a security hole. Report it as a
note only if the human cares about it.
