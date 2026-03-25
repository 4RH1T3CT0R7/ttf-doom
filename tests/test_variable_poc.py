"""Tests for the variable font proof-of-concept generator.

Validates that create_variable_poc_font produces a valid variable .ttf with
the expected fvar / gvar tables, glyph outline, and hinting instructions
that read the MOVE axis via GETVARIATION[].
"""

import os
import sys
import tempfile

import pytest

# Ensure the project root is on sys.path so fontgen is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fontgen.variable_poc import create_variable_poc_font


@pytest.fixture(scope="module")
def var_poc_font_path() -> str:
    """Generate the variable POC font once per test module."""
    path = os.path.join(tempfile.gettempdir(), "var_poc_test_module.ttf")
    create_variable_poc_font(path)
    return path


# ---------------------------------------------------------------------------
# File-level checks
# ---------------------------------------------------------------------------


def test_creates_valid_ttf(var_poc_font_path: str) -> None:
    """Font file exists and is non-empty."""
    assert os.path.exists(var_poc_font_path)
    assert os.path.getsize(var_poc_font_path) > 0


def test_return_value_matches_path() -> None:
    """create_variable_poc_font returns the output path it was given."""
    path = os.path.join(tempfile.gettempdir(), "var_poc_return_test.ttf")
    result = create_variable_poc_font(path)
    assert result == path


# ---------------------------------------------------------------------------
# fvar table checks
# ---------------------------------------------------------------------------


def test_has_fvar_table(var_poc_font_path: str) -> None:
    """Font contains an fvar (font variations) table."""
    from fontTools.ttLib import TTFont

    font = TTFont(var_poc_font_path)
    assert "fvar" in font, "fvar table missing"


def test_fvar_has_move_axis(var_poc_font_path: str) -> None:
    """fvar defines exactly one axis with tag 'MOVE'."""
    from fontTools.ttLib import TTFont

    font = TTFont(var_poc_font_path)
    axes = font["fvar"].axes
    assert len(axes) == 1, f"Expected 1 axis, got {len(axes)}"
    assert axes[0].axisTag == "MOVE"


def test_fvar_axis_range(var_poc_font_path: str) -> None:
    """MOVE axis has min=0, default=500, max=1000."""
    from fontTools.ttLib import TTFont

    font = TTFont(var_poc_font_path)
    axis = font["fvar"].axes[0]
    assert axis.minValue == 0
    assert axis.defaultValue == 500
    assert axis.maxValue == 1000


# ---------------------------------------------------------------------------
# gvar table checks
# ---------------------------------------------------------------------------


def test_has_gvar_table(var_poc_font_path: str) -> None:
    """Font contains a gvar (glyph variations) table."""
    from fontTools.ttLib import TTFont

    font = TTFont(var_poc_font_path)
    assert "gvar" in font, "gvar table missing"


def test_gvar_has_variation_for_glyph_a(var_poc_font_path: str) -> None:
    """gvar contains at least one variation entry for glyph 'A'."""
    from fontTools.ttLib import TTFont

    font = TTFont(var_poc_font_path)
    variations = font["gvar"].variations
    assert "A" in variations, "No gvar entry for glyph A"
    assert len(variations["A"]) >= 1, "gvar entry for A has no variations"


def test_gvar_variation_references_move_axis(var_poc_font_path: str) -> None:
    """The gvar variation for 'A' references the MOVE axis."""
    from fontTools.ttLib import TTFont

    font = TTFont(var_poc_font_path)
    variation = font["gvar"].variations["A"][0]
    assert "MOVE" in variation.axes, "MOVE axis not referenced in gvar tuple"


# ---------------------------------------------------------------------------
# Glyph outline checks
# ---------------------------------------------------------------------------


def test_glyph_has_4_points(var_poc_font_path: str) -> None:
    """Glyph 'A' is a single-contour rectangle with exactly 4 points."""
    from fontTools.ttLib import TTFont

    font = TTFont(var_poc_font_path)
    glyph = font["glyf"]["A"]
    assert glyph.numberOfContours == 1
    coords = glyph.coordinates
    assert len(coords) == 4, f"Expected 4 points, got {len(coords)}"


def test_glyph_coordinates(var_poc_font_path: str) -> None:
    """Glyph 'A' outline matches the expected rectangle vertices."""
    from fontTools.ttLib import TTFont

    font = TTFont(var_poc_font_path)
    glyph = font["glyf"]["A"]
    coords = list(glyph.coordinates)
    expected = [(100, 0), (200, 0), (200, 800), (100, 800)]
    assert coords == expected, f"Expected {expected}, got {coords}"


# ---------------------------------------------------------------------------
# Hinting tables checks
# ---------------------------------------------------------------------------


def test_has_fpgm_and_prep(var_poc_font_path: str) -> None:
    """Font contains fpgm and prep hinting tables."""
    from fontTools.ttLib import TTFont

    font = TTFont(var_poc_font_path)
    assert "fpgm" in font, "fpgm table missing"
    assert "prep" in font, "prep table missing"


def test_maxp_settings(var_poc_font_path: str) -> None:
    """maxp table has the required resource reservations."""
    from fontTools.ttLib import TTFont

    font = TTFont(var_poc_font_path)
    maxp = font["maxp"]
    assert maxp.maxStackElements == 256
    assert maxp.maxStorage == 64
    assert maxp.maxFunctionDefs == 8
    assert maxp.maxSizeOfInstructions == 1024


# ---------------------------------------------------------------------------
# Glyph instruction checks
# ---------------------------------------------------------------------------


def test_glyph_has_instructions(var_poc_font_path: str) -> None:
    """Glyph 'A' carries a non-empty hinting program."""
    from fontTools.ttLib import TTFont

    font = TTFont(var_poc_font_path)
    glyph = font["glyf"]["A"]
    assert glyph.program is not None, "Glyph program is None"
    bytecode = glyph.program.getBytecode()
    assert len(bytecode) > 0, "Glyph bytecode is empty"


def test_assembly_contains_getvariation(var_poc_font_path: str) -> None:
    """Glyph program uses GETVARIATION to read the axis value."""
    from fontTools.ttLib import TTFont

    font = TTFont(var_poc_font_path)
    glyph = font["glyf"]["A"]
    asm = glyph.program.getAssembly()
    asm_text = " ".join(asm)
    assert "GETVARIATION" in asm_text, (
        f"GETVARIATION not found in assembly:\n{asm_text}"
    )


def test_assembly_contains_scfs(var_poc_font_path: str) -> None:
    """Glyph program uses SCFS to reposition points."""
    from fontTools.ttLib import TTFont

    font = TTFont(var_poc_font_path)
    glyph = font["glyf"]["A"]
    asm = glyph.program.getAssembly()
    asm_text = " ".join(asm)
    assert "SCFS" in asm_text, f"SCFS not found in assembly:\n{asm_text}"


def test_assembly_contains_mppem(var_poc_font_path: str) -> None:
    """Glyph program reads ppem for proper scaling."""
    from fontTools.ttLib import TTFont

    font = TTFont(var_poc_font_path)
    glyph = font["glyf"]["A"]
    asm = glyph.program.getAssembly()
    asm_text = " ".join(asm)
    assert "MPPEM" in asm_text, f"MPPEM not found in assembly:\n{asm_text}"


def test_assembly_sets_y_axis(var_poc_font_path: str) -> None:
    """Glyph program sets the Y-axis vector via SVTCA."""
    from fontTools.ttLib import TTFont

    font = TTFont(var_poc_font_path)
    glyph = font["glyf"]["A"]
    asm = glyph.program.getAssembly()
    asm_text = " ".join(asm)
    assert "SVTCA[0]" in asm_text, (
        f"SVTCA[0] not found in assembly:\n{asm_text}"
    )


def test_assembly_targets_points_2_and_3(var_poc_font_path: str) -> None:
    """Glyph program references point indices 2 and 3 for SCFS."""
    from fontTools.ttLib import TTFont

    font = TTFont(var_poc_font_path)
    glyph = font["glyf"]["A"]
    bytecode = bytes(glyph.program.getBytecode())

    # PUSHB[] for value 2: opcode 0xB0, then 0x02
    # PUSHB[] for value 3: opcode 0xB0, then 0x03
    assert bytes([0xB0, 0x02]) in bytecode, (
        "Point index 2 not found in bytecode"
    )
    assert bytes([0xB0, 0x03]) in bytecode, (
        "Point index 3 not found in bytecode"
    )


def test_getvariation_opcode_present(var_poc_font_path: str) -> None:
    """Bytecode contains opcode 0x91 (GETVARIATION)."""
    from fontTools.ttLib import TTFont

    font = TTFont(var_poc_font_path)
    glyph = font["glyf"]["A"]
    bytecode = bytes(glyph.program.getBytecode())
    assert 0x91 in bytecode, (
        f"Opcode 0x91 (GETVARIATION) not found in bytecode: {bytecode.hex()}"
    )


# ---------------------------------------------------------------------------
# Name table checks
# ---------------------------------------------------------------------------


def test_font_family_name(var_poc_font_path: str) -> None:
    """Font family name is 'DoomVarPOC'."""
    from fontTools.ttLib import TTFont

    font = TTFont(var_poc_font_path)
    name_records = {r.nameID: str(r) for r in font["name"].names}
    assert "DoomVarPOC" in name_records.get(1, ""), (
        f"Family name mismatch: {name_records}"
    )


# ---------------------------------------------------------------------------
# Bytecode round-trip check
# ---------------------------------------------------------------------------


def test_bytecode_roundtrip(var_poc_font_path: str) -> None:
    """Assembly -> bytecode -> assembly round-trip preserves instructions."""
    from fontTools.ttLib import TTFont
    from fontTools.ttLib.tables.ttProgram import Program

    font = TTFont(var_poc_font_path)
    glyph = font["glyf"]["A"]

    original_asm = glyph.program.getAssembly()
    bytecode = glyph.program.getBytecode()

    roundtrip = Program()
    roundtrip.fromBytecode(bytecode)
    roundtrip_asm = roundtrip.getAssembly()

    # Strip comments for comparison (fonttools appends /* ... */ comments)
    def strip_comments(lines: list[str]) -> list[str]:
        return [line.split("/*")[0].strip() for line in lines]

    assert strip_comments(original_asm) == strip_comments(roundtrip_asm)
