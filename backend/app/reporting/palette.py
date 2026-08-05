"""
The product's own colours, for the things it prints.

Kept here rather than beside each drawing so a report and the screen it came
from stay recognisably the same product. These mirror the `--ink`/`--accent`
tokens in `frontend/app/globals.css`; changing one without the other is what
makes an export look like it came from somewhere else.
"""

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

#: The confidence band. Translucent so the line stays readable through it.
BAND_FILL = colors.Color(0.173, 0.373, 0.659, alpha=0.16)
