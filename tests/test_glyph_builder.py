"""Tests for the multi-bar glyph builder.

Validates that build_bar_glyph produces glyphs with the correct number
of contours, points, and coordinate ranges, and that build_notdef_glyph
creates a valid placeholder glyph.
"""

import os
import sys

import pytest

# Ensure the project root is on sys.path so fontgen is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fontgen.glyph_builder import build_bar_glyph, build_notdef_glyph


# ---------------------------------------------------------------------------
# Contour count tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("num_bars", [8, 32, 64])
def test_bar_glyph_contour_count(num_bars: int) -> None:
    """Glyph has exactly num_bars contours."""
    glyph = build_bar_glyph(num_bars=num_bars)
    assert glyph.numberOfContours == num_bars, (
        f"Expected {num_bars} contours, got {glyph.numberOfContours}"
    )


def test_64_bar_glyph_has_64_contours() -> None:
    """Default 64-bar glyph has exactly 64 contours."""
    glyph = build_bar_glyph()
    assert glyph.numberOfContours == 64


# ---------------------------------------------------------------------------
# Point count tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("num_bars", [8, 32, 64])
def test_bar_glyph_point_count(num_bars: int) -> None:
    """Glyph has exactly num_bars * 4 on-curve points."""
    glyph = build_bar_glyph(num_bars=num_bars)
    expected = num_bars * 4
    actual = len(glyph.coordinates)
    assert actual == expected, f"Expected {expected} points, got {actual}"


def test_64_bar_glyph_has_256_points() -> None:
    """Default 64-bar glyph has exactly 256 on-curve points (64 * 4)."""
    glyph = build_bar_glyph()
    assert len(glyph.coordinates) == 256


# ---------------------------------------------------------------------------
# All points are on-curve
# ---------------------------------------------------------------------------


def test_all_points_on_curve() -> None:
    """Every point in the bar glyph should be on-curve (flag bit 0 set)."""
    glyph = build_bar_glyph(num_bars=8)
    for idx, flag in enumerate(glyph.flags):
        assert flag & 0x01, f"Point {idx} is off-curve (flag={flag:#04x})"


# ---------------------------------------------------------------------------
# Coordinate correctness tests
# ---------------------------------------------------------------------------


def test_bars_have_correct_y_coordinates() -> None:
    """All bar points have y=0 (bottom) or y=glyph_height (top)."""
    height = 1000
    glyph = build_bar_glyph(num_bars=8, glyph_height=height)
    coords = list(glyph.coordinates)
    for i in range(0, len(coords), 4):
        # Points 0,1 are bottom (y=0); points 2,3 are top (y=height)
        assert coords[i][1] == 0, f"Bar {i // 4} bottom-left y != 0"
        assert coords[i + 1][1] == 0, f"Bar {i // 4} bottom-right y != 0"
        assert coords[i + 2][1] == height, f"Bar {i // 4} top-right y != {height}"
        assert coords[i + 3][1] == height, f"Bar {i // 4} top-left y != {height}"


def test_bars_non_overlapping_x() -> None:
    """Adjacent bars must not overlap horizontally."""
    glyph = build_bar_glyph(num_bars=64, glyph_width=1000)
    coords = list(glyph.coordinates)

    prev_x1 = -1
    for i in range(0, len(coords), 4):
        x0 = coords[i][0]       # bottom-left x
        x1 = coords[i + 1][0]   # bottom-right x
        assert x0 < x1, f"Bar {i // 4}: left ({x0}) >= right ({x1})"
        assert x0 > prev_x1, (
            f"Bar {i // 4}: left ({x0}) overlaps previous right ({prev_x1})"
        )
        prev_x1 = x1


def test_bars_within_glyph_width() -> None:
    """All bar x-coordinates stay within [0, glyph_width]."""
    width = 1000
    glyph = build_bar_glyph(num_bars=64, glyph_width=width)
    coords = list(glyph.coordinates)
    for i, (x, _y) in enumerate(coords):
        assert 0 <= x <= width, (
            f"Point {i}: x={x} outside [0, {width}]"
        )


def test_custom_dimensions() -> None:
    """Custom glyph_width and glyph_height are respected."""
    glyph = build_bar_glyph(num_bars=4, glyph_width=2000, glyph_height=500)
    coords = list(glyph.coordinates)
    # All y-tops should be 500
    for i in range(0, len(coords), 4):
        assert coords[i + 2][1] == 500
        assert coords[i + 3][1] == 500
    # All x-values should be within [0, 2000]
    for x, _y in coords:
        assert 0 <= x <= 2000


# ---------------------------------------------------------------------------
# Point ordering per bar
# ---------------------------------------------------------------------------


def test_point_order_per_bar() -> None:
    """Each bar has points in BL, BR, TR, TL order."""
    glyph = build_bar_glyph(num_bars=4, glyph_width=400, glyph_height=100)
    coords = list(glyph.coordinates)
    for bar_idx in range(4):
        base = bar_idx * 4
        bl = coords[base]
        br = coords[base + 1]
        tr = coords[base + 2]
        tl = coords[base + 3]

        # Bottom-left: smaller x, y=0
        assert bl[1] == 0
        # Bottom-right: larger x, y=0
        assert br[1] == 0
        assert br[0] > bl[0]
        # Top-right: same x as BR, y=height
        assert tr[0] == br[0]
        assert tr[1] == 100
        # Top-left: same x as BL, y=height
        assert tl[0] == bl[0]
        assert tl[1] == 100


# ---------------------------------------------------------------------------
# .notdef glyph tests
# ---------------------------------------------------------------------------


def test_notdef_glyph_has_1_contour() -> None:
    """.notdef glyph has exactly 1 contour."""
    glyph = build_notdef_glyph()
    assert glyph.numberOfContours == 1


def test_notdef_glyph_has_4_points() -> None:
    """.notdef glyph has exactly 4 points."""
    glyph = build_notdef_glyph()
    assert len(glyph.coordinates) == 4


def test_notdef_glyph_coordinates() -> None:
    """.notdef glyph matches expected rectangle vertices."""
    glyph = build_notdef_glyph(width=500, height=700)
    coords = list(glyph.coordinates)
    expected = [(0, 0), (500, 0), (500, 700), (0, 700)]
    assert coords == expected, f"Expected {expected}, got {coords}"


def test_notdef_custom_dimensions() -> None:
    """.notdef with custom dimensions produces correct coordinates."""
    glyph = build_notdef_glyph(width=300, height=400)
    coords = list(glyph.coordinates)
    expected = [(0, 0), (300, 0), (300, 400), (0, 400)]
    assert coords == expected
