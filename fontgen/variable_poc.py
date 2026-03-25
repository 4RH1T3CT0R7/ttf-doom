"""Variable font proof-of-concept for TTDoom.

Creates a variable .ttf font with a custom 'MOVE' axis.  The glyph 'A' is
a vertical bar whose top-edge height is controlled at render time by the
axis value.  The glyph's hinting program uses GETVARIATION[] to read the
normalised axis coordinate, scales it to a pixel position via MPPEM, and
repositions the top two outline points with SCFS[].

This proves that a font variation axis can serve as an input channel to
the TrueType hinting VM -- the fundamental input mechanism for TTDoom.
"""

from fontTools.fontBuilder import FontBuilder
from fontTools.ttLib.tables._f_p_g_m import table__f_p_g_m
from fontTools.ttLib.tables._p_r_e_p import table__p_r_e_p
from fontTools.ttLib.tables.ttProgram import Program
from fontTools.ttLib.tables.TupleVariation import TupleVariation
from fontTools.pens.ttGlyphPen import TTGlyphPen


def create_variable_poc_font(output_path: str) -> str:
    """Create a variable TrueType font with a MOVE axis driving bar height.

    The font contains a single glyph 'A' drawn as a vertical rectangle
    (4 on-curve points at Y=0 and Y=800).  A custom variation axis named
    ``MOVE`` ranges from 0 to 1000 (default 500).  The glyph's hinting
    program reads the normalised axis value with GETVARIATION[], converts
    it to a pixel-space Y coordinate, and calls SCFS[] on the two top
    points so the visible bar height tracks the axis value.

    Axis-to-height mapping (in font units):
        MOVE=0    ->  height ~0
        MOVE=500  ->  height ~400
        MOVE=1000 ->  height ~800

    Args:
        output_path: Filesystem path where the .ttf file will be written.

    Returns:
        The same *output_path*, for convenience in chaining.
    """
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "A"])
    fb.setupCharacterMap({65: "A"})

    # --- Glyph outlines ---------------------------------------------------
    #
    # Glyph 'A': a vertical bar (rectangle) from (100,0) to (200,800).
    #   0: bottom-left  (100,   0)
    #   1: bottom-right (200,   0)
    #   2: top-right    (200, 800)
    #   3: top-left     (100, 800)

    pen = TTGlyphPen(None)
    pen.moveTo((100, 0))
    pen.lineTo((200, 0))
    pen.lineTo((200, 800))
    pen.lineTo((100, 800))
    pen.closePath()

    # .notdef: required placeholder glyph.
    notdef_pen = TTGlyphPen(None)
    notdef_pen.moveTo((0, 0))
    notdef_pen.lineTo((500, 0))
    notdef_pen.lineTo((500, 700))
    notdef_pen.lineTo((0, 700))
    notdef_pen.closePath()

    fb.setupGlyf({".notdef": notdef_pen.glyph(), "A": pen.glyph()})

    # --- Metrics and metadata ---------------------------------------------

    fb.setupHorizontalMetrics({"A": (300, 100), ".notdef": (500, 0)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "DoomVarPOC", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()

    # --- fvar: variation axis definition ----------------------------------
    #
    # Custom axis 'MOVE' with range 0..1000, default 500.
    # In the normalised coordinate space used by GETVARIATION[]:
    #   MOVE=0    ->  -1.0  (F2Dot14: -16384)
    #   MOVE=500  ->   0.0  (F2Dot14:      0)
    #   MOVE=1000 ->  +1.0  (F2Dot14: +16384)

    fb.setupFvar(
        axes=[("MOVE", 0, 500, 1000, "Move")],
        instances=[],
    )

    # --- gvar: glyph variation data ---------------------------------------
    #
    # Even though the actual repositioning is done entirely by hinting,
    # the font MUST contain gvar entries for the renderer to recognise it
    # as a variable font and supply normalised coordinates to
    # GETVARIATION[].  We provide zero-delta tuples (no outline movement
    # from gvar itself).
    #
    # Each glyph has 4 on-curve points + 4 phantom points = 8 entries.

    zero_deltas = [(0, 0)] * 8  # 4 contour points + 4 phantom points

    fb.setupGvar({
        ".notdef": [
            TupleVariation({"MOVE": (0, 1.0, 1.0)}, [(0, 0)] * 8),
        ],
        "A": [
            TupleVariation({"MOVE": (0, 1.0, 1.0)}, zero_deltas),
        ],
    })

    font = fb.font

    # --- maxp: reserve resources for the hinting VM -----------------------

    font["maxp"].maxStackElements = 256
    font["maxp"].maxStorage = 64
    font["maxp"].maxFunctionDefs = 8
    font["maxp"].maxSizeOfInstructions = 1024

    # --- fpgm: Font Program (global function definitions) -----------------
    # Minimal bootstrap; full TTDoom build will expand this.

    fpgm = table__f_p_g_m()
    fpgm.program = Program()
    fpgm.program.fromAssembly([
        "PUSHB[] 0",
        "SRP0[]",
    ])
    font["fpgm"] = fpgm

    # --- prep: Pre-Program ------------------------------------------------
    # Set freedom and projection vectors to Y axis.

    prep = table__p_r_e_p()
    prep.program = Program()
    prep.program.fromAssembly(["SVTCA[0]"])  # [0] = Y-axis, [1] = X-axis
    font["prep"] = prep

    # --- Glyph hinting program for 'A' -----------------------------------
    #
    # Arithmetic walkthrough
    # ~~~~~~~~~~~~~~~~~~~~~~
    # GETVARIATION[] pushes the normalised axis coordinate V as F2Dot14
    # (-16384 for MOVE=0 ... +16384 for MOVE=1000).
    #
    # We want to map this to a *pixel* Y coordinate (F26Dot6) proportional
    # to 0..800 font units at the current ppem:
    #
    #   shifted = V + 16384            range [0, 32768]   (plain integer)
    #   target  = shifted * ppem * 800 / (1000 * 32768)
    #           = shifted * ppem / 40960
    #
    # In TrueType stack operations (ADD/SUB are plain integer; MUL does
    # (n1*n2)/64; DIV does (n2*64)/n1):
    #
    #   MUL(shifted, ppem)  = shifted * ppem / 64
    #   DIV(result,  640)   = (shifted*ppem/64) * 64 / 640
    #                       = shifted * ppem / 640
    #
    # That gives height proportional to 800/1000 * ppem when shifted is at
    # maximum, which is exactly 0.8 * ppem pixels -- the correct bar height
    # in pixel space.  The result is already in F26Dot6 (suitable for SCFS).

    glyph = font["glyf"]["A"]
    glyph.program = Program()
    glyph.program.fromAssembly([
        # -- set vectors to Y axis --
        "SVTCA[0]",               # [0] = Y-axis, [1] = X-axis

        # -- read normalised axis value --
        "GETVARIATION[]",       # pushes V in F2Dot14 (-16384..+16384)

        # -- shift to unsigned range --
        "PUSHW[] 16384",
        "ADD[]",                # stack: shifted (0..32768)

        # -- scale to pixel Y (F26Dot6) --
        "MPPEM[]",              # stack: shifted, ppem
        "MUL[]",                # stack: (shifted * ppem) / 64
        "PUSHW[] 640",
        "DIV[]",                # stack: (shifted * ppem) / 640  [F26Dot6]

        # -- apply to both top points --
        "DUP[]",                # duplicate for second SCFS call

        "PUSHB[] 2",            # point index 2 (top-right)
        "SWAP[]",               # stack: ..., 2, y_coord
        "SCFS[]",               # move point 2 to computed Y

        "PUSHB[] 3",            # point index 3 (top-left)
        "SWAP[]",               # stack: 3, y_coord
        "SCFS[]",               # move point 3 to computed Y
    ])

    # --- Save -------------------------------------------------------------

    font.save(output_path)
    return output_path


if __name__ == "__main__":
    import os
    import sys

    if len(sys.argv) > 1:
        out = sys.argv[1]
    else:
        out = os.path.join(os.path.dirname(__file__), "..", "var_poc.ttf")
        out = os.path.normpath(out)

    result = create_variable_poc_font(out)
    print(f"Variable POC font saved to {result}  ({os.path.getsize(result)} bytes)")
