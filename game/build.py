"""Build doom.ttf from doom.doom + sin/cos tables + map data.

Compiles the TTDoom DSL raycaster source into a fully functional
variable TrueType font with embedded sin/cos lookup tables and a
16x16 test level map.

Usage::

    python game/build.py
"""

from __future__ import annotations

import os
import sys

# Add project root to path so we can import compiler/fontgen packages.
_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _PROJECT_ROOT)

from compiler.codegen import CodeGenerator
from compiler.parser import Parser
from fontgen.font_builder import build_doom_font
from fontgen.math_tables import generate_prep_load_tables, generate_sin_cos_tables


# ---------------------------------------------------------------------------
# Level 1 map: 16x16, 1=wall, 0=empty
# ---------------------------------------------------------------------------

LEVEL_1: list[int] = [
    1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1,
    1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1,
    1, 0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0, 0, 1,
    1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1,
    1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1,
    1, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 1,
    1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1,
    1, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 1,
    1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1,
    1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1,
    1, 0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0, 0, 1,
    1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1,
    1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1,
    1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1,
    1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
]


def _push_and_store(storage_idx: int, value: int) -> list[str]:
    """Generate TT assembly to store *value* at *storage_idx*."""
    asm: list[str] = []
    if 0 <= value <= 255:
        asm.append(f"PUSHB[] {value}")
    elif -32768 <= value <= 32767:
        asm.append(f"PUSHW[] {value}")
    else:
        asm.append(f"PUSHW[] {max(-32768, min(32767, value))}")

    if 0 <= storage_idx <= 255:
        asm.append(f"PUSHB[] {storage_idx}")
    else:
        asm.append(f"PUSHW[] {storage_idx}")
    asm.append("SWAP[]")
    asm.append("WS[]")
    return asm


def build(output_path: str | None = None) -> str:
    """Compile doom.doom into a TrueType font.

    Args:
        output_path: Override for the output .ttf path.  Defaults to
            ``doom.ttf`` in the project root.

    Returns:
        Absolute path of the generated font file.
    """
    # --- Read DSL source ---
    src_path = os.path.join(os.path.dirname(__file__), "doom.doom")
    with open(src_path, "r", encoding="utf-8") as f:
        source = f.read()

    # --- Parse and compile ---
    parser = Parser(source)
    program = parser.parse()
    codegen = CodeGenerator(num_axes=5)
    result = codegen.compile(program)

    # --- Discover array storage locations ---
    sin_base, sin_size = codegen.allocator.arrays["sin_table"]
    cos_base, cos_size = codegen.allocator.arrays["cos_table"]
    map_base, map_size = codegen.allocator.arrays["map_data"]
    # enemy_data removed in stateless renderer architecture

    # --- Generate sin/cos tables ---
    sin_table, cos_table = generate_sin_cos_tables(entries=256, scale=256)
    table_asm = generate_prep_load_tables(sin_table, cos_table, sin_base, cos_base)

    # --- Generate map data loading assembly ---
    map_asm: list[str] = []
    for i, val in enumerate(LEVEL_1):
        if val > 0:
            map_asm.extend(_push_and_store(map_base + i, val))

    # --- Combine prep: codegen's prep + table loading + map loading ---
    full_prep = result["prep"] + table_asm + map_asm

    # --- Determine output path ---
    if output_path is None:
        output_path = os.path.join(_PROJECT_ROOT, "doom.ttf")
    output_path = os.path.normpath(output_path)

    # --- Calculate max storage needed ---
    max_storage = max(
        codegen.allocator.total_storage,
        cos_base + cos_size,
        sin_base + sin_size,
        map_base + map_size,
        # enemy data removed
    )

    # --- Build font ---
    build_doom_font(
        fpgm_asm=result["fpgm"],
        prep_asm=full_prep,
        glyph_asm=result["glyph"],
        output_path=output_path,
        num_bars=16,
        max_storage=max_storage + 64,  # headroom
        max_funcs=max(codegen.allocator.total_funcs + 4, 32),
        max_stack=1024,
    )

    file_size = os.path.getsize(output_path)
    print(f"Built {output_path} ({file_size:,} bytes)")
    print(f"  Functions: {codegen.allocator.total_funcs}")
    print(f"  Storage slots: {max_storage}")
    print(f"  Sin table: indices {sin_base}..{sin_base + sin_size - 1}")
    print(f"  Cos table: indices {cos_base}..{cos_base + cos_size - 1}")
    print(f"  Map data:  indices {map_base}..{map_base + map_size - 1}")
    # enemy data removed in stateless renderer architecture
    print(f"  fpgm: {len(result['fpgm'])} asm lines")
    print(f"  prep: {len(full_prep)} asm lines (base {len(result['prep'])} + tables {len(table_asm)} + map {len(map_asm)})")
    print(f"  glyph: {len(result['glyph'])} asm lines")
    return output_path


if __name__ == "__main__":
    build()
