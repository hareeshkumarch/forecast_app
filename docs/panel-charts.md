# Charts for a panel run

What to draw once an upload resolves into many series, and what not to. Every
chart below is tied to a question somebody actually asks at that point in the
flow, and to the field in `app/schema/` that answers it. A chart with no
question above it does not get built.

## The palette constraint, first

`lib/chart-theme.ts` ships `categoricalPalette` as `navy, accent, teal, sand,
textSecondary`. Validated against the light surface, that order fails on two
counts that matter here:

- `accent #287b59` against `teal #5a9278` is ΔE 9.3 for **normal** colour
  vision, under the floor of 15. Two adjacent series in that order are hard to
  tell apart for everybody, not only for colour-blind readers.
- `sand #a7b9aa` sits at 1.99:1 against the surface, under 3:1.

For anything new, use three slots in this order — `accent`, `gold`,
`textSecondary` — which clears the lightness band, the normal-vision floor and
contrast. Its worst adjacent pair is ΔE 7.2 under protanopia, which is legal
only with a second encoding, so **direct labels are mandatory**, not optional.
`sand` is available as a fourth slot only with a visible label. Past four
series: small multiples, or fold the tail into "Other". The brand is
deliberately desaturated, so identity must never rest on hue alone.

## 1. Before the run — is the file read correctly?

Answered by `MappingProposal.candidates` and `.warnings`.

**Role confidence bars.** One horizontal bar group per role (date, target,
dimension), a bar per candidate column, x = confidence 0–1. Chosen column in
`accent`, runners-up in `textSecondary`, every bar directly labelled with the
column name.

The bar length is not the point — *the gap between the top two* is. That gap is
the whole decision the layer makes, and it is invisible in a table of numbers.
Draw the `MIN_MARGIN` threshold as a reference line so a contested pair is
visible as an overlap rather than as a warning to read. When
`needs_confirmation` is set, this chart is the confirmation screen.

Not a chart: the row count, series count, detected frequency and layout. Four
numbers with no comparison — a stat strip, not a plot.

## 2. Before the run — what shape is the data in?

Answered by `ValidationReport`.

**Series status bar.** One stacked horizontal bar, `ok` / `warn` / `reject`,
using the reserved status colours with an icon and a count on each segment. One
bar rather than a pie: three parts, and next month's upload wants comparing
against this one, which stacked bars allow and pies do not.

**Reason codes, sorted.** Horizontal bars, one per reason code
(`short_history`, `intermittent_demand`, `calendar_gaps`, `outliers`,
`negative_values`…), x = number of series carrying it, longest first, single
hue. This is the "what is wrong with this file" chart, and sorted bars are the
right form because the question is rank, not trend.

**History-length histogram.** x = observations per series, y = count of series,
with `required_history` drawn as a vertical rule and everything left of it in
the warning status colour. It shows at a glance how much of the panel routes to
a baseline instead of a fitted model — the number that most determines what the
run is worth.

**Coverage grid.** Rows = series ordered by first period, columns = periods,
cell = has data / gap / zero. A sequential single-hue ramp for magnitude, with
gaps as the surface colour so they read as holes. Up to ~200 series this is the
single most informative panel chart in the product: ragged starts,
mid-history gaps and intermittency all show up as texture. Above 200 series,
aggregate rows to the parent level rather than shrinking cells below 3px.

## 3. After the run — where should I look?

Answered by `FanOutResult` and the stored `ForecastSeries` rows.

**Accuracy against size.** Scatter: x = forecast total (log), y = wMAPE, dot
area = value at risk, dot colour = route (`model` vs `fallback`, two slots,
both direct-labelled). Answers "is my error in the series that matter or in the
long tail" in one look; the sorted table answers it one row at a time. Label
the worst five points and leave the rest to hover.

**Small multiples of the top N.** A 3-across grid of history-plus-forecast
sparklines for the top 12 by value at risk, shared y-scale within a row,
labelled with the series id. Twelve series on one axis is spaghetti; twelve
small charts is a scan.

**Model mix.** Stacked bars, one per winning model, split by route. Tells you
whether the fallback path is quietly doing most of the work — which is the
signal that the history requirement, not the models, is what needs attention.

**Hierarchy contribution over time.** Stacked area of the parent levels from
`FanOutResult.parents`, at most four bands plus "Other". Only when the mix
moving over time is the question; for a single horizon total, a sorted bar
beats both a treemap and a pie.

**Per-series forecast fan.** The existing `ForecastVsActual`, reused per
series. One change: a fallback-routed series has no interval, so it must draw
as a dashed line with a "baseline" chip — never as a band of zero width, which
reads as certainty.

## What not to draw

- No dual-axis charts. Two measures at different scales are two charts.
- No pie beyond two slices — including the existing breakdown pie, which should
  become a sorted bar.
- No line-per-series above about eight lines. Small multiples, or a fan of
  quantile bands.
- No number on every point. Label the extremes and the last point; leave the
  rest to hover.
- No status colour reused as a series colour. `warning` and `negative` mean
  state, everywhere, or they mean nothing.
