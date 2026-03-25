"""Tests for the proof-of-concept font generator.

Validates that create_poc_font produces a valid .ttf with the expected
glyph outline, hinting tables, and SCFS instructions.
"""

import os
import sys
import tempfile

import pytest

# Ensure the project root is on sys.path so fontgen is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fontgen.poc_font import create_poc_font


@pytest.fixture(scope="module")
def poc_font_path() -> str:
    """Generate the POC font once per test module and return its path."""
    path = os.path.join(tempfile.gettempdir(), "poc_test_module.ttf")
    create_poc_font(path)
    return path


# ---------------------------------------------------------------------------
# File-level checks
# ---------------------------------------------------------------------------


def test_poc_font_creates_valid_ttf(poc_font_path: str) -> None:
    """Font file exists and is non-empty."""
    assert os.path.exists(poc_font_path)
    assert os.path.getsize(poc_font_path) > 0


# ---------------------------------------------------------------------------
# Table-level checks
# ---------------------------------------------------------------------------


def test_poc_font_has_hinting_tables(poc_font_path: str) -> None:
    """Font contains fpgm and prep hinting tables."""
    from fontTools.ttLib import TTFont

    font = TTFont(poc_font_path)
    assert "fpgm" in font, "fpgm table missing"
    assert "prep" in font, "prep table missing"


def test_poc_font_maxp_settings(poc_font_path: str) -> None:
    """maxp table has the required resource reservations."""
    from fontTools.ttLib import TTFont

    font = TTFont(poc_font_path)
    maxp = font["maxp"]
    assert maxp.maxStackElements == 256
    assert maxp.maxStorage == 64
    assert maxp.maxFunctionDefs == 8
    assert maxp.maxSizeOfInstructions == 512


# ---------------------------------------------------------------------------
# Glyph outline checks
# ---------------------------------------------------------------------------


def test_poc_font_glyph_has_4_points(poc_font_path: str) -> None:
    """Glyph 'A' is a single-contour rectangle with exactly 4 points."""
    from fontTools.ttLib import TTFont

    font = TTFont(poc_font_path)
    glyph = font["glyf"]["A"]
    assert glyph.numberOfContours == 1
    coords = glyph.coordinates
    assert len(coords) == 4, f"Expected 4 points, got {len(coords)}"


def test_poc_font_glyph_coordinates(poc_font_path: str) -> None:
    """Glyph 'A' outline matches the expected rectangle vertices."""
    from fontTools.ttLib import TTFont

    font = TTFont(poc_font_path)
    glyph = font["glyf"]["A"]
    coords = list(glyph.coordinates)
    expected = [(100, 0), (200, 0), (200, 800), (100, 800)]
    assert coords == expected, f"Expected {expected}, got {coords}"


# ---------------------------------------------------------------------------
# Instruction checks
# ---------------------------------------------------------------------------


def test_poc_font_glyph_has_instructions(poc_font_path: str) -> None:
    """Glyph 'A' carries a non-empty hinting program."""
    from fontTools.ttLib import TTFont

    font = TTFont(poc_font_path)
    glyph = font["glyf"]["A"]
    assert glyph.program is not None, "Glyph program is None"
    bytecode = glyph.program.getBytecode()
    assert len(bytecode) > 0, "Glyph bytecode is empty"


def test_poc_font_has_scfs_in_assembly(poc_font_path: str) -> None:
    """Glyph 'A' hinting program contains SCFS instructions."""
    from fontTools.ttLib import TTFont

    font = TTFont(poc_font_path)
    glyph = font["glyf"]["A"]
    asm = glyph.program.getAssembly()
    asm_text = "\n".join(asm)
    assert "SCFS" in asm_text, f"SCFS not found in assembly:\n{asm_text}"


def test_poc_font_has_svtca_in_assembly(poc_font_path: str) -> None:
    """Glyph 'A' hinting program sets the Y-axis vector via SVTCA."""
    from fontTools.ttLib import TTFont

    font = TTFont(poc_font_path)
    glyph = font["glyf"]["A"]
    asm = glyph.program.getAssembly()
    asm_text = "\n".join(asm)
    assert "SVTCA[0]" in asm_text, f"SVTCA[0] not found in assembly:\n{asm_text}"


def test_poc_font_targets_points_2_and_3(poc_font_path: str) -> None:
    """Glyph program pushes point indices 2 and 3 for SCFS."""
    from fontTools.ttLib import TTFont

    font = TTFont(poc_font_path)
    glyph = font["glyf"]["A"]
    bytecode = glyph.program.getBytecode()
    # PUSHW[] for value 2: 0xB8 0x00 0x02
    # PUSHW[] for value 3: 0xB8 0x00 0x03
    assert bytes([0xB8, 0x00, 0x02]) in bytes(bytecode), "Point index 2 not found in bytecode"
    assert bytes([0xB8, 0x00, 0x03]) in bytes(bytecode), "Point index 3 not found in bytecode"


# ---------------------------------------------------------------------------
# Name table checks
# ---------------------------------------------------------------------------


def test_poc_font_name(poc_font_path: str) -> None:
    """Font family name is 'DoomPOC'."""
    from fontTools.ttLib import TTFont

    font = TTFont(poc_font_path)
    name_records = {r.nameID: str(r) for r in font["name"].names}
    # nameID 1 = Font Family
    assert "DoomPOC" in name_records.get(1, ""), f"Family name mismatch: {name_records}"
