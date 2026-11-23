# Search engines: the rules that matter

Updated: 2026-11-23. From Google Search Central pages read that day.
Recheck any rule here that is more than a year old.

## Status, robots and noindex

- A page meant for search answers 200. Missing pages answer 404 (or
  410); pages behind a login answer 401 or 403. For non-200 answers
  Google may skip rendering.
- Soft 404: an app that answers 200 for any URL. Fix: answer 404 from
  the server for unknown routes, or a JavaScript redirect to a URL that
  answers 404, or add `noindex` on the error view.
- robots.txt controls crawling, not indexing. Google reads only the
  first 500 KiB, treats a 4xx as "no robots.txt", and stops crawling
  while it answers 5xx or 429. It caches the file for up to a day, so a
  bad file stays live after the fix.
- Keep a page out of search with `<meta name="robots" content="noindex">`
  or `X-Robots-Tag: noindex`, and leave it crawlable so Google sees it.
- Redirects: one 301 (or 308) hop to the final URL. Chains waste crawl
  budget; loops drop the page. Moving URLs needs a 301 from every old
  URL: ask the human first.

## Rendering

- Google renders with an up-to-date Chrome, later than it crawls.
  AI crawlers (GPTBot, ClaudeBot and others, per the one measured study)
  fetch JavaScript files but never run them.
- So on public pages the title, description, canonical, main text,
  links and JSON-LD belong in the raw HTML: server rendering, static
  generation or pre-rendering. `check_pages.py --rendered` shows what
  only exists after JavaScript.
- If JavaScript touches the canonical, it must keep the raw value.
  Never add or remove `noindex` with JavaScript on a real page.
- Routes use the History API (`/pricing`), not `#/pricing`.

## Canonical

- One `<link rel="canonical">` per page, absolute URL, pointing at a
  URL that answers 200 and is not itself redirected or noindex.
- Each page normally points at itself. Pointing every page at the home
  page removes them all from search.
- Pick one host (`www` or not) and https; 301 the others to it.

## Titles and descriptions

- Every page has one `<title>`, different from every other page,
  written from what the page really says. No length limit is a Google
  rule; tools that say "60 characters" are guessing at truncation.
- A meta description per page, unique, a plain summary. Google often
  replaces it with page text.
- `meta keywords` does nothing. Keyword stuffing can hurt.
- Site name: `WebSite` JSON-LD on the home page with `name` and `url`.
- Favicon: a square icon (larger than 48x48 recommended), linked from
  the home page, crawlable.

## Sitemaps

- At most 50,000 URLs or 50 MB per file; more needs a sitemap index.
- Only absolute, canonical, indexable URLs that answer 200.
- `lastmod` only if it is really when the page changed; Google ignores
  it otherwise. `priority` and `changefreq` are ignored: leave them out.
- Point to it from robots.txt (`Sitemap: https://...`), and submit it
  in Search Console as `references/submit.md` says.

## hreflang (only for language or region versions)

- Each version lists every version, itself included, and each pair
  links both ways, or Google ignores the pair. Add `x-default` for the
  fallback.
- Codes: ISO 639-1 language, optional ISO 3166-1 alpha-2 region
  (`en-GB`, not `en-UK`); script codes like `zh-Hant` work; `es-419`
  is not supported.
- One method is enough: HTML links, HTTP headers or the sitemap.

## Structured data (JSON-LD)

- Mark up only what the page visibly shows, and truthfully. Fake
  ratings or hidden content can bring a manual action.
- Before adding a type, check Google's current search gallery
  (developers.google.com/search/docs/appearance/structured-data/search-gallery):
  rich results come and go every year.
- Gone: FAQ rich results (2026-05-07), HowTo (2023), and several others
  in 2025. The markup is harmless but brings nothing.
- Usually worth it when true: `WebSite` (site name), `Organization`
  (logo), `BreadcrumbList`, `Product` with `Offer`, `Article`.
- Structured data is not needed for AI features, and there is no
  special AI schema.

## Social cards

- `og:title`, `og:description`, `og:image` (absolute URL that answers
  200, not blocked by robots.txt), `og:url`, `og:type`.
- `twitter:card` (`summary_large_image`); X falls back to the OG tags
  for the rest.
- After a fix, the human can recheck with each platform's card
  debugger; caches can keep the old card for days.

## Search Console and Bing

- Adding, verifying and submitting the site: `references/submit.md`.
- Search Console: check that the site is included in generative AI
  features if the human wants that, and watch the Generative AI
  report. Bing has an AI Performance report for Copilot citations.
- URL Inspection shows the rendered page as Google sees it.
