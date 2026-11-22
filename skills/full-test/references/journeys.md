# Key user journeys

A journey is a whole flow a real user walks, like sign up, then log in,
then buy one thing. Walking journeys is the slowest, costliest part of
full-test, so pick as few as you can.

## Picking them, fresh for each PR

Pick only journeys that both:

- pass through code this PR changed, directly or through a shared piece
  (a shared component, an API route, auth, a database table, global
  styles, routing); and
- matter most to users: signing in, paying, saving their work, the one
  thing the app is for.

Usually one to three is enough. If the PR changes nothing a user can see
or do (only docs, tests, tooling or internal refactors with full test
coverage), walk none and say why.

feature-test already tried every changed input and button with edge
cases. Here, walk each journey end to end to check the pieces still work
together: its happy path, and its main error path.

## Walking them

1. Start the app from the `pr` copy, from the production build if the
   project can serve one (`npm run preview`, `next start` and similar).
   That way you test the merged code that will ship.
2. Use the built-in browser first. Only if there is none, use an outside
   real browser (a browser extension, or Playwright and similar).
3. Walk each journey step by step. Watch the console and the network
   panel the whole time for errors and failed requests.
4. Stop the app when done.

Write down each journey and what happened. A journey you could not walk
goes in the report as "not checked yet".
