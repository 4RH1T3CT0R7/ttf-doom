"""Glyph builder for TTDoom multi-bar display font.

Creates TrueType glyphs composed of multiple vertical rectangular contours
(bars).  The 'A' glyph uses 64 bars side by side, each a separate contour
with 4 on-curve points.  At render time the hinting program repositions
these points to draw the DOOM framebuffer columns.

Point layout per bar *i* (counter-clockwise winding):
    point 4*i + 0: bottom-left  (x0, 0)
    point 4*i + 1: bottom-right (x1, 0)
    point 4*i + 2: top-right    (x1, glyph_height)
    point 4*i + 3: top-left     (x0, glyph_height)
"""

from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib.tables._g_l_y_f import Glyph


def build_bar_glyph(
    num_bars: int = 64,
    glyph_width: int = 1000,
    glyph_height: int = 1000,
) -> Glyph:
    """Create a glyph with *num_bars* vertical rectangular contours.

    Each bar is a separate closed contour occupying an equal horizontal
    slice of the glyph advance width, with a small gap between adjacent
    bars so they remain distinct contours.

    Args:
        num_bars: Number of vertical bar contours to generate.
        glyph_width: Total horizontal extent in font units.
        glyph_height: Vertical extent (bar top) in font units.

    Returns:
        A compiled ``TTGlyph`` object ready for insertion into a ``glyf``
        table.
    """
    pen = TTGlyphPen(None)
    bar_total_width = glyph_width / num_bars
    gap = max(1, int(bar_total_width * 0.05))  # 5% gap between bars

    for i in range(num_bars):
        x0 = int(i * bar_total_width) + gap
        x1 = int((i + 1) * bar_total_width) - gap

        # Counter-clockwise winding (TrueType standard)
        pen.moveTo((x0, 0))
        pen.lineTo((x1, 0))
        pen.lineTo((x1, glyph_height))
        pen.lineTo((x0, glyph_height))
        pen.closePath()

    return pen.glyph()


def build_notdef_glyph(width: int = 500, height: int = 700) -> Glyph:
    """Create a minimal ``.notdef`` glyph.

    The ``.notdef`` glyph is a required placeholder in every TrueType font.
    It is drawn as a simple rectangle.

    Args:
        width: Horizontal extent in font units.
        height: Vertical extent in font units.

    Returns:
        A compiled ``TTGlyph`` object.
    """
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((width, 0))
    pen.lineTo((width, height))
    pen.lineTo((0, height))
    pen.closePath()
    return pen.glyph()
