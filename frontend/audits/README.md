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
node audits/rail.mjs       # screenshots the left rail open and collapsed
node audits/bluebox.mjs    # what focus ring a click, drag, tap and Tab produce
node audits/reveal.mjs     # every section reveals when actually scrolled to
node audits/sections.mjs   # compare, accuracy, proof band, hero demo and its two product lines
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

**sections.mjs** samples the wipe rects and the bars frame by frame rather than
reading the timings the components asked for. The two disagree exactly where the
bugs live: a clip whose `transform-box` the browser did not honour still reports
the animation it was given while wiping from the wrong origin, and a bar that
overshoots its value does so between the keyframes rather than at them. It also
loads the page twice more — once under `prefers-reduced-motion`, once with
JavaScript switched off — because both of those paths render through CSS that
the normal path never reaches, and the failure they produce is a blank chart.

For the hero's self-demonstration it asserts that a still pointer stops the
walk, rather than asserting which week ends up under the cursor. The prisms are
an isometric projection and overlap, so the bar whose bounding box the pointer
is aimed at is often behind another one; the readout that comes back is then
the wrong week for the right reason. What the check is actually for is that the
walk stops when the visitor takes over, and a readout that does not advance for
four steps' worth of time says exactly that.

`aimAtForecast` exists for the same reason, plus one more: the chart sits low
enough in the hero that at 1366x768 only about a third of it is on screen, and
a pointer sent to a point below the fold hovers nothing while looking exactly
like a broken hover handler. It scrolls the chart in, then hit-tests candidate
bars with `elementFromPoint` and takes the first that resolves to itself. Call
it only once the build has settled — a bounding box read mid-animation is the
height the bar had partway up, not the height it is going to have.

For the chart's two product lines it reads the fills the browser computed
rather than the palette the component asked for, and requires the two rows to
share none of them. The rows overlap by design — that is what makes the drawing
read as depth — so two rows that resolve to the same ink are one silhouette
wearing two names, and nothing in the geometry can tell you that has happened.
It then checks that the two figures the readout splits a week into add up to
the total it quotes for that week, which is the claim the depth is making.

**header.mjs** looks for the mobile navigation as a `[role="dialog"]` in a
portal, not as the inline `#app-navigation`. Below the rail breakpoint the two
are different elements. It reads the chevron's direction off the computed
transform rather than the icon name, because the same icon is used for both
directions and only the rotation distinguishes them.

## Known shortfall

`track-a.mjs` reports the step-card measure as PARTIAL. Those cards sit inside
a `.75fr / 1.55fr` section split with 32px of padding, so 18px copy reaches
about 32 characters a line at 1366px against a 45-character target. Closing it
needs a change to the section layout, the card padding, or the body size —
each a design decision rather than a defect fix.
