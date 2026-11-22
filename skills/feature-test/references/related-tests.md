# Running only the related tests

Run the tests that exercise the changed code, not the whole suite. The
whole suite runs once per PR in full-test.

## Finding them

1. Use the test runner's own "related tests" mode when it has one. It
   follows imports, so it finds tests you would miss by name:
   - Jest: `npx jest --findRelatedTests <changed files>`
   - Vitest: `npx vitest related --run <changed files>`
   - pytest with pytest-testmon already set up: `pytest --testmon`
   - Go: `go test ./<changed package>/...`
   - Cargo: `cargo test -p <changed crate>`
2. If the runner has no such mode, pick the test files that cover the
   changed files: the matching test file (`cart.py` and `test_cart.py`),
   plus every test file that imports a changed file (search for the
   module name).
3. Always include the tests you just wrote or changed.

## Run the whole suite instead when

- config changed (build, test, lint, env, CI files);
- dependencies or the lockfile changed;
- test setup changed (fixtures, conftest, setup files, test helpers);
- a shared helper changed that many files import;
- a data file, schema or migration changed;
- you cannot tell which tests cover the change.

## In the report

Name the command you ran and say it was the related set, so the reader
knows the whole suite is still to come in full-test.
