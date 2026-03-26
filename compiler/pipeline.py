"""TTDoom compile pipeline: DSL source -> TrueType font.

Chains the lexer, parser, code generator, and font builder into a
single ``compile_doom()`` function that takes DSL source code and
produces a fully functional variable TrueType font file.
"""

from __future__ import annotations

from fontTools.fontBuilder import FontBuilder
from fontTools.ttLib.tables._f_p_g_m import table__f_p_g_m
from fontTools.ttLib.tables._p_r_e_p import table__p_r_e_p
from fontTools.ttLib.tables.ttProgram import Program
from fontTools.ttLib.tables.TupleVariation import TupleVariation

from compiler.codegen import CodeGenerator
from compiler.parser import Parser
from fontgen.glyph_builder import build_bar_glyph, build_notdef_glyph


# ---------------------------------------------------------------------------
# Axis definitions
# ---------------------------------------------------------------------------

_AXES: list[tuple[str, int, int, int, str]] = [
    ("MOVX", 0, 500, 1000, "MoveX"),
    ("MOVY", 0, 500, 1000, "MoveY"),
    ("TURN", 0, 500, 1000, "Turn"),
    ("FIRE", 0, 500, 1000, "Fire"),
    ("ACTN", 0, 500, 1000, "Action"),
]


# ---------------------------------------------------------------------------
# Font builder
# ---------------------------------------------------------------------------

def build_font(
    fpgm_asm: list[str],
    prep_asm: list[str],
    glyph_asm: list[str],
    num_bars: int = 64,
    num_axes: int = 5,
    max_storage: int = 64,
    max_funcs: int = 8,
    output_path: str = "doom.ttf",
) -> str:
    """Build a variable TrueType font from compiled assembly segments.

    Creates a font with a multi-bar glyph whose geometry is controlled
    by TrueType hinting instructions compiled from the TTDoom DSL.  The
    font includes custom variation axes that serve as input channels for
    the game engine running inside the hinting VM.

    Args:
        fpgm_asm: Assembly lines for the font program (function defs).
        prep_asm: Assembly lines for the pre-program (init code).
        glyph_asm: Assembly lines for the glyph program (game tick).
        num_bars: Number of vertical bar contours in the display glyph.
        num_axes: Number of custom variation axes.
        max_storage: Maximum storage slots required by the program.
        max_funcs: Maximum function definitions required.
        output_path: Filesystem path for the output .ttf file.

    Returns:
        The output_path.
    """
    axes = _AXES[:num_axes]

    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "A"])
    fb.setupCharacterMap({65: "A"})

    # --- Glyph outlines ---
    a_glyph = build_bar_glyph(num_bars=num_bars)
    notdef_glyph = build_notdef_glyph()

    fb.setupGlyf({".notdef": notdef_glyph, "A": a_glyph})

    # --- Metrics and metadata ---
    total_width = 1000  # matches build_bar_glyph default
    fb.setupHorizontalMetrics({
        "A": (total_width, 0),
        ".notdef": (500, 0),
    })
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({
        "familyName": "TTDoom",
        "styleName": "Regular",
    })
    fb.setupOS2()
    fb.setupPost()

    # --- fvar: variation axes ---
    fb.setupFvar(
        axes=[(tag, mn, default, mx, name) for tag, mn, default, mx, name in axes],
        instances=[],
    )

    # --- gvar: glyph variation data ---
    # Each glyph needs deltas for all on-curve points + 4 phantom points.
    # The bar glyph has num_bars * 4 contour points.
    num_a_points = num_bars * 4
    num_a_deltas = num_a_points + 4  # + 4 phantom points
    num_notdef_deltas = 4 + 4        # 4 contour points + 4 phantom

    axis_tags = [tag for tag, *_ in axes]

    gvar_a: list[TupleVariation] = []
    gvar_notdef: list[TupleVariation] = []

    for tag in axis_tags:
        gvar_a.append(
            TupleVariation(
                {tag: (0, 1.0, 1.0)},
                [(0, 0)] * num_a_deltas,
            )
        )
        gvar_notdef.append(
            TupleVariation(
                {tag: (0, 1.0, 1.0)},
                [(0, 0)] * num_notdef_deltas,
            )
        )

    fb.setupGvar({
        ".notdef": gvar_notdef,
        "A": gvar_a,
    })

    font = fb.font

    # --- maxp: resource limits ---
    font["maxp"].maxStackElements = 1024
    font["maxp"].maxStorage = max(max_storage, 64)
    font["maxp"].maxFunctionDefs = max(max_funcs, 8)
    # Estimate instruction size from assembly line count
    estimated_size = (len(fpgm_asm) + len(prep_asm) + len(glyph_asm)) * 4
    font["maxp"].maxSizeOfInstructions = max(estimated_size, 2048)

    # --- fpgm: font program ---
    fpgm_table = table__f_p_g_m()
    fpgm_table.program = Program()
    if fpgm_asm:
        fpgm_table.program.fromAssembly(fpgm_asm)
    else:
        # Minimal valid program
        fpgm_table.program.fromAssembly(["PUSHB[] 0", "SRP0[]"])
    font["fpgm"] = fpgm_table

    # --- prep: pre-program ---
    prep_table = table__p_r_e_p()
    prep_table.program = Program()
    if prep_asm:
        prep_table.program.fromAssembly(prep_asm)
    else:
        prep_table.program.fromAssembly(["SVTCA[0]"])
    font["prep"] = prep_table

    # --- Glyph hinting program for 'A' ---
    glyph_obj = font["glyf"]["A"]
    glyph_obj.program = Program()
    if glyph_asm:
        glyph_obj.program.fromAssembly(glyph_asm)

    # --- Save ---
    font.save(output_path)
    return output_path


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def compile_doom(
    source: str,
    output_path: str,
    num_bars: int = 64,
    num_axes: int = 5,
) -> str:
    """Compile a .doom DSL source string into a .ttf font file.

    Runs the full compilation pipeline:
        1. Parse source text into an AST.
        2. Generate TrueType hinting assembly from the AST.
        3. Build a variable font containing the compiled hinting programs.

    Args:
        source: DSL source code string.
        output_path: Path to write the .ttf file.
        num_bars: Number of vertical bar contours in the glyph (default 64).
        num_axes: Number of font variation axes (default 5).

    Returns:
        The output_path.

    Raises:
        compiler.lexer.LexerError: If the source has invalid tokens.
        compiler.parser.ParseError: If the source has syntax errors.
        compiler.codegen.CodeGenError: If code generation fails.
    """
    # 1. Parse (Parser internally creates a Lexer)
    parser = Parser(source)
    program = parser.parse()

    # 2. Generate code
    codegen = CodeGenerator(num_axes=num_axes)
    result = codegen.compile(program)
    # result has keys: 'fpgm', 'prep', 'glyph'

    # 3. Build font
    build_font(
        fpgm_asm=result["fpgm"],
        prep_asm=result["prep"],
        glyph_asm=result["glyph"],
        num_bars=num_bars,
        num_axes=num_axes,
        max_storage=codegen.allocator.total_storage,
        max_funcs=codegen.allocator.total_funcs,
        output_path=output_path,
    )

    return output_path
