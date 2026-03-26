"""Sin/cos lookup table generation for TTDoom.

Generates fixed-point sine and cosine lookup tables and the TrueType
assembly instructions needed to load them into the hinting VM's storage
area at startup.

The default scale factor is **256**, chosen for compactness:
- All positive values fit in a single ``PUSHB`` instruction.
- Negative values fit in ``PUSHW`` (max magnitude 256).
- 256-scaled values align with the game's coordinate system where map
  cells are 64 units wide:  ``dx = speed * sin_table[angle] / 256``.
"""

import math


def generate_sin_cos_tables(
    entries: int = 256,
    scale: int = 256,
) -> tuple[list[int], list[int]]:
    """Generate fixed-point sin/cos lookup tables.

    Divides a full circle into *entries* equal steps and computes
    ``sin(angle) * scale`` and ``cos(angle) * scale`` for each step,
    rounded to the nearest integer.

    Args:
        entries: Number of table entries (256 covers a full circle with
            ~1.4-degree resolution).
        scale: Fixed-point scale factor.  A value of 256 means
            ``sin(90deg) == 256`` and ``sin(270deg) == -256``.

    Returns:
        A ``(sin_table, cos_table)`` tuple where each element is a list
        of *entries* integers.
    """
    sin_table: list[int] = []
    cos_table: list[int] = []
    for i in range(entries):
        angle = 2.0 * math.pi * i / entries
        sin_table.append(int(round(math.sin(angle) * scale)))
        cos_table.append(int(round(math.cos(angle) * scale)))
    return sin_table, cos_table


def generate_prep_load_tables(
    sin_table: list[int],
    cos_table: list[int],
    sin_base: int,
    cos_base: int,
) -> list[str]:
    """Generate TrueType assembly to load sin/cos tables into storage.

    Emits a sequence of ``PUSHB``/``PUSHW`` + ``WS[]`` instructions that
    write every table entry into the hinting VM's storage area, starting
    at the given base indices.

    Args:
        sin_table: List of sine values to store.
        cos_table: List of cosine values to store.
        sin_base: Storage index where the sine table begins.
        cos_base: Storage index where the cosine table begins.

    Returns:
        A list of TrueType assembly instruction strings.
    """
    asm: list[str] = []
    for i, val in enumerate(sin_table):
        idx = sin_base + i
        asm.extend(_push_and_store(idx, val))
    for i, val in enumerate(cos_table):
        idx = cos_base + i
        asm.extend(_push_and_store(idx, val))
    return asm


def _push_and_store(storage_idx: int, value: int) -> list[str]:
    """Generate assembly to store *value* at *storage_idx*.

    Uses ``PUSHB`` for values in [0, 255] and ``PUSHW`` otherwise.  The
    storage index is pushed, then swapped with the value so that ``WS[]``
    receives ``(index, value)`` in the correct order.

    Args:
        storage_idx: Target storage location index.
        value: Integer value to store (must fit in a signed 16-bit word).

    Returns:
        A list of 4 assembly instruction strings.
    """
    asm: list[str] = []

    # Push the value.
    if 0 <= value <= 255:
        asm.append(f"PUSHB[] {value}")
    elif -32768 <= value <= 32767:
        asm.append(f"PUSHW[] {value}")
    else:
        # Clamp to signed 16-bit range (should not happen with scale <= 256).
        clamped = max(-32768, min(32767, value))
        asm.append(f"PUSHW[] {clamped}")

    # Push the storage index.
    if 0 <= storage_idx <= 255:
        asm.append(f"PUSHB[] {storage_idx}")
    else:
        asm.append(f"PUSHW[] {storage_idx}")

    # Swap so the stack is (index, value), then write.
    asm.append("SWAP[]")
    asm.append("WS[]")
    return asm
