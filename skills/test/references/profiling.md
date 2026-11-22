# Profiling

Profile only when the change can make things slower: a loop over data, a
database query, a file or network call, startup, or a path that runs on
every request. Otherwise skip it and say why.

## How to measure

1. Measure before you change anything. Keep that number.
2. Use data the size and shape of real data. Ten rows hide what ten
   million rows show.
3. Warm up first, so one-time startup work does not fill the numbers.
4. Run it at least 5 times and look at the spread, not one run.
5. Compare old and new on the same machine, in the same run if you can.
   Shared CI machines are too noisy for absolute numbers.
6. Use the language's real profiler to find where time goes (cProfile
   or py-spy for Python, the browser's Performance tab, `--prof` or
   clinic for Node, pprof for Go). Fix the biggest cost first.
7. Measure again after the fix, the same way.

## Watch out for

- Database: a query inside a loop (one query per row), a missing index,
  loading whole tables when one page is needed.
- A cold cache in production when your test had a warm one.
- A benchmark the compiler can skip because its result is never used.
- Tiny benchmarks that look great alone and change nothing end to end.
- The profiler itself slowing the code down.

## What goes in the report

The command you ran, the before and after numbers with their spread, and
the data size you used.
