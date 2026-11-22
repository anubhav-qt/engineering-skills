# Testing what the user sees

Use the built-in browser first (the app's own browser pane). Only if
there is none, use an outside real browser (a browser extension, or a
browser driven by Playwright or similar).

Start the app, open the changed screen, and check every changed input
and button. Watch the console for errors the whole time.

## Every text input

- Empty, and only spaces.
- One character, and far too long (paste 10,000 characters).
- Odd characters: emoji, accents, right-to-left text, quotes `' "`,
  `<b>` and `<script>` tags, a backslash, a new line pasted in.
- The edges of any limit: one under, exactly at, one over.

## Every number input

- 0, negative, a decimal, a huge number, letters, an empty value.

## Every button and link

- Click once and check the result.
- Double click and click fast many times: no double submit, no double
  charge, no duplicate rows.
- Disabled states: it really does nothing while disabled, and it turns
  back on when it should.
- Use it with the keyboard only (Tab, Enter, Space, Escape).

## The whole flow

- Refresh and press back in the middle of the flow.
- A slow or failed request: the user sees a clear error and can try
  again.
- A narrow phone-width window: nothing cut off, nothing overlapping.
- Light and dark mode, if the app has both.

Write down each check and what happened. Anything you could not try goes
in the report as "not checked yet".
