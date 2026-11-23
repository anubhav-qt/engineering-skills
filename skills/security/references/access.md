# Access between users

Broken access control is the most common serious hole in web apps
(OWASP Top 10 A01, API Top 10 #1 and #5). Test it with real requests as
two users, never by reading code.

## Build the plan

From the API calls saved in the browser pass, write `plan.json` in the
run's temp folder. Format and an example are in the docstring of
`scripts/check_access.py`. Include:

- every call that reads one user's thing by id: orders, files,
  messages, invoices, profiles, exports, downloads, job results;
- every admin-only call, owned by the admin identity;
- list and search calls, with a marker only A's data holds;
- writes (rename, delete, share, change role) only on this machine with
  `--allow-writes`, each with a `check` the owner reads afterward.

Pick markers carefully: a text in A's answer that B's own data never
holds (A's order title, A's email). With no marker, only an answer
identical to A's counts, and any other 2xx is reported as open.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/check_access.py" --plan "$RUN/plan.json"
```

Each request is replayed as every other identity and as nobody. A
finding prints both curl commands as proof.

## Where ids hide (add these to the plan)

- path, query, JSON body, headers, cookies;
- `include`, `expand`, `fields` and `with` params that pull related data;
- export, report, download and share links;
- background job ids and their result URLs;
- pagination cursors and GraphQL node ids (base64 of a type and id).

## By hand with curl

- Admin functions as a normal user (BFLA): try the admin calls and
  hidden routes found in the bundle, not just the ones the menu shows.
- Mass assignment: add fields like `role`, `is_admin`, `owner_id`,
  `price`, `verified` to an update A is allowed to make, then read the
  object back. A field that sticks is a finding.
- Method switch: a route blocked for GET may answer PUT or DELETE.
- Old API versions: `/v1/` next to `/v2/` often lacks newer checks.

## Supabase and Firebase apps

The browser holds the public key and talks to the database directly, so
row rules are the only protection.

- Supabase: with the anon key and A's token, query each table through
  the REST endpoint (`/rest/v1/<table>?select=*`). Rows of B or of all
  users mean row level security is off or wrong. Repeat with no token.
- Firebase: read collections and storage paths as B and as nobody.
- On a hosted project these are reads only, after the human's yes.

Credit: the "where ids hide" list follows ideas in usestrix/strix
(Apache-2.0), written in our own words.
