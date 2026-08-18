from __future__ import annotations

from reportlab.lib import colors

INK = colors.HexColor("#111826")
MUTED = colors.HexColor("#586274")
FAINT = colors.HexColor("#8a93a3")
ACCENT = colors.HexColor("#2c5fa8")
POSITIVE = colors.HexColor("#1a7f5a")
RULE = colors.HexColor("#e0e6f0")
GRID = colors.HexColor("#eef2f8")
BAND = colors.HexColor("#f6f8fb")

BAND_FILL = colors.Color(0.173, 0.373, 0.659, alpha=0.16)

# The decision band. `PREPARE` is deliberately not the warning colour: being
# ready for the upper bound is capacity planning, not an alarm.
COMMIT = colors.HexColor("#1a7f5a")
PREPARE = colors.HexColor("#8a6d3b")
PLAN_FILL = colors.Color(0.102, 0.498, 0.353, alpha=0.12)
CHIP = colors.HexColor("#eef4f0")

# The tail of the risk ranking, below the cut. Grey rather than a second hue:
# they are the same measure as the bars above, just not where the week goes.
RISK_REST = colors.HexColor("#b9c0cc")
