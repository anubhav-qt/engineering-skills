# Browser pass

Use Claude's built-in browser. Log in as test account A and walk every
screen once: each page, form, button, upload and admin area you can
reach. Then check the items below.

## Save the API calls (feeds access and injection checks)

- `read_network_requests` after each screen. Keep each call the app
  makes: method, URL, which ids are in it, and the body's shape.
- Note ids that belong to A (order 12, file abc) and a text in each
  answer only A's data holds. Those become `marker`s in the access plan.
- Note every input the server reads: query params, JSON fields, headers,
  file names. Those are the targets for `probe_inputs.py`.

## Network

- Tokens, passwords or personal data in URLs or query strings (they end
  up in logs and the Referer header).
- Answers that carry more than the screen shows: password hashes, other
  users' emails, internal flags, `is_admin`. That is over-fetching.
- Calls over `http://` from an HTTPS page.
- User data sent to third parties the human did not mention.
- Keys sent from the browser: a public key (Stripe `pk_`, Supabase anon,
  Firebase web key) is fine; a secret key is a finding.

## Console and storage (`javascript_tool`)

- `document.cookie`: if the session cookie shows up, it lacks HttpOnly
  and any XSS can steal it.
- `localStorage` and `sessionStorage`: session tokens or JWTs there are
  readable by any script on the page.
- Console errors that print stack traces, SQL or internal URLs.
- CSP violation messages show whether the CSP is enforced.

## JWTs

Decode the middle part (base64url) without checking the signature. Look
for:
- secrets or personal data inside it (anyone can read a JWT);
- roles or ids the server might trust: change one, keep the signature,
  and replay it (`references/auth.md` has the full list);
- no `exp`, or an expiry weeks away.

## Client-side checks

Hidden or disabled buttons, admin links removed from the menu, prices
computed in the browser: none of these protect anything. Note each one
and test the matching API call directly in the access or logic checks.
