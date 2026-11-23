# Login, sessions and tokens

Use test accounts only. On a deployed app, only the read-only items
apply (marked "local only" otherwise).

## Login, sign-up and password reset

- Account enumeration: a wrong email and a wrong password should give
  the same message, status and roughly the same time. Same for reset
  and sign-up ("email already taken" is fine only if sign-up is public
  anyway; say so in the note).
- Rate limits (local only): a capped burst with a wrong password.

  ```bash
  python3 "${CLAUDE_SKILL_DIR}/scripts/rate_probe.py" --url http://localhost:3000/api/login \
    --data '{"email":"sec-a@shop.test","password":"wrong"}' --allow-writes
  ```

  Repeat for reset, sign-up and one-time codes. No limit on a one-time
  code endpoint is usually high: 6 digits fall to a few thousand tries.
- Reset tokens: single use, expire, tied to one account, not in the
  URL of a page that loads third-party scripts. Use one twice; use A's
  token with B's email.
- Default or seed admin accounts still working.

## Sessions

- Logout ends the session: save the cookie, log out, replay a request
  with the old cookie. Still logged in is a finding.
- Session fixation: the session id must change at login.
- Password change and "log out everywhere" end other sessions.
- Long life: a session cookie that never expires, or a JWT with an
  `exp` weeks away and no way to revoke it.
- Cookie flags: `check_headers.py` sees only cookies set on a GET. The
  session cookie is usually set by the login POST, so read that
  answer's `Set-Cookie` (`curl -i` on the login) for `HttpOnly`,
  `Secure` (on HTTPS) and `SameSite`. The browser pass shows whether
  page scripts can read it.

## JWTs

Change and replay, one at a time; each must be rejected:
- a changed claim (`sub`, `role`, `user_id`) with the old signature;
- `alg` set to `none` and the signature removed;
- an expired token;
- a token signed with an obvious secret (`secret`, the app name), if
  the app uses HS256: sign one locally and replay it (local only);
- a token from another environment or another app that shares the
  secret.

## CSRF

For cookie-based sessions, a state-changing request (local only) sent
with no CSRF token and an `Origin` of another site must fail.
`SameSite=Lax` cookies block most of this; `SameSite=None` cookies need
a token. A GET that changes state is a finding on its own.

## OAuth and SSO

- The `redirect_uri` must match exactly; try another path and another
  host.
- The `state` param must be checked; drop it and see if login still
  completes.
- Linking a social login to an existing account by email alone lets
  anyone with that email take the account.
