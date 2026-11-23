# Confirm, rate, fix and report

Updated: 2026-11-23

## Confirm

A script line or probe hit is a lead. It becomes a finding when you
have looked:

1. Open the page (raw HTML with `curl -s` or the browser) and see the
   problem yourself.
2. Rerun the same check; a lead that only shows once is "not checked
   yet" until you know why.
3. Look for a second sign: the tag in the source file, the route that
   answers 200, the control that the keyboard skips.

Mark each one confirmed, or "not checked yet". Never round up.

## Rate

- Blocker: a page meant for search cannot be indexed (noindex, robots
  blocks it, non-200, redirect loop, JavaScript adds noindex), or a
  person cannot use a core task (a control the keyboard cannot reach,
  a form field with no name, a keyboard trap).
- Major: search or people get it wrong or partly (wrong canonical,
  content only after JavaScript, soft 404, broken sitemap, missing
  alt on meaningful images, no visible focus, contrast fails, no lang).
- Minor: a weaker result, not a broken one (missing description or OG
  image, duplicate titles, redirect chains, small targets, heading
  jumps).
- Note: worth knowing, nothing broken (meta keywords, ignored sitemap
  tags, a canonical pointing elsewhere on purpose).

Hype items (no llms.txt, no FAQ schema, a low "AI score") are never
findings. Scores with made-up weights are never reported.

## Fix small, ask big

Fix yourself, then rerun the same check:
- alt text when the meaning is obvious, or `alt=""` when decorative;
- labels, accessible names, `lang`, visible focus styles;
- titles and descriptions written from the page's real content;
- canonical tags, meta robots, robots.txt and sitemap syntax;
- OG and X tags;
- a `div` button turned into a `<button>`.

Ask the human first:
- rendering mode changes (client-only to server or static rendering);
- URL moves and redirects;
- brand colors for contrast;
- rewriting content;
- AI crawler rules in robots.txt;
- anything across many files.

## Regression guard

For each blocker, add one test to the project's existing tests that
fails if it comes back. Examples:
- the production build's robots.txt does not say `Disallow: /` for `*`
  or Googlebot;
- a key page's built HTML has no `noindex` and has its title;
- an unknown route answers 404;
- an axe check in the existing end-to-end tests for the fixed screen.

Watch it fail with the bug put back, then pass with the fix. Never add
a new test framework without asking.

## Report

Within the reply length the project asks for:
- each confirmed finding: level, what it costs (who cannot find or use
  what), the command or page that shows it;
- what was fixed and the check that now passes;
- decisions for the human, one at a time;
- the human's list: screen reader pass, sign-ins for submitting, AI
  crawler choices, content or brand choices;
- what was submitted (Search Console, Bing, IndexNow) and each status;
- what did not run, marked "not checked yet" (axe blocked by CSP, focus
  needing window focus, deployed site not checked).
