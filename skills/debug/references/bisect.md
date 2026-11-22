# Finding the commit that broke it

Use this when the bug did not exist at some older commit. Bisect tests
the commits in between and halves the range each time, so 1,000 commits
take about 10 tests.

## Pick the ends

- Bad: usually `HEAD`, where you just saw it fail.
- Good: a commit where it worked, like the last release tag or a commit
  from before the bug was first reported. If unsure, try one far back.
  The script checks both ends first and stops if they are wrong.

## Write the test

- Keep it outside the repo, at an absolute path. Bisect checks out old
  commits, which do not have files you wrote today.
- Make it test only this bug, and fast. Not the whole suite.
- Exit 0 when the bug is absent, 1 when it is present.
- Exit 125 when this commit cannot answer, such as when the code the
  test needs does not exist yet. That commit is skipped, not judged.
- Make it reliable. A flaky test sends bisect to the wrong commit. For a
  bug that fails only sometimes, loop inside the test and fail if any
  run fails.

## Setup

The copy starts without installed packages or ignored files. Pass the
install or build with `--setup`, like `--setup "npm ci"`. If setup fails
at a commit, that commit is skipped.

## Reading the result

- One commit found: read its diff. It shows where the bug came in, not
  always where the cause is. Still follow the hypothesis steps.
- Several commits left (too many skipped): read their diffs together,
  or improve the test so fewer commits are skipped.
