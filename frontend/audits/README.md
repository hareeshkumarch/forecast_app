# Landing-page acceptance audits

Four harnesses that measure the landing page in a real browser rather than
asserting on the code that draws it. Each one corresponds to acceptance
criteria that cannot be checked from unit tests: whether ink from two lines of
text touches, where an anchor actually lands, whether a bar overshoots its
value mid-animation.

Start the app first — they drive whatever is at `BASE` (default
`http://localhost:3000`):

```
npm run dev
node audits/a1.mjs         # no two lines of text touch, 320px to 2560px
node audits/track-a.mjs    # anchors, card measure, hero fold
node audits/a5.mjs         # chart geometry and captions stay inside the frame
node audits/track-b.mjs    # motion: budget, overshoot, reduced motion, frame cost
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

## Known shortfall

`track-a.mjs` reports the step-card measure as PARTIAL. Those cards sit inside
a `.75fr / 1.55fr` section split with 32px of padding, so 18px copy reaches
about 32 characters a line at 1366px against a 45-character target. Closing it
needs a change to the section layout, the card padding, or the body size —
each a design decision rather than a defect fix.
