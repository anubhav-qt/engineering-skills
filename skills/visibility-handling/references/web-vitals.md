# Core Web Vitals, light

Updated: 2026-11-23. Thresholds from web.dev as reported by several
sources; not rechecked on web.dev itself this round.

- Good, at the 75th percentile of real visits: LCP (largest content
  shown) 2.5 s or less, INP (reaction to clicks and keys) 200 ms or
  less, CLS (layout jumping) 0.1 or less. INP replaced FID in 2024.
- `a11y_probe.js` returns lab LCP and CLS for the page as loaded on this
  machine. Open the page fresh (navigate, then run the probe) so the
  numbers cover the load. They are lab numbers: a fast laptop on
  localhost is not a phone on a train. Report them as "lab, this
  machine". A null LCP (a hidden pane, or no large content): write
  "LCP: not checked yet".
- INP needs real interactions; say "INP: field only, not checked".
- Lighthouse: only if already installed, against the production build.
- PageSpeed Insights and the CrUX API give real-user numbers, but only
  for a public deployed URL with enough traffic, and they send the URL
  to Google. Ask first.
- Common fixes, if the numbers are bad: size images and embeds (stops
  CLS), preload or server-render the largest content (LCP), break up
  long scripts (INP). Deep work goes to feature-test's profiling.
