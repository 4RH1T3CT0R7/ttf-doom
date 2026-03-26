"""Tests for the DOOM font builder.

Validates that build_doom_font produces a valid variable TrueType font
with the expected axes, glyph geometry, hinting programs, and maxp
resource reservations.
"""

import os
import sys
import tempfile

import pytest

# Ensure the project root is on sys.path so fontgen is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fontTools.ttLib import TTFont
from fontTools.ttLib.tables.ttProgram import Program

from fontgen.font_builder import DEFAULT_AXES, build_doom_font


# ---------------------------------------------------------------------------
# Minimal assembly fixtures
# ---------------------------------------------------------------------------

MINIMAL_FPGM = ["PUSHB[] 0", "SRP0[]"]
MINIMAL_PREP = ["SVTCA[0]"]
MINIMAL_GLYPH = ["SVTCA[0]", "PUSHB[] 0", "PUSHB[] 0", "SCFS[]"]


@pytest.fixture(scope="module")
def doom_font_path() -> str:
    """Build the DOOM font once per test module with minimal assembly."""
    path = os.path.join(tempfile.gettempdir(), "doom_builder_test.ttf")
    build_doom_font(
        fpgm_asm=MINIMAL_FPGM,
        prep_asm=MINIMAL_PREP,
        glyph_asm=MINIMAL_GLYPH,
        output_path=path,
    )
    return path


# ---------------------------------------------------------------------------
# File-level checks
# ---------------------------------------------------------------------------


def test_creates_valid_ttf(doom_font_path: str) -> None:
    """Font file exists and is non-empty."""
    assert os.path.exists(doom_font_path)
    assert os.path.getsize(doom_font_path) > 0


def test_return_value_matches_path() -> None:
    """build_doom_font returns the output path it was given."""
    path = os.path.join(tempfile.gettempdir(), "doom_return_test.ttf")
    result = build_doom_font(
        fpgm_asm=MINIMAL_FPGM,
        prep_asm=MINIMAL_PREP,
        glyph_asm=MINIMAL_GLYPH,
        output_path=path,
    )
    assert result == path


def test_font_reloadable(doom_font_path: str) -> None:
    """Font can be reloaded by TTFont without errors."""
    font = TTFont(doom_font_path)
    assert "glyf" in font
    assert "fvar" in font
    font.close()


# ---------------------------------------------------------------------------
# fvar axis checks
# ---------------------------------------------------------------------------


def test_has_fvar_with_5_axes(doom_font_path: str) -> None:
    """Font contains fvar with the 5 default axes."""
    font = TTFont(doom_font_path)
    assert "fvar" in font, "fvar table missing"
    axes = font["fvar"].axes
    assert len(axes) == 5, f"Expected 5 axes, got {len(axes)}"


def test_fvar_axis_tags(doom_font_path: str) -> None:
    """fvar axis tags match DEFAULT_AXES."""
    font = TTFont(doom_font_path)
    tags = [a.axisTag for a in font["fvar"].axes]
    expected_tags = [tag for tag, *_ in DEFAULT_AXES]
    assert tags == expected_tags, f"Expected {expected_tags}, got {tags}"


def test_fvar_axis_ranges(doom_font_path: str) -> None:
    """Each axis has the correct min/default/max values."""
    font = TTFont(doom_font_path)
    for axis_obj, (tag, mn, df, mx, _name) in zip(
        font["fvar"].axes, DEFAULT_AXES
    ):
        assert axis_obj.axisTag == tag
        assert axis_obj.minValue == mn, f"{tag} minValue mismatch"
        assert axis_obj.defaultValue == df, f"{tag} defaultValue mismatch"
        assert axis_obj.maxValue == mx, f"{tag} maxValue mismatch"


def test_custom_axes() -> None:
    """Custom axis definitions are applied correctly."""
    custom_axes = [
        ("XPOS", 0, 500, 1000, "X Position"),
        ("YPOS", 0, 500, 1000, "Y Position"),
    ]
    path = os.path.join(tempfile.gettempdir(), "doom_custom_axes.ttf")
    build_doom_font(
        fpgm_asm=MINIMAL_FPGM,
        prep_asm=MINIMAL_PREP,
        glyph_asm=MINIMAL_GLYPH,
        output_path=path,
        axes=custom_axes,
    )
    font = TTFont(path)
    axes = font["fvar"].axes
    assert len(axes) == 2
    assert axes[0].axisTag == "XPOS"
    assert axes[1].axisTag == "YPOS"


# ---------------------------------------------------------------------------
# gvar checks
# ---------------------------------------------------------------------------


def test_has_gvar_table(doom_font_path: str) -> None:
    """Font contains a gvar table."""
    font = TTFont(doom_font_path)
    assert "gvar" in font, "gvar table missing"


def test_gvar_has_entries_for_both_glyphs(doom_font_path: str) -> None:
    """gvar has variation entries for both .notdef and A."""
    font = TTFont(doom_font_path)
    variations = font["gvar"].variations
    assert ".notdef" in variations, "No gvar entry for .notdef"
    assert "A" in variations, "No gvar entry for A"


# ---------------------------------------------------------------------------
# Glyph geometry checks
# ---------------------------------------------------------------------------


def test_glyph_a_has_64_contours(doom_font_path: str) -> None:
    """Glyph 'A' has 64 contours (one per bar)."""
    font = TTFont(doom_font_path)
    glyph = font["glyf"]["A"]
    assert glyph.numberOfContours == 64, (
        f"Expected 64 contours, got {glyph.numberOfContours}"
    )


def test_glyph_a_has_256_points(doom_font_path: str) -> None:
    """Glyph 'A' has 256 on-curve points (64 bars * 4 points)."""
    font = TTFont(doom_font_path)
    glyph = font["glyf"]["A"]
    assert len(glyph.coordinates) == 256, (
        f"Expected 256 points, got {len(glyph.coordinates)}"
    )


def test_custom_num_bars() -> None:
    """Font built with custom num_bars has correct contour count."""
    path = os.path.join(tempfile.gettempdir(), "doom_8bars.ttf")
    build_doom_font(
        fpgm_asm=MINIMAL_FPGM,
        prep_asm=MINIMAL_PREP,
        glyph_asm=MINIMAL_GLYPH,
        output_path=path,
        num_bars=8,
    )
    font = TTFont(path)
    glyph = font["glyf"]["A"]
    assert glyph.numberOfContours == 8
    assert len(glyph.coordinates) == 32


# ---------------------------------------------------------------------------
# Hinting table checks
# ---------------------------------------------------------------------------


def test_has_fpgm_and_prep(doom_font_path: str) -> None:
    """Font contains fpgm and prep hinting tables."""
    font = TTFont(doom_font_path)
    assert "fpgm" in font, "fpgm table missing"
    assert "prep" in font, "prep table missing"


def test_glyph_has_instructions(doom_font_path: str) -> None:
    """Glyph 'A' has a non-empty hinting program."""
    font = TTFont(doom_font_path)
    glyph = font["glyf"]["A"]
    assert glyph.program is not None, "Glyph program is None"
    bytecode = glyph.program.getBytecode()
    assert len(bytecode) > 0, "Glyph bytecode is empty"


def test_assembly_roundtrip(doom_font_path: str) -> None:
    """Assembly -> bytecode -> assembly round-trips correctly."""
    font = TTFont(doom_font_path)
    glyph = font["glyf"]["A"]

    original_asm = glyph.program.getAssembly()
    bytecode = glyph.program.getBytecode()

    roundtrip = Program()
    roundtrip.fromBytecode(bytecode)
    roundtrip_asm = roundtrip.getAssembly()

    def strip_comments(lines: list[str]) -> list[str]:
        return [line.split("/*")[0].strip() for line in lines]

    assert strip_comments(original_asm) == strip_comments(roundtrip_asm)


def test_empty_assembly_omits_tables() -> None:
    """When assembly lists are empty, the corresponding tables are absent."""
    path = os.path.join(tempfile.gettempdir(), "doom_no_asm.ttf")
    build_doom_font(
        fpgm_asm=[],
        prep_asm=[],
        glyph_asm=[],
        output_path=path,
    )
    font = TTFont(path)
    assert "fpgm" not in font, "fpgm should be absent with empty assembly"
    assert "prep" not in font, "prep should be absent with empty assembly"


# ---------------------------------------------------------------------------
# maxp checks
# ---------------------------------------------------------------------------


def test_maxp_values(doom_font_path: str) -> None:
    """maxp resource reservations match the defaults."""
    font = TTFont(doom_font_path)
    maxp = font["maxp"]
    assert maxp.maxStackElements == 256
    assert maxp.maxStorage == 4096
    assert maxp.maxFunctionDefs == 256
    assert maxp.maxSizeOfInstructions == 65535


def test_custom_maxp_values() -> None:
    """Custom maxp values are applied correctly."""
    path = os.path.join(tempfile.gettempdir(), "doom_custom_maxp.ttf")
    build_doom_font(
        fpgm_asm=MINIMAL_FPGM,
        prep_asm=MINIMAL_PREP,
        glyph_asm=MINIMAL_GLYPH,
        output_path=path,
        max_storage=8192,
        max_funcs=512,
        max_stack=1024,
    )
    font = TTFont(path)
    maxp = font["maxp"]
    assert maxp.maxStackElements == 1024
    assert maxp.maxStorage == 8192
    assert maxp.maxFunctionDefs == 512


# ---------------------------------------------------------------------------
# Name table checks
# ---------------------------------------------------------------------------


def test_font_family_name(doom_font_path: str) -> None:
    """Font family name is 'DoomFont'."""
    font = TTFont(doom_font_path)
    name_records = {r.nameID: str(r) for r in font["name"].names}
    assert "DoomFont" in name_records.get(1, ""), (
        f"Family name mismatch: {name_records}"
    )


def test_custom_font_name() -> None:
    """Custom font name is applied correctly."""
    path = os.path.join(tempfile.gettempdir(), "doom_custom_name.ttf")
    build_doom_font(
        fpgm_asm=MINIMAL_FPGM,
        prep_asm=MINIMAL_PREP,
        glyph_asm=MINIMAL_GLYPH,
        output_path=path,
        font_name="MyDoomFont",
    )
    font = TTFont(path)
    name_records = {r.nameID: str(r) for r in font["name"].names}
    assert "MyDoomFont" in name_records.get(1, "")
