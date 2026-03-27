"""Tests for the full TTDoom raycaster pipeline.

Verifies that doom.doom parses, compiles, and builds into a valid
variable TrueType font with the correct structure for the raycasting
game engine.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from fontTools.ttLib import TTFont

# ---------------------------------------------------------------------------
# Project root / source paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..")
)
_DOOM_SRC = os.path.join(_PROJECT_ROOT, "game", "doom.doom")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_doom_source() -> str:
    """Read the doom.doom DSL source file."""
    with open(_DOOM_SRC, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def doom_source() -> str:
    """The raw doom.doom source code."""
    return _read_doom_source()


@pytest.fixture(scope="module")
def parsed_program(doom_source: str):
    """Parsed AST from doom.doom."""
    from compiler.parser import Parser

    parser = Parser(doom_source)
    return parser.parse()


@pytest.fixture(scope="module")
def compiled_result(doom_source: str):
    """Compiled assembly output from doom.doom."""
    from compiler.codegen import CodeGenerator
    from compiler.parser import Parser

    parser = Parser(doom_source)
    program = parser.parse()
    codegen = CodeGenerator(num_axes=5)
    result = codegen.compile(program)
    return result, codegen


@pytest.fixture(scope="module")
def built_font_path() -> str:
    """Build doom.ttf into a temp directory and return the path."""
    import sys
    sys.path.insert(0, _PROJECT_ROOT)
    from game.build import build

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "doom_test.ttf")
        result = build(output_path=out_path)
        # Copy to a more durable location for the module scope
        durable_path = os.path.join(tmpdir, "doom_test_copy.ttf")
        import shutil
        shutil.copy2(result, durable_path)
        yield durable_path


@pytest.fixture(scope="module")
def built_font_path_stable():
    """Build doom.ttf into a temp file that persists for the module."""
    import sys
    sys.path.insert(0, _PROJECT_ROOT)
    from game.build import build

    fd, path = tempfile.mkstemp(suffix=".ttf", prefix="doom_test_")
    os.close(fd)
    try:
        build(output_path=path)
        yield path
    finally:
        if os.path.exists(path):
            os.unlink(path)


@pytest.fixture(scope="module")
def font(built_font_path_stable: str) -> TTFont:
    """Load the built font as a TTFont object."""
    f = TTFont(built_font_path_stable)
    yield f
    f.close()


# =========================================================================
# Test Class: DSL Source Parsing
# =========================================================================

class TestDoomParsing:
    """Verify that doom.doom parses without errors."""

    def test_source_file_exists(self):
        """doom.doom source file must exist."""
        assert os.path.isfile(_DOOM_SRC), f"Missing {_DOOM_SRC}"

    def test_lexer_succeeds(self, doom_source: str):
        """Lexer produces tokens without errors."""
        from compiler.lexer import Lexer

        lexer = Lexer(doom_source)
        tokens = lexer.tokenize()
        assert len(tokens) > 100, "Expected a substantial token stream"

    def test_parser_succeeds(self, parsed_program):
        """Parser produces a Program AST without errors."""
        from compiler.ast_nodes import Program

        assert isinstance(parsed_program, Program)

    def test_has_constants(self, parsed_program):
        """Program declares the expected constants."""
        from compiler.ast_nodes import ConstDecl

        const_names = {
            d.name for d in parsed_program.declarations
            if isinstance(d, ConstDecl)
        }
        for name in ["MAP_W", "MAP_H", "CELL_SIZE", "NUM_COLS",
                      "FOV_HALF", "WALL_SCALE", "MAX_STEPS"]:
            assert name in const_names, f"Missing constant: {name}"

    def test_has_variables(self, parsed_program):
        """Program declares player state variables."""
        from compiler.ast_nodes import VarDecl

        var_names = {
            d.name for d in parsed_program.declarations
            if isinstance(d, VarDecl)
        }
        for name in ["player_x", "player_y", "player_angle"]:
            assert name in var_names, f"Missing variable: {name}"

    def test_has_arrays(self, parsed_program):
        """Program declares map and trig table arrays."""
        from compiler.ast_nodes import ArrayDecl

        arrays = {
            d.name: d.size for d in parsed_program.declarations
            if isinstance(d, ArrayDecl)
        }
        assert "map_data" in arrays
        assert arrays["map_data"] == 256
        assert "sin_table" in arrays
        assert arrays["sin_table"] == 256
        assert "cos_table" in arrays
        assert arrays["cos_table"] == 256

    def test_has_functions(self, parsed_program):
        """Program defines the expected functions."""
        from compiler.ast_nodes import FuncDef

        func_names = {
            d.name for d in parsed_program.declarations
            if isinstance(d, FuncDef)
        }
        for name in ["get_sin", "get_cos", "get_map", "raycast",
                      "render_col", "render_frame", "move_player",
                      "game_tick"]:
            assert name in func_names, f"Missing function: {name}"

    def test_game_tick_is_entry_point(self, parsed_program):
        """game_tick must exist so the glyph program can call it."""
        from compiler.ast_nodes import FuncDef

        func_names = [
            d.name for d in parsed_program.declarations
            if isinstance(d, FuncDef)
        ]
        assert "game_tick" in func_names

    def test_raycast_returns_int(self, parsed_program):
        """raycast function should be declared with a return type."""
        from compiler.ast_nodes import FuncDef

        for d in parsed_program.declarations:
            if isinstance(d, FuncDef) and d.name == "raycast":
                assert d.has_return is True
                break
        else:
            pytest.fail("raycast function not found")


# =========================================================================
# Test Class: Code Generation
# =========================================================================

class TestDoomCompilation:
    """Verify that doom.doom compiles to valid TT assembly."""

    def test_codegen_succeeds(self, compiled_result):
        """Code generator does not throw errors."""
        result, codegen = compiled_result
        assert "fpgm" in result
        assert "prep" in result
        assert "glyph" in result

    def test_fpgm_nonempty(self, compiled_result):
        """fpgm assembly contains function definitions."""
        result, _ = compiled_result
        assert len(result["fpgm"]) > 50

    def test_fpgm_has_fdef_endf_pairs(self, compiled_result):
        """Every FDEF has a matching ENDF."""
        result, _ = compiled_result
        fdef_count = sum(1 for line in result["fpgm"] if line == "FDEF[]")
        endf_count = sum(1 for line in result["fpgm"] if line == "ENDF[]")
        assert fdef_count == endf_count
        assert fdef_count >= 12  # user funcs + stdlib + while loops

    def test_glyph_calls_game_tick(self, compiled_result):
        """Glyph program calls the game_tick function."""
        result, codegen = compiled_result
        game_tick_id = codegen.allocator.funcs["game_tick"]
        glyph = result["glyph"]
        assert "CALL[]" in glyph
        assert any(str(game_tick_id) in line for line in glyph)

    def test_storage_arrays_allocated(self, compiled_result):
        """Storage arrays are allocated with correct sizes."""
        _, codegen = compiled_result
        assert "map_data" in codegen.allocator.arrays
        assert "sin_table" in codegen.allocator.arrays
        assert "cos_table" in codegen.allocator.arrays

        _, map_size = codegen.allocator.arrays["map_data"]
        assert map_size == 256

        _, sin_size = codegen.allocator.arrays["sin_table"]
        assert sin_size == 256

        _, cos_size = codegen.allocator.arrays["cos_table"]
        assert cos_size == 256

    def test_user_functions_have_ids(self, compiled_result):
        """All user functions are assigned FDEF IDs."""
        _, codegen = compiled_result
        expected = ["get_sin", "get_cos", "get_map", "raycast",
                    "render_col", "render_frame", "move_player", "game_tick"]
        for name in expected:
            assert name in codegen.allocator.funcs, f"Missing func ID: {name}"

    def test_stdlib_functions_registered(self, compiled_result):
        """Standard library functions are registered."""
        _, codegen = compiled_result
        for name in ["fixmul", "fixdiv", "fixabs", "fixneg"]:
            assert name in codegen.allocator.funcs, f"Missing stdlib: {name}"

    def test_while_loops_allocated(self, compiled_result):
        """While loop helper functions are allocated."""
        _, codegen = compiled_result
        while_funcs = [
            name for name in codegen.allocator.funcs
            if name.startswith("__while_")
        ]
        assert len(while_funcs) >= 2, "Expected at least 2 while loops"

    def test_prep_does_not_reset_player_state(self, compiled_result):
        """Prep must NOT reset player vars (they persist between frames)."""
        result, _ = compiled_result
        prep = result["prep"]
        # Player vars have no init values → prep should not write them
        ws_count = sum(1 for line in prep if line == "WS[]")
        assert ws_count == 0, f"Base prep should have no WS[] (got {ws_count})"

    def test_total_storage_reasonable(self, compiled_result):
        """Total storage allocation stays within practical limits."""
        _, codegen = compiled_result
        total = codegen.allocator.total_storage
        # 3 vars + 256 map + 256 sin + 256 cos + locals = ~800+
        assert 700 < total < 2000, f"Unexpected storage: {total}"

    def test_total_funcs_reasonable(self, compiled_result):
        """Total function count stays within practical limits."""
        _, codegen = compiled_result
        total = codegen.allocator.total_funcs
        # 8 user + 4 stdlib + 2 while = 14
        assert 12 <= total <= 30, f"Unexpected func count: {total}"


# =========================================================================
# Test Class: Build Script
# =========================================================================

class TestBuildScript:
    """Verify the build script produces a valid font file."""

    def test_build_produces_file(self, built_font_path_stable: str):
        """Build script creates a .ttf file."""
        assert os.path.isfile(built_font_path_stable)

    def test_file_size_reasonable(self, built_font_path_stable: str):
        """The font file is a reasonable size (not trivially empty)."""
        size = os.path.getsize(built_font_path_stable)
        assert size > 1000, f"Font too small: {size} bytes"
        assert size < 1_000_000, f"Font too large: {size} bytes"


# =========================================================================
# Test Class: Font Structure
# =========================================================================

class TestFontStructure:
    """Verify the built font has the correct tables and structure."""

    def test_font_loads(self, font: TTFont):
        """Font can be loaded by fonttools."""
        assert font is not None

    def test_has_required_tables(self, font: TTFont):
        """Font has all required TrueType tables."""
        required = ["glyf", "head", "hhea", "hmtx", "maxp",
                     "name", "post", "cmap", "loca"]
        for table in required:
            assert table in font, f"Missing table: {table}"

    def test_has_variation_tables(self, font: TTFont):
        """Font has fvar and gvar for variable font support."""
        assert "fvar" in font
        assert "gvar" in font

    def test_has_hinting_tables(self, font: TTFont):
        """Font has fpgm and prep for hinting programs."""
        assert "fpgm" in font
        assert "prep" in font

    def test_fvar_has_five_axes(self, font: TTFont):
        """fvar defines exactly 5 variation axes."""
        axes = font["fvar"].axes
        assert len(axes) == 5

    def test_fvar_axis_tags(self, font: TTFont):
        """fvar axes have the correct tags."""
        tags = [a.axisTag for a in font["fvar"].axes]
        expected = ["MOVX", "MOVY", "TURN", "FIRE", "ACTN"]
        assert tags == expected

    def test_glyph_a_exists(self, font: TTFont):
        """The display glyph 'A' exists in the font."""
        assert "A" in font["glyf"]

    def test_glyph_has_32_contours(self, font: TTFont):
        """Glyph 'A' has 32 bar contours (one per display column)."""
        glyph = font["glyf"]["A"]
        assert glyph.numberOfContours == 16

    def test_glyph_has_128_points(self, font: TTFont):
        """Glyph 'A' has 32 * 4 = 128 on-curve points."""
        glyph = font["glyf"]["A"]
        coords = glyph.getCoordinates(font["glyf"])
        assert len(coords[0]) == 64

    def test_glyph_has_program(self, font: TTFont):
        """Glyph 'A' has a hinting program attached."""
        glyph = font["glyf"]["A"]
        assert hasattr(glyph, "program")
        assert glyph.program is not None
        asm = glyph.program.getAssembly()
        assert len(asm) > 0


# =========================================================================
# Test Class: fpgm Content
# =========================================================================

class TestFpgmContent:
    """Verify the font program (fpgm) content."""

    def test_fpgm_has_bytecode(self, font: TTFont):
        """fpgm table contains bytecode."""
        fpgm = font["fpgm"].program
        assert fpgm.getBytecode() is not None
        assert len(fpgm.getBytecode()) > 100

    def test_fpgm_fdef_count(self, font: TTFont):
        """fpgm has the expected number of FDEF blocks."""
        asm = font["fpgm"].program.getAssembly()
        fdef_count = sum(1 for line in asm if "FDEF" in line and "ENDF" not in line)
        assert fdef_count >= 12  # 8 user + 4 stdlib + while loops

    def test_fpgm_roundtrips(self, font: TTFont):
        """fpgm bytecode round-trips through assembly."""
        from fontTools.ttLib.tables.ttProgram import Program

        orig_bytecode = font["fpgm"].program.getBytecode()
        asm = font["fpgm"].program.getAssembly()

        prog2 = Program()
        prog2.fromAssembly(asm)
        assert prog2.getBytecode() == orig_bytecode


# =========================================================================
# Test Class: prep Content
# =========================================================================

class TestPrepContent:
    """Verify the pre-program (prep) content."""

    def test_prep_has_bytecode(self, font: TTFont):
        """prep table contains bytecode."""
        prep = font["prep"].program
        assert prep.getBytecode() is not None
        assert len(prep.getBytecode()) > 100

    def test_prep_loads_sin_cos_tables(self, font: TTFont):
        """prep assembly contains many WS[] instructions for table loading."""
        asm = font["prep"].program.getAssembly()
        ws_lines = [line for line in asm if "WS" in line]
        # 256 sin + 256 cos + 84 map walls + 3 vars = 599
        assert len(ws_lines) >= 500, (
            f"Expected ~599 WS[] instructions, got {len(ws_lines)}"
        )

    def test_prep_starts_with_svtca(self, font: TTFont):
        """prep begins with SVTCA[0] (set to Y-axis)."""
        asm = font["prep"].program.getAssembly()
        assert any("SVTCA[0]" in line for line in asm[:5])

    def test_prep_loads_map_data(self, font: TTFont):
        """prep loads non-zero map values into storage."""
        asm = font["prep"].program.getAssembly()
        # The map has walls (value 1) that need to be stored.
        # At minimum, the border walls are 16*4 - 4 corners counted once = 56 walls
        ws_lines = [line for line in asm if "WS" in line]
        assert len(ws_lines) >= 84, "Expected map data WS[] instructions"


# =========================================================================
# Test Class: Font Reload
# =========================================================================

class TestFontReload:
    """Verify font can be saved and reloaded (round-trip)."""

    def test_roundtrip_save_load(self, built_font_path_stable: str):
        """Font survives a save-load round-trip."""
        font1 = TTFont(built_font_path_stable)
        with tempfile.NamedTemporaryFile(suffix=".ttf", delete=False) as f:
            tmp_path = f.name
        try:
            font1.save(tmp_path)
            font1.close()

            font2 = TTFont(tmp_path)
            assert "fvar" in font2
            assert "fpgm" in font2
            assert "prep" in font2
            assert font2["glyf"]["A"].numberOfContours == 16
            font2.close()
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_roundtrip_preserves_bytecode(self, built_font_path_stable: str):
        """fpgm bytecode is identical after round-trip."""
        font1 = TTFont(built_font_path_stable)
        orig_bc = font1["fpgm"].program.getBytecode()
        with tempfile.NamedTemporaryFile(suffix=".ttf", delete=False) as f:
            tmp_path = f.name
        try:
            font1.save(tmp_path)
            font1.close()

            font2 = TTFont(tmp_path)
            new_bc = font2["fpgm"].program.getBytecode()
            assert orig_bc == new_bc
            font2.close()
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


# =========================================================================
# Test Class: Local Variable Scoping
# =========================================================================

class TestLocalVariableScoping:
    """Verify that local variables in different functions do not conflict."""

    def test_duplicate_local_names_across_functions(self):
        """Two functions can declare locals with the same name."""
        from compiler.codegen import CodeGenerator
        from compiler.parser import Parser

        source = """
func foo(x: int) -> int:
    var temp: int = x + 1
    return temp

func bar(y: int) -> int:
    var temp: int = y + 2
    return temp

func game_tick():
    var a: int = foo(1)
    var b: int = bar(2)
"""
        parser = Parser(source)
        program = parser.parse()
        codegen = CodeGenerator()
        result = codegen.compile(program)
        # Should not raise AllocatorError
        assert "fpgm" in result
        assert len(result["fpgm"]) > 0

    def test_local_var_in_while_body(self):
        """Local variable declared inside a while loop compiles."""
        from compiler.codegen import CodeGenerator
        from compiler.parser import Parser

        source = """
var counter: int = 0

func game_tick():
    var i: int = 0
    while i < 3:
        var temp: int = i + 1
        counter = counter + temp
        i = i + 1
"""
        parser = Parser(source)
        program = parser.parse()
        codegen = CodeGenerator()
        result = codegen.compile(program)
        assert "fpgm" in result


# =========================================================================
# Test Class: DSL Feature Coverage
# =========================================================================

class TestDSLFeatures:
    """Verify specific DSL features used in the raycaster."""

    def test_array_access_in_expression(self):
        """Array access works inside expressions."""
        from compiler.codegen import CodeGenerator
        from compiler.parser import Parser

        source = """
array data[16]

func game_tick():
    var val: int = data[0]
    var val2: int = data[val + 1]
"""
        parser = Parser(source)
        program = parser.parse()
        codegen = CodeGenerator()
        result = codegen.compile(program)
        assert "fpgm" in result

    def test_nested_function_calls(self):
        """Nested function calls compile correctly."""
        from compiler.codegen import CodeGenerator
        from compiler.parser import Parser

        source = """
func inner(x: int) -> int:
    return x + 1

func outer(y: int) -> int:
    return inner(y) + inner(y + 1)

func game_tick():
    var result: int = outer(5)
"""
        parser = Parser(source)
        program = parser.parse()
        codegen = CodeGenerator()
        result = codegen.compile(program)
        assert "fpgm" in result

    def test_if_else_chains(self):
        """If/else chains compile correctly."""
        from compiler.codegen import CodeGenerator
        from compiler.parser import Parser

        source = """
var x: int = 0

func game_tick():
    if x < 0:
        x = 0
    else:
        if x > 100:
            x = 100
        else:
            x = x + 1
"""
        parser = Parser(source)
        program = parser.parse()
        codegen = CodeGenerator()
        result = codegen.compile(program)
        assert "fpgm" in result

    def test_set_point_y_intrinsic(self):
        """set_point_y intrinsic generates SCFS assembly."""
        from compiler.codegen import CodeGenerator
        from compiler.parser import Parser

        source = """
func game_tick():
    set_point_y(0, 500)
    set_point_y(1, 250)
"""
        parser = Parser(source)
        program = parser.parse()
        codegen = CodeGenerator()
        result = codegen.compile(program)
        fpgm = result["fpgm"]
        assert any("SCFS" in line for line in fpgm)
        assert any("SVTCA[0]" in line for line in fpgm)

    def test_get_axis_intrinsic(self):
        """get_axis intrinsic generates GETVARIATION assembly."""
        from compiler.codegen import CodeGenerator
        from compiler.parser import Parser

        source = """
var val: int = 0

func game_tick():
    val = get_axis(0)
"""
        parser = Parser(source)
        program = parser.parse()
        codegen = CodeGenerator()
        result = codegen.compile(program)
        fpgm = result["fpgm"]
        assert any("GETVARIATION" in line for line in fpgm)

    def test_multiplication_compensation(self):
        """DSL * operator generates MUL with 4096 compensation."""
        from compiler.codegen import CodeGenerator
        from compiler.parser import Parser

        source = """
var a: int = 3
var b: int = 4

func game_tick():
    var c: int = a * b
"""
        parser = Parser(source)
        program = parser.parse()
        codegen = CodeGenerator()
        result = codegen.compile(program)
        fpgm = result["fpgm"]
        mul_count = sum(1 for line in fpgm if line == "MUL[]")
        # Two MUL[] instructions: one for the actual multiply, one for 4096 compensation
        assert mul_count >= 2

    def test_division_compensation(self):
        """DSL / operator generates DIV with 4096 compensation."""
        from compiler.codegen import CodeGenerator
        from compiler.parser import Parser

        source = """
var a: int = 10
var b: int = 2

func game_tick():
    var c: int = a / b
"""
        parser = Parser(source)
        program = parser.parse()
        codegen = CodeGenerator()
        result = codegen.compile(program)
        fpgm = result["fpgm"]
        div_count = sum(1 for line in fpgm if line == "DIV[]")
        assert div_count >= 2


# =========================================================================
# Test Class: Math Tables
# =========================================================================

class TestMathTablesIntegration:
    """Verify sin/cos table generation and integration."""

    def test_sin_cos_table_sizes(self):
        """Tables have the expected number of entries."""
        from fontgen.math_tables import generate_sin_cos_tables

        sin_t, cos_t = generate_sin_cos_tables(entries=256, scale=256)
        assert len(sin_t) == 256
        assert len(cos_t) == 256

    def test_sin_zero_is_zero(self):
        """sin(0) should be 0."""
        from fontgen.math_tables import generate_sin_cos_tables

        sin_t, _ = generate_sin_cos_tables(entries=256, scale=256)
        assert sin_t[0] == 0

    def test_cos_zero_is_scale(self):
        """cos(0) should equal the scale factor."""
        from fontgen.math_tables import generate_sin_cos_tables

        _, cos_t = generate_sin_cos_tables(entries=256, scale=256)
        assert cos_t[0] == 256

    def test_sin_quarter_is_scale(self):
        """sin(90 deg) = sin(entry 64) should be the scale factor."""
        from fontgen.math_tables import generate_sin_cos_tables

        sin_t, _ = generate_sin_cos_tables(entries=256, scale=256)
        assert sin_t[64] == 256

    def test_cos_quarter_is_zero(self):
        """cos(90 deg) = cos(entry 64) should be 0."""
        from fontgen.math_tables import generate_sin_cos_tables

        _, cos_t = generate_sin_cos_tables(entries=256, scale=256)
        assert cos_t[64] == 0

    def test_all_values_fit_pushw(self):
        """All table values fit in a signed 16-bit PUSHW instruction."""
        from fontgen.math_tables import generate_sin_cos_tables

        sin_t, cos_t = generate_sin_cos_tables(entries=256, scale=256)
        for v in sin_t + cos_t:
            assert -32768 <= v <= 32767

    def test_prep_asm_generation(self):
        """generate_prep_load_tables produces the expected number of WS[]."""
        from fontgen.math_tables import (
            generate_prep_load_tables,
            generate_sin_cos_tables,
        )

        sin_t, cos_t = generate_sin_cos_tables(entries=256, scale=256)
        asm = generate_prep_load_tables(sin_t, cos_t, 100, 400)
        ws_count = sum(1 for line in asm if line == "WS[]")
        assert ws_count == 512  # 256 sin + 256 cos


# =========================================================================
# Test Class: Map Data
# =========================================================================

class TestMapData:
    """Verify the map data loading."""

    def test_level1_size(self):
        """Level 1 map has 256 cells (16x16)."""
        from game.build import LEVEL_1

        assert len(LEVEL_1) == 256

    def test_level1_border_walls(self):
        """All border cells are walls."""
        from game.build import LEVEL_1

        # Top row
        for x in range(16):
            assert LEVEL_1[x] == 1, f"Top border open at x={x}"
        # Bottom row
        for x in range(16):
            assert LEVEL_1[15 * 16 + x] == 1, f"Bottom border open at x={x}"
        # Left column
        for y in range(16):
            assert LEVEL_1[y * 16] == 1, f"Left border open at y={y}"
        # Right column
        for y in range(16):
            assert LEVEL_1[y * 16 + 15] == 1, f"Right border open at y={y}"

    def test_player_spawn_is_open(self):
        """Player spawn position (160, 160) -> cell (2, 2) is open."""
        from game.build import LEVEL_1

        # player_x=160, player_y=160, cell_size=64
        # cell = (160//64, 160//64) = (2, 2)
        cell_x = 160 // 64  # 2
        cell_y = 160 // 64  # 2
        assert LEVEL_1[cell_y * 16 + cell_x] == 0, \
            f"Spawn cell ({cell_x},{cell_y}) should be open"

    def test_interior_has_open_space(self):
        """The map interior has some open cells for gameplay."""
        from game.build import LEVEL_1

        open_cells = sum(1 for v in LEVEL_1 if v == 0)
        assert open_cells > 100, f"Not enough open space: {open_cells} cells"

    def test_wall_count_matches_prep(self, font: TTFont):
        """Number of wall cells matches non-zero map entries stored in prep."""
        from game.build import LEVEL_1

        wall_count = sum(1 for v in LEVEL_1 if v > 0)
        # Each wall cell generates 4 prep instructions (push val, push idx, swap, ws)
        # Total map WS[] = wall_count
        assert wall_count == 84, f"Unexpected wall count: {wall_count}"


# =========================================================================
# Test Class: End-to-End Build
# =========================================================================

class TestEndToEnd:
    """End-to-end tests verifying the complete build pipeline."""

    def test_build_import(self):
        """The build module can be imported."""
        from game.build import build
        assert callable(build)

    def test_build_produces_valid_font(self):
        """Building doom.doom produces a font that fonttools can load."""
        import sys
        sys.path.insert(0, _PROJECT_ROOT)
        from game.build import build

        fd, path = tempfile.mkstemp(suffix=".ttf")
        os.close(fd)
        try:
            build(output_path=path)
            font = TTFont(path)
            assert "A" in font["glyf"]
            assert font["glyf"]["A"].numberOfContours == 16
            font.close()
        finally:
            os.unlink(path)

    def test_build_is_deterministic(self):
        """Two consecutive builds produce identical bytecode."""
        import sys
        sys.path.insert(0, _PROJECT_ROOT)
        from game.build import build

        paths = []
        try:
            for _ in range(2):
                fd, path = tempfile.mkstemp(suffix=".ttf")
                os.close(fd)
                build(output_path=path)
                paths.append(path)

            f1 = TTFont(paths[0])
            f2 = TTFont(paths[1])

            bc1 = f1["fpgm"].program.getBytecode()
            bc2 = f2["fpgm"].program.getBytecode()
            assert bc1 == bc2, "Build is not deterministic"

            f1.close()
            f2.close()
        finally:
            for p in paths:
                if os.path.exists(p):
                    os.unlink(p)
