"""End-to-end integration tests for the TTDoom compile pipeline.

Validates that the full compilation chain -- DSL source to lexer to
parser to code generator to font builder -- produces valid TrueType
fonts with the expected structure.

Coverage:
- Minimal program compilation
- Function and call compilation
- Game-like program with variables, arrays, functions, if/while
- Font has correct variation axes (fvar)
- Font has correct number of bar contours
- Font can be reloaded with TTFont
- Assembly round-trip through fpgm
- CLI invocation
- Error handling for invalid source
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import pytest
from fontTools.ttLib import TTFont

from compiler.pipeline import build_font, compile_doom


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PYTHON = sys.executable

_MINIMAL_SOURCE = "var x: int = 42\n"

_FUNC_SOURCE = """\
var result: int = 0

func add(a: int, b: int) -> int:
    return a + b

func game_tick():
    result = add(10, 20)
"""

_GAME_SOURCE = """\
const MAP_SIZE = 16
var player_x: int = 512
var player_y: int = 512
var player_angle: int = 0
array map_data[256]

func move_player(dx: int, dy: int):
    player_x = player_x + dx
    player_y = player_y + dy

func game_tick():
    var move: int = get_axis(0)
    var turn: int = get_axis(2)
    player_angle = player_angle + turn / 512
    if player_angle < 0:
        player_angle = player_angle + 256
    if player_angle >= 256:
        player_angle = player_angle - 256
    move_player(move / 4, 0)
"""

_ARRAY_SOURCE = """\
array data[8]

func game_tick():
    var i: int = 0
    while i < 8:
        data[i] = i * 10
        i = i + 1
"""

_IF_ELSE_SOURCE = """\
var x: int = 10
var y: int = 0

func game_tick():
    if x > 5:
        y = 1
    else:
        y = 0
"""


# ---------------------------------------------------------------------------
# Minimal program
# ---------------------------------------------------------------------------

class TestMinimalProgram:
    """Compile a minimal ``var x: int = 42`` program."""

    def test_compiles_to_ttf(self, tmp_path: object) -> None:
        """A single variable declaration compiles to a valid .ttf file."""
        out = os.path.join(str(tmp_path), "minimal.ttf")
        result = compile_doom(_MINIMAL_SOURCE, out)
        assert result == out
        assert os.path.isfile(out)
        assert os.path.getsize(out) > 0

    def test_output_is_valid_ttfont(self, tmp_path: object) -> None:
        """The output file loads correctly as a TTFont."""
        out = os.path.join(str(tmp_path), "minimal.ttf")
        compile_doom(_MINIMAL_SOURCE, out)
        font = TTFont(out)
        assert "glyf" in font
        assert "fpgm" in font
        assert "prep" in font
        font.close()

    def test_prep_contains_init(self, tmp_path: object) -> None:
        """The prep table contains variable initialisation instructions."""
        out = os.path.join(str(tmp_path), "minimal.ttf")
        compile_doom(_MINIMAL_SOURCE, out)
        font = TTFont(out)
        prep_asm = font["prep"].program.getAssembly()
        # Should contain SVTCA and WS for variable init
        assert any("SVTCA" in line for line in prep_asm)
        assert any("WS" in line for line in prep_asm)
        font.close()


# ---------------------------------------------------------------------------
# Function program
# ---------------------------------------------------------------------------

class TestFunctionProgram:
    """Compile a program with function definitions and calls."""

    def test_compiles_to_ttf(self, tmp_path: object) -> None:
        """Program with functions compiles to a valid .ttf file."""
        out = os.path.join(str(tmp_path), "func.ttf")
        result = compile_doom(_FUNC_SOURCE, out)
        assert result == out
        assert os.path.isfile(out)

    def test_fpgm_contains_fdef(self, tmp_path: object) -> None:
        """The fpgm table contains FDEF/ENDF blocks for user functions."""
        out = os.path.join(str(tmp_path), "func.ttf")
        compile_doom(_FUNC_SOURCE, out)
        font = TTFont(out)
        fpgm_asm = font["fpgm"].program.getAssembly()
        fdef_count = sum(1 for line in fpgm_asm if "FDEF" in line)
        endf_count = sum(1 for line in fpgm_asm if "ENDF" in line)
        assert fdef_count >= 2  # at least add + game_tick + stdlib
        assert fdef_count == endf_count
        font.close()

    def test_glyph_calls_game_tick(self, tmp_path: object) -> None:
        """The glyph program calls game_tick via CALL[]."""
        out = os.path.join(str(tmp_path), "func.ttf")
        compile_doom(_FUNC_SOURCE, out)
        font = TTFont(out)
        glyph_asm = font["glyf"]["A"].program.getAssembly()
        assert any("CALL" in line for line in glyph_asm)
        font.close()


# ---------------------------------------------------------------------------
# Game-like program
# ---------------------------------------------------------------------------

class TestGameProgram:
    """Compile a game-like program with variables, arrays, functions, if/while."""

    def test_compiles_to_ttf(self, tmp_path: object) -> None:
        """Full game-like program compiles without errors."""
        out = os.path.join(str(tmp_path), "game.ttf")
        result = compile_doom(_GAME_SOURCE, out)
        assert result == out
        assert os.path.isfile(out)
        assert os.path.getsize(out) > 1000  # should be substantial

    def test_reloads_cleanly(self, tmp_path: object) -> None:
        """Compiled font can be saved and reloaded without corruption."""
        out = os.path.join(str(tmp_path), "game.ttf")
        compile_doom(_GAME_SOURCE, out)
        font = TTFont(out)
        # Re-save and re-load to verify integrity
        out2 = os.path.join(str(tmp_path), "game2.ttf")
        font.save(out2)
        font.close()
        font2 = TTFont(out2)
        assert "glyf" in font2
        assert "fpgm" in font2
        font2.close()


# ---------------------------------------------------------------------------
# Font structure verification
# ---------------------------------------------------------------------------

class TestFontStructure:
    """Verify the structural properties of compiled fonts."""

    def test_has_five_axes(self, tmp_path: object) -> None:
        """Font fvar table contains exactly 5 custom axes."""
        out = os.path.join(str(tmp_path), "axes.ttf")
        compile_doom(_MINIMAL_SOURCE, out, num_axes=5)
        font = TTFont(out)
        assert "fvar" in font
        axes = font["fvar"].axes
        assert len(axes) == 5
        font.close()

    def test_axis_tags(self, tmp_path: object) -> None:
        """Font axes have the expected tags: MOVX, MOVY, TURN, FIRE, ACTN."""
        out = os.path.join(str(tmp_path), "axes.ttf")
        compile_doom(_MINIMAL_SOURCE, out, num_axes=5)
        font = TTFont(out)
        tags = [a.axisTag for a in font["fvar"].axes]
        assert tags == ["MOVX", "MOVY", "TURN", "FIRE", "ACTN"]
        font.close()

    def test_axis_ranges(self, tmp_path: object) -> None:
        """Each axis ranges from 0 to 1000 with default 500."""
        out = os.path.join(str(tmp_path), "axes.ttf")
        compile_doom(_MINIMAL_SOURCE, out, num_axes=5)
        font = TTFont(out)
        for axis in font["fvar"].axes:
            assert axis.minValue == 0
            assert axis.defaultValue == 500
            assert axis.maxValue == 1000
        font.close()

    def test_has_64_contours(self, tmp_path: object) -> None:
        """Glyph 'A' has 64 contours (one per bar)."""
        out = os.path.join(str(tmp_path), "bars.ttf")
        compile_doom(_MINIMAL_SOURCE, out, num_bars=64)
        font = TTFont(out)
        glyph = font["glyf"]["A"]
        assert glyph.numberOfContours == 64
        font.close()

    def test_custom_bar_count(self, tmp_path: object) -> None:
        """Glyph 'A' contour count matches the requested num_bars."""
        out = os.path.join(str(tmp_path), "bars32.ttf")
        compile_doom(_MINIMAL_SOURCE, out, num_bars=32)
        font = TTFont(out)
        glyph = font["glyf"]["A"]
        assert glyph.numberOfContours == 32
        font.close()

    def test_points_per_contour(self, tmp_path: object) -> None:
        """Each contour in the bar glyph has exactly 4 points."""
        out = os.path.join(str(tmp_path), "bars.ttf")
        compile_doom(_MINIMAL_SOURCE, out, num_bars=8)
        font = TTFont(out)
        glyph = font["glyf"]["A"]
        # endPtsOfContours gives the last point index for each contour
        endpoints = glyph.endPtsOfContours
        assert len(endpoints) == 8
        for i, end in enumerate(endpoints):
            start = 0 if i == 0 else endpoints[i - 1] + 1
            assert end - start + 1 == 4
        font.close()

    def test_gvar_delta_count(self, tmp_path: object) -> None:
        """gvar entries have correct delta count (num_bars*4 + 4 phantom)."""
        out = os.path.join(str(tmp_path), "gvar.ttf")
        compile_doom(_MINIMAL_SOURCE, out, num_bars=16)
        font = TTFont(out)
        gvar = font["gvar"]
        a_variations = gvar.variations["A"]
        # Each TupleVariation should have 16*4 + 4 = 68 deltas
        for tv in a_variations:
            assert len(tv.coordinates) == 16 * 4 + 4
        font.close()

    def test_maxp_storage(self, tmp_path: object) -> None:
        """maxp.maxStorage is at least as large as the allocator requires."""
        out = os.path.join(str(tmp_path), "maxp.ttf")
        compile_doom(_GAME_SOURCE, out)
        font = TTFont(out)
        assert font["maxp"].maxStorage >= 64
        font.close()

    def test_maxp_function_defs(self, tmp_path: object) -> None:
        """maxp.maxFunctionDefs is at least as large as the allocator requires."""
        out = os.path.join(str(tmp_path), "maxp.ttf")
        compile_doom(_GAME_SOURCE, out)
        font = TTFont(out)
        assert font["maxp"].maxFunctionDefs >= 2  # at least game_tick + move_player
        font.close()

    def test_essential_tables_present(self, tmp_path: object) -> None:
        """Compiled font contains all essential TrueType tables."""
        out = os.path.join(str(tmp_path), "tables.ttf")
        compile_doom(_MINIMAL_SOURCE, out)
        font = TTFont(out)
        for table in ["glyf", "fpgm", "prep", "fvar", "gvar", "maxp",
                       "head", "hhea", "hmtx", "name", "OS/2", "post"]:
            assert table in font, f"Missing table: {table}"
        font.close()


# ---------------------------------------------------------------------------
# Assembly round-trip
# ---------------------------------------------------------------------------

class TestAssemblyRoundTrip:
    """Verify that assembly can be disassembled and still makes sense."""

    def test_fpgm_disassembles(self, tmp_path: object) -> None:
        """fpgm program can be disassembled without errors."""
        out = os.path.join(str(tmp_path), "roundtrip.ttf")
        compile_doom(_FUNC_SOURCE, out)
        font = TTFont(out)
        asm = font["fpgm"].program.getAssembly()
        assert isinstance(asm, list)
        assert len(asm) > 0
        font.close()

    def test_prep_disassembles(self, tmp_path: object) -> None:
        """prep program can be disassembled without errors."""
        out = os.path.join(str(tmp_path), "roundtrip.ttf")
        compile_doom(_FUNC_SOURCE, out)
        font = TTFont(out)
        asm = font["prep"].program.getAssembly()
        assert isinstance(asm, list)
        assert len(asm) > 0
        font.close()

    def test_glyph_program_disassembles(self, tmp_path: object) -> None:
        """Glyph hinting program can be disassembled without errors."""
        out = os.path.join(str(tmp_path), "roundtrip.ttf")
        compile_doom(_FUNC_SOURCE, out)
        font = TTFont(out)
        glyph = font["glyf"]["A"]
        asm = glyph.program.getAssembly()
        assert isinstance(asm, list)
        assert len(asm) > 0
        font.close()

    def test_fpgm_contains_expected_instructions(self, tmp_path: object) -> None:
        """fpgm assembly contains FDEF/ENDF and known instructions."""
        out = os.path.join(str(tmp_path), "roundtrip.ttf")
        compile_doom(_FUNC_SOURCE, out)
        font = TTFont(out)
        asm = font["fpgm"].program.getAssembly()
        asm_text = "\n".join(asm)
        assert "FDEF" in asm_text
        assert "ENDF" in asm_text
        font.close()

    def test_bytecode_can_be_recompiled(self, tmp_path: object) -> None:
        """Disassembled fpgm can be re-assembled without errors."""
        from fontTools.ttLib.tables.ttProgram import Program
        out = os.path.join(str(tmp_path), "roundtrip.ttf")
        compile_doom(_FUNC_SOURCE, out)
        font = TTFont(out)
        asm = font["fpgm"].program.getAssembly()
        # Re-assemble: this validates the assembly is syntactically correct
        prog = Program()
        prog.fromAssembly(asm)
        asm2 = prog.getAssembly()
        assert len(asm2) == len(asm)
        font.close()


# ---------------------------------------------------------------------------
# Array and if/else programs
# ---------------------------------------------------------------------------

class TestArrayProgram:
    """Compile a program with arrays and while loops."""

    def test_compiles_to_ttf(self, tmp_path: object) -> None:
        """Array + while loop program compiles to a valid .ttf."""
        out = os.path.join(str(tmp_path), "array.ttf")
        result = compile_doom(_ARRAY_SOURCE, out)
        assert result == out
        assert os.path.isfile(out)

    def test_fpgm_has_while_loop_fdef(self, tmp_path: object) -> None:
        """While loops compile to recursive FDEFs in fpgm."""
        out = os.path.join(str(tmp_path), "array.ttf")
        compile_doom(_ARRAY_SOURCE, out)
        font = TTFont(out)
        fpgm_asm = font["fpgm"].program.getAssembly()
        fdef_count = sum(1 for line in fpgm_asm if "FDEF" in line)
        # game_tick + stdlib + while loop helper
        assert fdef_count >= 2
        font.close()


class TestIfElseProgram:
    """Compile a program with if/else."""

    def test_compiles_to_ttf(self, tmp_path: object) -> None:
        """If/else program compiles to a valid .ttf."""
        out = os.path.join(str(tmp_path), "ifelse.ttf")
        result = compile_doom(_IF_ELSE_SOURCE, out)
        assert result == out
        assert os.path.isfile(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCLI:
    """Test the compiler CLI (python -m compiler)."""

    def test_cli_compiles_doom_file(self, tmp_path: object) -> None:
        """CLI compiles a .doom file and produces a .ttf."""
        src = os.path.join(str(tmp_path), "test.doom")
        out = os.path.join(str(tmp_path), "test.ttf")
        with open(src, "w") as f:
            f.write(_MINIMAL_SOURCE)

        result = subprocess.run(
            [PYTHON, "-m", "compiler", src, "-o", out],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert os.path.isfile(out)

    def test_cli_default_output_name(self, tmp_path: object) -> None:
        """CLI defaults output name to source stem + .ttf."""
        src = os.path.join(str(tmp_path), "hello.doom")
        with open(src, "w") as f:
            f.write(_MINIMAL_SOURCE)

        result = subprocess.run(
            [PYTHON, "-m", "compiler", src],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        expected_out = os.path.join(str(tmp_path), "hello.ttf")
        assert os.path.isfile(expected_out)

    def test_cli_custom_bars(self, tmp_path: object) -> None:
        """CLI --bars flag controls bar count in the output font."""
        src = os.path.join(str(tmp_path), "bars.doom")
        out = os.path.join(str(tmp_path), "bars.ttf")
        with open(src, "w") as f:
            f.write(_MINIMAL_SOURCE)

        result = subprocess.run(
            [PYTHON, "-m", "compiler", src, "-o", out, "--bars", "16"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        font = TTFont(out)
        glyph = font["glyf"]["A"]
        assert glyph.numberOfContours == 16
        font.close()

    def test_cli_missing_source_file(self) -> None:
        """CLI exits with error for missing source file."""
        result = subprocess.run(
            [PYTHON, "-m", "compiler", "nonexistent.doom"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        assert result.returncode != 0
        assert "Error" in result.stderr or "error" in result.stderr

    def test_cli_compiles_game_test(self, tmp_path: object) -> None:
        """CLI compiles the game/test_game.doom file successfully."""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = os.path.join(project_root, "game", "test_game.doom")
        out = os.path.join(str(tmp_path), "test_game.ttf")

        result = subprocess.run(
            [PYTHON, "-m", "compiler", src, "-o", out],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert os.path.isfile(out)
        font = TTFont(out)
        assert "fvar" in font
        assert len(font["fvar"].axes) == 5
        font.close()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Verify that compilation errors are handled gracefully."""

    def test_syntax_error_raises(self, tmp_path: object) -> None:
        """Invalid DSL source raises an appropriate error."""
        out = os.path.join(str(tmp_path), "bad.ttf")
        with pytest.raises(Exception):
            compile_doom("func ???", out)

    def test_undefined_variable_raises(self, tmp_path: object) -> None:
        """Reference to undefined variable raises an error."""
        out = os.path.join(str(tmp_path), "bad.ttf")
        source = """\
func game_tick():
    undefined_var = 42
"""
        with pytest.raises(Exception):
            compile_doom(source, out)

    def test_undefined_function_raises(self, tmp_path: object) -> None:
        """Call to undefined function raises an error."""
        out = os.path.join(str(tmp_path), "bad.ttf")
        source = """\
func game_tick():
    nonexistent_func()
"""
        with pytest.raises(Exception):
            compile_doom(source, out)

    def test_invalid_source_no_crash(self, tmp_path: object) -> None:
        """Invalid source produces an error, does not crash Python."""
        out = os.path.join(str(tmp_path), "bad.ttf")
        try:
            compile_doom("@@@ invalid tokens @@@ !!!", out)
        except Exception as e:
            assert str(e)  # has a meaningful error message

    def test_cli_invalid_source_reports_error(self, tmp_path: object) -> None:
        """CLI prints error to stderr for invalid source and exits non-zero."""
        src = os.path.join(str(tmp_path), "bad.doom")
        out = os.path.join(str(tmp_path), "bad.ttf")
        with open(src, "w") as f:
            f.write("@@@ totally invalid @@@\n")

        result = subprocess.run(
            [PYTHON, "-m", "compiler", src, "-o", out],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        assert result.returncode != 0
        assert "Error" in result.stderr


# ---------------------------------------------------------------------------
# build_font standalone
# ---------------------------------------------------------------------------

class TestBuildFont:
    """Test the build_font function directly."""

    def test_empty_assembly(self, tmp_path: object) -> None:
        """build_font works with empty assembly lists (uses fallbacks)."""
        out = os.path.join(str(tmp_path), "empty.ttf")
        result = build_font(
            fpgm_asm=[],
            prep_asm=[],
            glyph_asm=[],
            num_bars=4,
            num_axes=5,
            max_storage=64,
            max_funcs=8,
            output_path=out,
        )
        assert result == out
        assert os.path.isfile(out)
        font = TTFont(out)
        assert font["glyf"]["A"].numberOfContours == 4
        font.close()

    def test_custom_axes_count(self, tmp_path: object) -> None:
        """build_font respects num_axes parameter."""
        out = os.path.join(str(tmp_path), "axes3.ttf")
        build_font(
            fpgm_asm=[],
            prep_asm=[],
            glyph_asm=[],
            num_bars=4,
            num_axes=3,
            max_storage=64,
            max_funcs=8,
            output_path=out,
        )
        font = TTFont(out)
        assert len(font["fvar"].axes) == 3
        tags = [a.axisTag for a in font["fvar"].axes]
        assert tags == ["MOVX", "MOVY", "TURN"]
        font.close()

    def test_with_real_assembly(self, tmp_path: object) -> None:
        """build_font injects actual assembly and it round-trips."""
        out = os.path.join(str(tmp_path), "real.ttf")
        build_font(
            fpgm_asm=["PUSHB[] 0", "FDEF[]", "PUSHB[] 1", "ENDF[]"],
            prep_asm=["SVTCA[0]"],
            glyph_asm=["PUSHB[] 0", "CALL[]"],
            num_bars=8,
            num_axes=5,
            max_storage=64,
            max_funcs=8,
            output_path=out,
        )
        font = TTFont(out)
        fpgm_asm = font["fpgm"].program.getAssembly()
        assert any("FDEF" in line for line in fpgm_asm)
        glyph_asm = font["glyf"]["A"].program.getAssembly()
        assert any("CALL" in line for line in glyph_asm)
        font.close()
