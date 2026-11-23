# AI answer engines: what is proven, and what is hype

Updated: 2026-11-23. From each vendor's own crawler page and Google's
AI optimization guide (2026-05-15). Recheck yearly.

## What works

- Google AI Overviews and AI Mode run on normal ranking: a page must be
  indexed and allowed in snippets. Everything in `seo.md` applies.
- Crawlable without JavaScript. AI crawlers do not run it; a
  client-only page is empty to them.
- One clear title and H1 per page; the answer in plain text near the
  top; facts in text, not only in images, canvas or video; dates shown;
  sources linked. The one peer-reviewed study (GEO, KDD 2024) found
  cited sources, statistics and quotations raised visibility by about
  30 to 40%.
- Original content people find useful. A skill cannot make this up,
  and must never invent claims, reviews or expertise.

## AI crawler rules in robots.txt

Each vendor has separate crawlers for training, search, and fetches a
user asks for. Blocking training does not have to block search.
`check_site.py` lists what each one may do today:

- OpenAI: GPTBot (training), OAI-SearchBot (ChatGPT search; block it and
  the site leaves ChatGPT search), ChatGPT-User (user fetches;
  robots.txt "may not apply").
- Anthropic: ClaudeBot (training), Claude-SearchBot (search),
  Claude-User (user fetches).
- Perplexity: PerplexityBot (search), Perplexity-User (user fetches;
  "generally ignores robots.txt").
- Google: Google-Extended is a token, not a crawler: it controls Gemini
  training and grounding, and does not affect Google Search.

This is a business choice. Show the human the current lines and ask,
one question at a time: allow AI search? allow training? Never add
`User-agent: * Disallow: /` for AI: it also removes the site from
Google. Coming signals (IETF AIPREF, Google in early 2027) are not
usable yet.

## llms.txt

- A Markdown file at `/llms.txt`: an H1, an optional summary
  blockquote, then H2 lists of links (llmstxt.org).
- No search engine has shown it helps. Google says its search does not
  use it; studies found almost no crawler requests for it.
- Coding agents do read it when pointed at it. So: never add it by
  default. Offer it only for developer docs or developer tools, and say
  plainly that it is not for search.
- `check_site.py` checks its shape only if it exists.

## Hype to refuse

- "Add llms.txt and you will show up in ChatGPT."
- "Chunk content for AI" or "write for AI". Google says no.
- FAQ schema for rich results (retired May 2026).
- Many AI-written pages to catch answers: Google's scaled content abuse
  policy.
- Scores like "AI readiness 72/100" with made-up weights.

## Measuring (the human's list)

- Google Search Console: Generative AI performance report.
- Bing Webmaster Tools: AI Performance (Copilot and Bing AI citations).
- Nothing official covers ChatGPT or Perplexity citations yet.
