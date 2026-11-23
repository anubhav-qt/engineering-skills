# Submit the site to search engines

Updated: 2026-11-23

Only for public pages on the live production site, after step 15 has
checked it. You do the clicks; the human only signs in, enters
passwords or codes, and approves consent screens.

## Ask once per run

In chat, before the run's fixes are deployed (so the tag and the key
ship in that same deploy), list:
- the site, exactly as the canonical URLs write it (for example
  `https://www.example.com/`);
- the sitemap URL;
- the few key pages for "Request indexing" (home and new main pages);
- the changed URLs for IndexNow;
- what changes: a Search Console property, a verification tag and an
  IndexNow key file added to the project (both need a deploy), and the
  site added to Bing Webmaster Tools.

One yes covers this run only. No yes: give the human these steps as a
list instead.

## 1. Sign in to Google

Open https://search.google.com/search-console in the built-in browser.
The human signs in there. Never type a password or a code, and never
sign out or change the account.

If the property already exists and is verified, go to step 4.

## 2. Add a URL-prefix property

"Add property" (a new account sees "Add a website" instead), then
"URL prefix", with the site URL from the ask
(https, and www or not, as the canonical says). Domain properties need a
DNS record: leave those to the human.

Pick the "HTML tag" method and copy the tag the page shows. Put it in
the `<head>` of the home page in the project, in the raw HTML (check it
with `check_pages.py` or `curl -s`), not added by JavaScript. If the head
cannot be edited, use "HTML file" and write exactly the file name and
content Search Console shows into the public folder.

Keep the tag or file for good: Google rechecks it, and removing it
loses the property.

## 3. Same deploy: the IndexNow key

```bash
python3 "<skill dir>/scripts/submit_indexnow.py" key <public folder>
```

It prints the project's key, making `<key>.txt` in the folder the site
serves at `/` if there is none. The key is public by design.

Then tell the human both changes must be deployed first, and wait for
them to say it is live. Never commit or deploy without being asked.

After the deploy: see the tag in the live home page (`curl -s`), then
click "Verify". If it fails, read the reason on the page and report it.

## 4. Sitemap

In the property: "Sitemaps", enter the sitemap URL, "Submit". Read the
status it shows and report it. Errors there are findings.

## 5. Request indexing

"URL Inspection", paste a key page URL, wait for the result, then
"Request indexing". In a narrow pane the inspect box hides behind a
search icon at the top: click it. Never guess an inspect page's
address; guessed ones answer 404. Only the few key pages from the ask: there is a
daily limit per property, and Google gives no number. Never for the
whole sitemap, a page with noindex, or a page that is not live.

If the page says the quota is used up, stop and say "try again
tomorrow".

## 6. Bing Webmaster Tools

Open https://www.bing.com/webmasters. The human signs in. Pick "Import"
from Google Search Console; the human approves Google's consent screen.
Choose the site and import. Bing shows no confirmation: open the site's
Sitemaps page and check the sitemap is listed. If not, submit it there.

If import is not offered, add the site by hand and verify it the way
Bing's page says, using the same deploy rule.

## 7. IndexNow

```bash
python3 "<skill dir>/scripts/submit_indexnow.py" check-key <site URL> --key <key> --allow-host <host>
python3 "<skill dir>/scripts/submit_indexnow.py" send <changed URLs> --key <key> --allow-host <host>
```

`send` checks the key file again, then posts at most 10,000 URLs, all
on one host, to `api.indexnow.org`. Use `--url-file` for long lists.
Answers:
- 200 or 202: received (202: the key check is still pending).
- 400: bad format. 403: key file missing or different.
- 422: a URL is not on the key's host.
- 429: too many; wait 10 minutes or more, then send once.

Send only URLs that changed (added, updated or removed), once per
change, never the whole site again and again. Google does not use
IndexNow.

## Never

- The Google sitemap ping (`/ping?sitemap=`): retired, it errors.
- The Google Indexing API: only for job postings and livestream videos;
  misuse can lose access.
- Type passwords, codes or card details; approve consent screens.
- Change other Search Console or Bing settings: users, owners,
  removals, AI feature settings. Those are the human's choice.

## Report

What was submitted where, each status the pages showed, the IndexNow
code, and what is left for the human (for example "verify failed: the
tag is not live yet").
