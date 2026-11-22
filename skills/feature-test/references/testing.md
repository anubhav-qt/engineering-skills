# Writing tests that prove something

## What to test

- Test what the code does, through the door other code uses (its public
  functions, its API, its screen). Do not test its insides: those tests
  break on every clean-up and catch little.
- Use the real thing where you can: a real database in a container, real
  files in a temp folder, the real HTTP layer. Mock only outside services
  you do not own (payments, email, third-party APIs). Mocks hide SQL,
  wiring and config bugs.
- Never chase a coverage percent. It pushes tests toward the insides.

## How many of each kind

- Most tests are small and fast: one behavior each.
- Some tests check pieces working together (code plus database, two
  services talking).
- A few end-to-end tests walk the main user journeys: the happy path and
  the main error path. Not every combination; that is what the small
  tests are for.
- When an end-to-end test finds a bug, also add a small test that catches
  it, so the next failure points straight at the cause.

## Fixing a bug

1. Write a test that shows the bug.
2. Run it and watch it fail, for the reason you expect.
3. Fix the code.
4. Run it and watch it pass. Keep it forever.

A test written after the fix tends to prove the fix, not the bug.
If the bug truly cannot be reproduced in a test, say why in the report
and use the closest check you can run.

## Flaky tests

A test that sometimes passes and sometimes fails is a bug.

- Find the cause. The usual ones: the clock, randomness, the network,
  test order, shared state, timing between threads or processes.
- Freeze it: fixed time, fixed random seed, a local fake for the network,
  a fresh state per test, wait for a condition instead of sleeping.
- Run the suspect test many times in a row to prove it is fixed.
- Never just add retries or turn the test off.

## Never

- Edit, skip, loosen or delete a test so it passes.
- Special-case test inputs in the code.
- Catch and ignore an error just to make a test go green.
