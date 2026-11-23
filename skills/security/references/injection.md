# Injection

Run `probe_inputs.py` once per input the server reads, with `FUZZ`
where the input goes. Only inputs that reach something risky need it:
SQL, templates, file paths, shell commands, outbound URLs, or HTML
another user sees.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/probe_inputs.py" \
  --url "http://localhost:3000/api/search?q=FUZZ" --header "Cookie: env:SEC_A_COOKIE"
python3 "${CLAUDE_SKILL_DIR}/scripts/probe_inputs.py" \
  --url http://localhost:3000/api/notes --method POST \
  --data '{"title": "FUZZ"}' --header "Cookie: env:SEC_A_COOKIE" --allow-writes
```

Use `--value` for a value the field normally takes (an id for a number
field), and `--only` to run just the checks that fit the input.

## What each result means

- `xss` FINDING: the input comes back as raw HTML. Confirm it in the
  browser: the tag renders, or a harmless `<img src=x onerror=...>`
  with a console marker fires. A reflection in JSON is only a note,
  unless a page later renders that JSON as HTML.
- `ssti` FINDING: the template engine ran code. Treat as critical on
  the server side; stop there, do not escalate.
- `sql` FINDING: error text or a true/false difference. OPEN: a server
  error with no SQL text; check the server log on this machine to see
  the query error before calling it confirmed.
- `path` FINDING: `/etc/passwd` came back. Never request anything
  beyond that file.
- `cmd` FINDING: three slow answers out of three, control fast.
- `ssrf` FINDING: the server called the script's listener. On a
  deployed app this check is skipped.
- `redirect` FINDING: the answer sends users to evil.example.
- `leak` FINDING: a bad input showed a stack trace, SQL error or file
  path that the normal input did not.

## Checks done by hand

- Stored XSS: save a value with a unique tag as A, then open every
  screen that shows it, as B and as an admin. Admin and email views are
  the usual victims.
- DOM XSS: search the bundle for `innerHTML`, `dangerouslySetInnerHTML`,
  `v-html`, `document.write`, `eval`, and trace whether URL or user data
  reaches them; prove it in the browser.
- NoSQL: send `{"$ne": null}` or `{"$gt": ""}` in place of a JSON value
  in login or filters. Logging in without the password is a finding.
- GraphQL: introspection (probe_paths notes it), batching many queries
  in one request, deep nested queries (local only, small depth).
- Header injection: a newline (`%0d%0a`) in a value that ends up in a
  response header or an email.

## What does not prove injection

- A 500 alone. Many apps fail on odd input without being injectable.
- An input echoed back escaped (`&lt;x-sec&gt;`).
- A slow answer once. Timing proves only when it repeats and the
  control stays fast.
- An ORM or framework that "escapes everything". Probe the exact
  endpoint anyway; raw queries hide in every codebase.
