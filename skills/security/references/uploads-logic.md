# Uploads and business logic

Local only, with throwaway data, after the human's yes to writes.

## File uploads

Upload each of these as A, then open the file's URL as B and as nobody:

- an `.svg` holding `<script>` with a console marker;
- an `.html` file, and `a.png.html` (double extension);
- a PNG renamed to `.php` or `.jsp` (only matters if the server runs
  them);
- a real image sent with `Content-Type: text/html`;
- a file name with `../` in it, and one with `<x-sec>` in it;
- a file larger than any limit the app states (a few MB more, not GB).

A finding is any of these:
- the file is served from the app's own origin as HTML or SVG that runs
  script (check `Content-Type`; `Content-Disposition: attachment` or a
  separate files domain makes it safe);
- the name escapes the upload folder or overwrites another file;
- B or nobody can open A's private file;
- there is no size limit at all.

## Business logic

Start from the human's answer to "what must never happen here". Then
try, each as a single request:

- negative, zero, huge and fractional quantities and prices;
- a price, total, discount or role sent from the browser and trusted;
- the same coupon, gift card or invite used twice;
- steps skipped: jump straight to "confirm" or "download" without
  paying or verifying;
- limits split to slip under them (many small transfers, many free
  trials with `a+1@` style emails);
- actions on objects in the wrong state (refund a cancelled order).

## Races

Send the same one-time action twice at once (two coupon uses, two
withdrawals of the full balance). A small parallel burst is enough:

```bash
for i in 1 2 3 4 5; do curl -s -o /dev/null -w '%{http_code}\n' -X POST ... & done; wait
```

More than one success where only one is allowed is a finding. Keep it
to a handful of requests.
