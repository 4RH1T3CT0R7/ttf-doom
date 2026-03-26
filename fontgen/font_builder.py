"""Font builder for TTDoom.

Assembles a complete variable TrueType font (doom.ttf) from compiled
hinting assembly, multi-bar glyph geometry, and variation axis definitions.

The font contains:
- A ``.notdef`` placeholder glyph.
- An ``A`` glyph with *num_bars* vertical bar contours whose points are
  manipulated by the glyph hinting program to render DOOM frames.
- An ``fvar`` table defining input axes (movement, turning, firing, etc.).
- ``gvar`` entries with zero deltas (actual work is done by hinting).
- ``fpgm`` / ``prep`` / glyph programs loaded from pre-compiled assembly.
"""

from fontTools.fontBuilder import FontBuilder
from fontTools.ttLib.tables._f_p_g_m import table__f_p_g_m
from fontTools.ttLib.tables._p_r_e_p import table__p_r_e_p
from fontTools.ttLib.tables.ttProgram import Program
from fontTools.ttLib.tables.TupleVariation import TupleVariation

from fontgen.glyph_builder import build_bar_glyph, build_notdef_glyph

# Default axis definitions for the game.
# Each tuple: (tag, min_value, default_value, max_value, display_name)
DEFAULT_AXES: list[tuple[str, int, int, int, str]] = [
    ("MOVX", -1000, 0, 1000, "Move X"),
    ("MOVY", -1000, 0, 1000, "Move Y"),
    ("TURN", -1000, 0, 1000, "Turn"),
    ("FIRE", 0, 0, 1000, "Fire"),
    ("ACTN", 0, 0, 1000, "Action"),
]


def build_doom_font(
    fpgm_asm: list[str],
    prep_asm: list[str],
    glyph_asm: list[str],
    output_path: str,
    num_bars: int = 64,
    axes: list[tuple[str, int, int, int, str]] | None = None,
    max_storage: int = 4096,
    max_funcs: int = 256,
    max_stack: int = 256,
    font_name: str = "DoomFont",
) -> str:
    """Build the complete DOOM ``.ttf`` font.

    Args:
        fpgm_asm: Assembly instructions for the font program (function
            definitions loaded once at font-load time).
        prep_asm: Assembly instructions for the pre-program (executed
            before each glyph rendering -- initialisation code).
        glyph_asm: Assembly instructions for glyph ``A``'s program
            (the per-frame rendering code).
        output_path: Filesystem path where the ``.ttf`` will be written.
        num_bars: Number of vertical bar contours in the ``A`` glyph.
        axes: Variation axis definitions as a list of
            ``(tag, min, default, max, name)`` tuples.  Defaults to
            :data:`DEFAULT_AXES`.
        max_storage: Maximum storage locations reserved in ``maxp``.
        max_funcs: Maximum function definitions reserved in ``maxp``.
        max_stack: Maximum stack depth reserved in ``maxp``.
        font_name: Font family name written to the ``name`` table.

    Returns:
        *output_path*, for convenience in chaining.
    """
    if axes is None:
        axes = DEFAULT_AXES

    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "A"])
    fb.setupCharacterMap({65: "A"})

    # --- Glyph outlines ---------------------------------------------------

    bar_glyph = build_bar_glyph(num_bars)
    fb.setupGlyf({".notdef": build_notdef_glyph(), "A": bar_glyph})
    fb.setupHorizontalMetrics({"A": (1000, 0), ".notdef": (500, 0)})
    fb.setupHorizontalHeader(ascent=1000, descent=-200)
    fb.setupNameTable({"familyName": font_name, "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()

    # --- fvar: variation axis definitions ---------------------------------

    fb.setupFvar(
        axes=[(tag, mn, df, mx, name) for tag, mn, df, mx, name in axes],
        instances=[],
    )

    # --- gvar: glyph variation data (zero deltas) -------------------------
    #
    # Even though hinting performs all repositioning, gvar must exist for
    # the rasteriser to recognise this as a variable font and supply
    # normalised coordinates to GETVARIATION[].

    num_points_a = num_bars * 4 + 4        # contour points + 4 phantom
    num_points_notdef = 4 + 4              # 1 contour (4 pts) + 4 phantom

    gvar_data: dict[str, list[TupleVariation]] = {}
    for glyph_name, num_pts in [(".notdef", num_points_notdef), ("A", num_points_a)]:
        zero_deltas = [(0, 0)] * num_pts
        gvar_data[glyph_name] = [
            TupleVariation({axes[0][0]: (0, 1.0, 1.0)}, zero_deltas),
        ]
    fb.setupGvar(gvar_data)

    font = fb.font

    # --- maxp: reserve VM resources ---------------------------------------

    font["maxp"].maxStackElements = max_stack
    font["maxp"].maxStorage = max_storage
    font["maxp"].maxFunctionDefs = max_funcs
    font["maxp"].maxSizeOfInstructions = 65535

    # --- fpgm: Font Program -----------------------------------------------

    if fpgm_asm:
        fpgm = table__f_p_g_m()
        fpgm.program = Program()
        fpgm.program.fromAssembly(fpgm_asm)
        font["fpgm"] = fpgm

    # --- prep: Pre-Program ------------------------------------------------

    if prep_asm:
        prep = table__p_r_e_p()
        prep.program = Program()
        prep.program.fromAssembly(prep_asm)
        font["prep"] = prep

    # --- Glyph program for 'A' --------------------------------------------

    if glyph_asm:
        glyph = font["glyf"]["A"]
        glyph.program = Program()
        glyph.program.fromAssembly(glyph_asm)

    # --- Save -------------------------------------------------------------

    font.save(output_path)
    return output_path
