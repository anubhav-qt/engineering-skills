# Confirm, rate and report

AI pentest agents often report holes that are not there. Every rule
here exists to stop that.

## Confirm

A lead becomes a finding only with paired evidence: two requests that
differ in one thing (owner vs other user, logged in vs not, attack
input vs harmless input), where only the attack shows the hole.

Before calling it confirmed:
1. Restate the claim in one sentence: who can do what to whom. Half of
   false leads fall apart here.
2. Replay the proof from a clean session (fresh login, no cached state).
3. Find a second sign that does not depend on the first: the data shows
   up in the browser, the server log shows the query error, the changed
   object reads back changed.
4. Timing needs repeats with a fast control in between.

Close every lead in one of three states:
- confirmed: the proof and second sign hold;
- ruled out: name the exact control that stops it ("returns 404 for
  other users' orders, checked as B and anonymous");
- open: not proven either way. Report it as "not checked yet", never as
  safe.

Reject these reasons for closing a lead: "the framework handles it",
"the ID is hard to guess" (unless it really is random, like a UUID v4,
and never listed anywhere), "only admins can reach it" (did you check
as a non-admin?), "it is only on staging".

## Rate

Ask four questions about each confirmed finding:
1. What does the attacker end up with (data, money, another account,
   the server)?
2. What did it take (no account, any account, a victim's click, an
   admin's mistake)?
3. How far does it reach (one record, one user, every user, the
   server)?
4. What is that worth in this app (a todo list vs a bank)?

Then:
- critical: no account or any account gets every user's data, money,
  admin, or code running on the server;
- high: any account gets another user's private data or account, or
  admin functions; a secret key that works;
- medium: needs a victim's click or narrow conditions, or leaks less
  sensitive data;
- low: small impact, or very hard to use.

Choose the lower level when unsure. Your own reasoning must not argue
against your level. Downgrade a weak finding rather than dropping it.

## Not a finding (hardening notes at most)

- Missing headers with no hole that uses them.
- Server version banners.
- Rate limits missing on endpoints that cost nothing and reveal nothing.
- Self-XSS (only the user can hurt themselves).
- CORS `*` on public, cookie-free data.
- Public keys in the bundle (Stripe `pk_`, Supabase anon, Firebase web
  config).
- A logout that does not use CSRF protection.
- Errors that show no internals.

## Keep the big ones from coming back

For each critical or high finding that was fixed:
- a test in the project's own suite that sends the attack and expects
  it to fail (B reads A's order and gets 404; the quote gives a clean
  400). Watch it fail with the fix undone;
- a short note in the project's `docs/` (one file, like
  `docs/security.md`): date, what the hole was, how it was fixed, the
  test that guards it. No secrets, no working exploit strings beyond
  what the test holds.

## Report format

Per finding: level, one sentence on what an attacker gets, where
(route or file), the proof command, and fixed or not. Then hardening
notes in one short list, secrets to rotate, what was not run and why,
and that package names and versions went to api.osv.dev.
