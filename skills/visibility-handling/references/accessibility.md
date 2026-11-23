# Accessibility: WCAG 2.2 AA

Updated: 2026-11-23. WCAG 2.2 (W3C Recommendation, 2024-12-12).

The target is WCAG 2.2 level AA. Meeting it also meets 2.1 AA, which
US ADA Title II and today's EN 301 549 (EU Accessibility Act) use.

## Automated pass (step 7)

Run both on each page with `javascript_tool`. Paste the file's text,
or, to save the paste: copy `<skill dir>/assets/` into the folder the
local build serves (for example `dist/__vis/`; copy again after each
build), then run
`await (0,eval)(await (await fetch('/__vis/run_axe.js')).text())`.
Delete that folder in clean-up.

1. `assets/run_axe.js`: loads axe-core 4.14.1 from jsdelivr and runs the
   WCAG 2.0 to 2.2 A and AA rules.
   - `violations`: real failures (axe aims for no false positives).
   - `incomplete`: axe could not decide (often contrast over images or
     gradients). Look at each one yourself.
   - `{blocked: true}`: the page's Content-Security-Policy stopped the
     script. Write "axe: not checked yet" and rely on the probe. Ask
     before any CSP change; never use a CSP bypass.
2. `assets/a11y_probe.js`: what axe skips or what needs computed styles,
   plus a few axe basics for when axe is blocked. Each finding names its
   WCAG criterion and up to three example elements. Everything is a
   lead: open the element and confirm.
   - `focus-not-visible` needs window focus and keyboard mode: if
     `notChecked` says the window has no focus, click the page and run
     it again; if it says rings are hidden after a mouse click, press
     Tab once in the page and run it again. Or check by Tab in step 8.
   - `fake-control` is anything with a pointer cursor or `onclick` that
     is not a button or link. Confirm with the keyboard.
   - `small-target`: fine if it has 24 px of space around it.
3. Lighthouse or pa11y: only if already installed.

About 57% of issues by count (but only about 16 of 50 criteria) are
caught by tools. A clean run is the start, not the end.

## Browser pass (step 8)

Do it in the built-in browser on each changed screen:

- Keyboard: Tab from the address bar through the whole page. Every
  control is reached, in a sensible order, works with Enter or Space
  (Escape closes, arrows move in menus and tabs), and nothing traps
  focus (2.1.1, 2.1.2, 2.4.3).
- Focus is visible on every control (2.4.7) and not hidden under a
  sticky header or cookie banner (2.4.11).
- Names: `read_page` shows the accessibility tree. Every control has a
  name and role, and the name contains its visible label (2.5.3, 4.1.2).
- Zoom to 200% and resize to 320 px wide (`resize_window`): no lost
  content, no sideways scroll for text (1.4.4, 1.4.10).
- Contrast: 4.5:1 for text, 3:1 for large text and for control borders
  and icons (1.4.3, 1.4.11). Use axe's numbers; check text over images
  by eye.
- Forms: each field has a visible label; errors are in text, tied to
  the field, not shown by color only (3.3.1, 3.3.2, 1.4.1); personal
  fields have `autocomplete` (1.3.5); nothing asked twice in one flow
  (3.3.7); login has no puzzle-only step and allows paste (3.3.8).
- Dialogs: focus moves in, stays in, and returns to the opener on
  close. Neither script checks these, so by hand: press Shift+Tab from
  the first control (focus stays in); go to the next step inside the
  dialog (focus is not lost to the page); close it after its opener is
  gone (focus lands somewhere sensible, not the page top). Status messages ("added to cart") are announced with
  `role="status"` or `aria-live` (4.1.3).
- Motion: honors `prefers-reduced-motion`; anything moving over 5 s can
  be paused (2.2.2); nothing flashes more than 3 times a second (2.3.1).
- Dragging has a click alternative (2.5.7).
- Single-page apps: the tab title changes with each view (2.4.2).
  Neither script checks it: open two views and read `document.title`.
- Alt text says what the image means here; decorative images get
  `alt=""`.

## Fixing

- Native elements first: `<button>`, `<a href>`, `<label>`, `<main>`,
  `<nav>`. ARIA only when no native element does the job, and never on
  a native element that already has a name.
- A `div` with a click handler becomes a `<button type="button">`.
- Never hide a control from the tool (`aria-hidden`, `role="presentation"`)
  to quiet it. Never `outline: none` without a visible replacement.
- Contrast fixes that change brand colors: ask the human.
- After a fix: rerun the same check, then Tab through the control.

## The human's list (never claim these as checked)

- A real screen reader pass: VoiceOver on Mac and iPhone, NVDA on
  Windows.
- Captions and audio description quality.
- Whether the reading order and wording make sense to people.
