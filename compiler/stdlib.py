"""TTDoom standard library: fixed-point arithmetic as TrueType assembly.

Generates TrueType hinting instructions for 16.16 fixed-point math
operations.  These function bodies are meant to be wrapped in FDEF/ENDF
blocks and injected into the font's ``fpgm`` table.

Fixed-point format
------------------
All values use **26Dot6** coordinates internally in the TT VM, but our
game logic operates with **16.16** fixed-point numbers stored as plain
32-bit integers:

    real_value = raw_integer / 65536
    1.0   =  65536
    0.5   =  32768
   -1.5   = -98304

TrueType arithmetic quirks
--------------------------
* ``MUL[]`` computes ``(a * b) / 64``   (F26Dot6 semantics)
* ``DIV[]`` computes ``(n2 * 64) / n1`` (n1 = top-of-stack, n2 = below)
* ``ADD[]`` / ``SUB[]`` / ``NEG[]`` / ``ABS[]`` work on plain integers
  and are directly usable with 16.16 values.

Because MUL/DIV have built-in scale factors of 64, extra compensation
steps are required to achieve correct 16.16 multiply and divide.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 16.16 fixed-point constants
# ---------------------------------------------------------------------------

FIXED_ONE: int = 1 << 16        # 65536 — represents 1.0 in 16.16
FIXED_HALF: int = 1 << 15       # 32768 — represents 0.5 in 16.16


def to_fixed(value: float) -> int:
    """Convert a Python float to 16.16 fixed-point integer.

    Args:
        value: Real number to convert.

    Returns:
        Signed 32-bit integer in 16.16 fixed-point representation.
    """
    return int(value * FIXED_ONE)


def from_fixed(raw: int) -> float:
    """Convert a 16.16 fixed-point integer back to a Python float.

    Args:
        raw: Integer in 16.16 fixed-point representation.

    Returns:
        Approximate floating-point equivalent.
    """
    return raw / FIXED_ONE


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_stdlib_functions() -> dict[str, list[str]]:
    """Return TT assembly bodies for every standard-library function.

    Each value is a list of TrueType assembly mnemonics that form the
    function body (without the surrounding ``FDEF`` / ``ENDF``).  The
    caller is responsible for assigning function IDs and wrapping these
    in FDEF/ENDF blocks before injecting into the ``fpgm`` table.

    Returns:
        Mapping of function name to its assembly instruction list.
    """
    return {
        "fixmul": _fixmul_asm(),
        "fixdiv": _fixdiv_asm(),
        "fixabs": _fixabs_asm(),
        "fixneg": _fixneg_asm(),
    }


def get_function_metadata() -> dict[str, dict[str, int]]:
    """Return stack-effect metadata for every stdlib function.

    This information is consumed by the compiler's stack-depth analyser
    and register allocator.

    Returns:
        Mapping of function name to ``{"args": N, "returns": M}``.
    """
    return {
        "fixmul": {"args": 2, "returns": 1},
        "fixdiv": {"args": 2, "returns": 1},
        "fixabs": {"args": 1, "returns": 1},
        "fixneg": {"args": 1, "returns": 1},
    }


# ---------------------------------------------------------------------------
# Assembly generators (private)
# ---------------------------------------------------------------------------

def _fixmul_asm() -> list[str]:
    """Fixed-point 16.16 multiply: ``(a * b) >> 16``.

    Stack effect
    ~~~~~~~~~~~~
    ::

        input:  ..., a, b   (b on top)
        output: ..., (a * b) / 65536

    Algorithm
    ~~~~~~~~~
    We need ``(a * b) / 65536`` but TT ``MUL[]`` gives ``(a * b) / 64``.
    The remaining factor of 1024 is applied via two ``DIV[]`` steps whose
    combined effect divides by 1024 (= 4 * 256):

    1. ``MUL[]``          -> ``(a*b) / 64``
    2. ``DIV[] by 256``   -> ``((a*b)/64 * 64) / 256  = (a*b) / 256``
    3. ``DIV[] by 16384`` -> ``((a*b)/256 * 64) / 16384 = (a*b) / 65536``

    Both divisors (256 and 16384) fit in a signed 16-bit ``PUSHW``.
    """
    return [
        # --- Step 1: TT multiply ---
        "MUL[]",                # (a * b) / 64
        # --- Step 2: divide by 4 via DIV(result, 256) ---
        "PUSHW[] 256",
        "DIV[]",                # ((a*b)/64 * 64) / 256 = (a*b) / 256
        # --- Step 3: divide by 256 via DIV(result, 16384) ---
        "PUSHW[] 16384",
        "DIV[]",                # ((a*b)/256 * 64) / 16384 = (a*b) / 65536
    ]


def _fixdiv_asm() -> list[str]:
    """Fixed-point 16.16 divide: ``(a << 16) / b``.

    Stack effect
    ~~~~~~~~~~~~
    ::

        input:  ..., a, b   (b on top)
        output: ..., (a * 65536) / b

    Algorithm
    ~~~~~~~~~
    We need ``(a * 65536) / b``.  TT ``DIV[]`` gives ``(n2 * 64) / n1``,
    so if we pre-scale ``a`` by 1024 (= 65536 / 64) the ``DIV`` finishes
    the job.

    The factor 1024 is built up via two ``MUL[]`` steps whose combined
    effect is ``a * 1024`` without exceeding 16-bit push limits:

    1. ``SWAP``                           -> stack: b, a
    2. ``MUL(a, 256)``  = (a*256)/64 = a*4
    3. ``MUL(a*4, 16384)`` = (a*4*16384)/64 = a*1024
    4. ``SWAP``                           -> stack: a*1024, b
    5. ``DIV(a*1024, b)`` = (a*1024*64)/b = a*65536/b
    """
    return [
        # --- Save divisor, expose dividend ---
        "SWAP[]",               # b, a
        # --- Scale a by 4: MUL(a, 256) -> (a*256)/64 = a*4 ---
        "PUSHW[] 256",
        "MUL[]",                # a * 4
        # --- Scale by 256: MUL(a*4, 16384) -> (a*4*16384)/64 = a*1024 ---
        "PUSHW[] 16384",
        "MUL[]",                # a * 1024
        # --- Final divide ---
        "SWAP[]",               # a*1024, b
        "DIV[]",                # (a*1024 * 64) / b = a*65536 / b
    ]


def _fixabs_asm() -> list[str]:
    """Fixed-point absolute value (thin wrapper around ``ABS[]``).

    Stack effect: ``..., a  ->  ..., |a|``
    """
    return [
        "ABS[]",
    ]


def _fixneg_asm() -> list[str]:
    """Fixed-point negation (thin wrapper around ``NEG[]``).

    Stack effect: ``..., a  ->  ..., -a``
    """
    return [
        "NEG[]",
    ]


# ---------------------------------------------------------------------------
# Font injection helpers
# ---------------------------------------------------------------------------

def build_fpgm_assembly(
    func_ids: dict[str, int] | None = None,
) -> list[str]:
    """Build complete ``fpgm`` assembly containing all stdlib FDEFs.

    Args:
        func_ids: Optional mapping of function name to its FDEF ID.
            If *None*, IDs are assigned sequentially starting at 0.

    Returns:
        List of TT assembly lines ready for ``Program.fromAssembly()``.
    """
    stdlib = get_stdlib_functions()

    if func_ids is None:
        func_ids = {name: idx for idx, name in enumerate(stdlib)}

    lines: list[str] = []
    for name, body in stdlib.items():
        fid = func_ids[name]
        lines.append(f"PUSHB[] {fid}")
        lines.append("FDEF[]")
        lines.extend(body)
        lines.append("ENDF[]")

    return lines
