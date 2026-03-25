"""Proof-of-concept font generator for TTDoom.

Creates a minimal .ttf font with a single glyph ('A') containing a vertical
rectangle whose height is controlled by TrueType hinting instructions.
The glyph program uses SCFS[] to move the top two points from Y=800 to Y=400,
proving that hinting instructions can dynamically alter glyph geometry.
"""

from fontTools.fontBuilder import FontBuilder
from fontTools.ttLib.tables._f_p_g_m import table__f_p_g_m
from fontTools.ttLib.tables._p_r_e_p import table__p_r_e_p
from fontTools.ttLib.tables.ttProgram import Program
from fontTools.pens.ttGlyphPen import TTGlyphPen


def create_poc_font(output_path: str) -> str:
    """Create a proof-of-concept TrueType font with hinting instructions.

    The font contains a single glyph 'A' drawn as a vertical rectangle
    (4 on-curve points). A glyph-level hinting program uses SCFS[] to
    reposition the top edge from Y=800 down to Y=400, demonstrating that
    the TrueType hinting VM can control rendered geometry.

    Args:
        output_path: Filesystem path where the .ttf file will be written.

    Returns:
        The same output_path, for convenience in chaining.
    """
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "A"])
    fb.setupCharacterMap({65: "A"})

    # --- Glyph outlines ---------------------------------------------------

    # Glyph 'A': a vertical bar (rectangle) from (100,0) to (200,800).
    # Points are ordered counter-clockwise so the winding is correct:
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
    fb.setupNameTable({"familyName": "DoomPOC", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()

    font = fb.font

    # --- maxp: reserve resources for the hinting VM -----------------------

    font["maxp"].maxStackElements = 256
    font["maxp"].maxStorage = 64
    font["maxp"].maxFunctionDefs = 8
    font["maxp"].maxSizeOfInstructions = 512

    # --- fpgm: Font Program (global function definitions) -----------------
    # Minimal program that sets reference point 0 to point index 1.
    # In TTDoom's full build this table will hold helper functions.

    fpgm = table__f_p_g_m()
    fpgm.program = Program()
    fpgm.program.fromAssembly([
        "PUSHB[] 1",
        "SRP0[]",
    ])
    font["fpgm"] = fpgm

    # --- prep: Pre-Program (executed before every glyph) ------------------
    # Sets the freedom/projection vectors to the Y axis so that all
    # subsequent coordinate manipulations operate vertically.

    prep = table__p_r_e_p()
    prep.program = Program()
    prep.program.fromAssembly(["SVTCA[0]"])  # [0] = Y-axis, [1] = X-axis
    font["prep"] = prep

    # --- Glyph hinting program for 'A' -----------------------------------
    # Move the two top points (indices 2 and 3) from their outline
    # position (Y=800) to Y=400.  This halves the visible bar height
    # and proves the hinting VM can control geometry.

    glyph = font["glyf"]["A"]
    glyph.program = Program()
    glyph.program.fromAssembly([
        "SVTCA[0]",       # Set vectors to Y axis ([0]=Y, [1]=X)
        "PUSHW[] 2",      # Push point index 2
        "PUSHW[] 400",    # Push target Y coordinate (FUnits)
        "SCFS[]",         # Set Coordinate From Stack — move point 2
        "PUSHW[] 3",      # Push point index 3
        "PUSHW[] 400",    # Push target Y coordinate (FUnits)
        "SCFS[]",         # Set Coordinate From Stack — move point 3
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
        out = os.path.join(os.path.dirname(__file__), "..", "poc.ttf")
        out = os.path.normpath(out)

    result = create_poc_font(out)
    print(f"POC font saved to {result}  ({os.path.getsize(result)} bytes)")
