# Browser acceptance audits

Harnesses that measure the running app in a real browser rather than asserting
on the code that draws it. Each one corresponds to acceptance criteria that
cannot be checked from unit tests: whether ink from two lines of text touches,
where an anchor actually lands, whether a bar overshoots its value mid-animation,
which focus ring a click actually produces.

Start the app first — they drive whatever is at `BASE` (default
`http://localhost:3000`):

```
npm run dev
node audits/a1.mjs         # no two lines of text touch, 320px to 2560px
node audits/track-a.mjs    # anchors, card measure, hero fold
node audits/a5.mjs         # chart geometry and captions stay inside the frame
node audits/track-b.mjs    # motion: budget, overshoot, reduced motion, frame cost
node audits/scale.mjs      # shell, nav and chart bounds at ten viewports
node audits/edges.mjs      # chart sequence, nav indicator, touch, keyboard, a11y
node audits/product.mjs    # wordmark, rails, motion inside the dashboard
node audits/header.mjs     # the collapse control at each breakpoint
node audits/bluebox.mjs    # what focus ring a click, drag, tap and Tab produce
node audits/reveal.mjs     # every section reveals when actually scrolled to
node audits/shots.mjs      # screenshots to audits/out-*.png (git-ignored)
```

`BASE=https://… node audits/a1.mjs` points them at a deploy instead.

## What each one is careful about

**a1.mjs** counts bands of pixel rows that carry ink, not line boxes. At a
leading below 1 the line boxes overlap by design while the glyphs still clear
each other, so measuring boxes reports failures that are not there. The
background is taken as the modal colour over the region — sampling one pixel
picks up a card border or one of the page's 48px grid lines and makes every row
look inked.

**track-b.mjs** measures the frame cost twice, once with the sequence running
and once with it disabled, and reports the difference. Scrolling the chart into
view repaints a grid background and a backdrop-blurred nav; attributing that to
the animation overstates it by roughly an order of magnitude.

**a5.mjs** reads rendered text boxes out of the live DOM. A caption's anchor
can sit inside the frame while the glyphs it anchors run outside it, and only
the browser knows how wide a word is once the mono face has loaded. The
geometry itself is covered at n = 8, 35 and 120 by `tests/demand-scape.test.ts`.

**bluebox.mjs** reports `:focus` and `:focus-visible` separately, because they
disagree exactly where the bug lived. An element with `tabindex` matches
`:focus` on a mouse click but not `:focus-visible`, so styling only the latter
leaves the click falling through to the browser's own ring.

**reveal.mjs** scrolls to each section before measuring. A full-page screenshot
resizes the viewport instead of scrolling, so `IntersectionObserver` never
fires and every revealed section photographs blank — an artifact that looks
exactly like content failing to appear.

**header.mjs** looks for the mobile navigation as a `[role="dialog"]` in a
portal, not as the inline `#app-navigation`. Below the rail breakpoint the two
are different elements.

## Known shortfall

`track-a.mjs` reports the step-card measure as PARTIAL. Those cards sit inside
a `.75fr / 1.55fr` section split with 32px of padding, so 18px copy reaches
about 32 characters a line at 1366px against a 45-character target. Closing it
needs a change to the section layout, the card padding, or the body size —
each a design decision rather than a defect fix.
