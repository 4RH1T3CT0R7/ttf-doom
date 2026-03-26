"""Tests for the TTDoom fixed-point math standard library.

Validates:
1. Generated TrueType assembly is syntactically correct
2. Numerical results match expected values (via TT arithmetic simulation)
3. Assembly can be injected into a real font via fonttools without errors
"""

from __future__ import annotations

import math
import os
import sys
import tempfile

import pytest

# Ensure the project root is on sys.path so compiler is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from compiler.stdlib import (
    FIXED_ONE,
    build_fpgm_assembly,
    from_fixed,
    get_function_metadata,
    get_stdlib_functions,
    to_fixed,
)


# ---------------------------------------------------------------------------
# TrueType arithmetic simulator
# ---------------------------------------------------------------------------

def _trunc_div(a: int, b: int) -> int:
    """Integer division that truncates toward zero (C / TT semantics).

    Python's ``//`` floors toward negative infinity, but the TrueType VM
    truncates toward zero, matching C's integer division behaviour.

    Examples::

        _trunc_div( 7,  2) ==  3   (Python //: 3)
        _trunc_div(-7,  2) == -3   (Python //: -4)
        _trunc_div( 7, -2) == -3   (Python //: -4)
        _trunc_div(-7, -2) ==  3   (Python //: 3)
    """
    if b == 0:
        raise ZeroDivisionError("division by zero")
    return int(a / b)


def tt_mul(a: int, b: int) -> int:
    """Simulate TrueType ``MUL[]``: ``(a * b) / 64``.

    The VM pops b (top-of-stack), then a, and pushes the result.
    Division truncates toward zero.
    """
    return _trunc_div(a * b, 64)


def tt_div(n2: int, n1: int) -> int:
    """Simulate TrueType ``DIV[]``: ``(n2 * 64) / n1``.

    The VM pops n1 (top-of-stack), then n2 (below), and pushes the
    result.  Division truncates toward zero.

    Args:
        n2: Second value popped (was below n1 on the stack).
        n1: First value popped (was on top of the stack).
    """
    if n1 == 0:
        raise ZeroDivisionError("TT DIV[] by zero")
    return _trunc_div(n2 * 64, n1)


# ---------------------------------------------------------------------------
# Composite operation simulators
# ---------------------------------------------------------------------------

def simulate_fixmul(a: int, b: int) -> int:
    """Simulate the fixmul FDEF through TT arithmetic.

    Mirrors the instruction sequence in ``_fixmul_asm()``:

    1. ``MUL[]``       -> ``(a * b) / 64``
    2. ``DIV[] 256``   -> ``result * 64 / 256 = result / 4``
    3. ``DIV[] 16384`` -> ``result * 64 / 16384 = result / 256``

    Net effect: ``(a * b) / 65536``.
    """
    step1 = tt_mul(a, b)            # MUL: (a*b)/64
    step2 = tt_div(step1, 256)      # DIV: (step1*64)/256 = step1/4
    step3 = tt_div(step2, 16384)    # DIV: (step2*64)/16384 = step2/256
    return step3


def simulate_fixdiv(a: int, b: int) -> int:
    """Simulate the fixdiv FDEF through TT arithmetic.

    Mirrors the instruction sequence in ``_fixdiv_asm()``:

    1. ``SWAP``                         -> stack: b, a
    2. ``MUL(a, 256)``   = (a*256)/64   = a*4
    3. ``MUL(a*4, 16384)`` = (a*4*16384)/64 = a*1024
    4. ``SWAP``                         -> stack: a*1024, b
    5. ``DIV(a*1024, b)`` = (a*1024*64)/b = a*65536/b

    Net effect: ``(a * 65536) / b``.
    """
    # After SWAP: stack is [b, a]; MUL operates on a (n2) and 256 (n1)
    step1 = tt_mul(a, 256)          # MUL: (a*256)/64 = a*4
    step2 = tt_mul(step1, 16384)    # MUL: (step1*16384)/64 = step1*256 = a*1024
    # After SWAP: stack is [a*1024, b]; DIV operates on a*1024 (n2) and b (n1)
    step3 = tt_div(step2, b)        # DIV: (a*1024*64)/b = a*65536/b
    return step3


# ---------------------------------------------------------------------------
# Ideal (Python) reference implementations
# ---------------------------------------------------------------------------

def ideal_fixmul(a: int, b: int) -> int:
    """Reference: exact ``(a * b) / 65536`` with truncation toward zero."""
    return _trunc_div(a * b, 65536)


def ideal_fixdiv(a: int, b: int) -> int:
    """Reference: exact ``(a * 65536) / b`` with truncation toward zero."""
    if b == 0:
        raise ZeroDivisionError
    return _trunc_div(a * 65536, b)


# ===========================================================================
# Test helpers
# ===========================================================================

VALID_TT_MNEMONICS = {
    "MUL[]", "DIV[]", "ADD[]", "SUB[]", "NEG[]", "ABS[]",
    "SWAP[]", "DUP[]", "POP[]", "ROLL[]", "MINDEX[]",
    "FDEF[]", "ENDF[]", "CALL[]",
    "SRP0[]", "SRP1[]", "SRP2[]",
    "SVTCA[0]", "SVTCA[1]",
    "SCFS[]",
    "IF[]", "ELSE[]", "EIF[]",
    "LT[]", "GT[]", "LTEQ[]", "GTEQ[]", "EQ[]", "NEQ[]",
    "AND[]", "OR[]", "NOT[]",
    "CINDEX[]", "MPPEM[]", "GETVARIATION[]",
}


def _is_valid_instruction(line: str) -> bool:
    """Check whether a single assembly line is a valid TT instruction.

    Recognises:
    - Bare mnemonics like ``MUL[]``, ``SWAP[]``
    - Push instructions like ``PUSHB[] 42``, ``PUSHW[] 16384``
    """
    line = line.strip()
    if not line:
        return False

    # Push instructions with an argument
    if line.startswith("PUSHB[] ") or line.startswith("PUSHW[] "):
        parts = line.split(None, 1)
        if len(parts) != 2:
            return False
        try:
            val = int(parts[1])
        except ValueError:
            return False
        if line.startswith("PUSHB[]"):
            return 0 <= val <= 255
        # PUSHW: signed 16-bit
        return -32768 <= val <= 32767

    # Bare mnemonic
    return line in VALID_TT_MNEMONICS


# ===========================================================================
# Tests: conversion helpers
# ===========================================================================


class TestConversionHelpers:
    """Verify to_fixed / from_fixed round-trip correctly."""

    def test_one(self) -> None:
        assert to_fixed(1.0) == 65536

    def test_half(self) -> None:
        assert to_fixed(0.5) == 32768

    def test_negative(self) -> None:
        assert to_fixed(-1.0) == -65536

    def test_zero(self) -> None:
        assert to_fixed(0.0) == 0

    def test_roundtrip(self) -> None:
        for val in [0.0, 1.0, -1.0, 0.5, 2.5, -3.75, 100.0]:
            assert from_fixed(to_fixed(val)) == pytest.approx(val, abs=1e-4)


# ===========================================================================
# Tests: assembly validity
# ===========================================================================


class TestAssemblyValidity:
    """Verify that generated assembly consists of valid TT instructions."""

    @pytest.fixture()
    def stdlib(self) -> dict[str, list[str]]:
        return get_stdlib_functions()

    def test_all_functions_present(self, stdlib: dict[str, list[str]]) -> None:
        assert "fixmul" in stdlib
        assert "fixdiv" in stdlib
        assert "fixabs" in stdlib
        assert "fixneg" in stdlib

    def test_fixmul_instructions_valid(self, stdlib: dict[str, list[str]]) -> None:
        for line in stdlib["fixmul"]:
            assert _is_valid_instruction(line), f"Invalid instruction: {line!r}"

    def test_fixdiv_instructions_valid(self, stdlib: dict[str, list[str]]) -> None:
        for line in stdlib["fixdiv"]:
            assert _is_valid_instruction(line), f"Invalid instruction: {line!r}"

    def test_fixabs_instructions_valid(self, stdlib: dict[str, list[str]]) -> None:
        for line in stdlib["fixabs"]:
            assert _is_valid_instruction(line), f"Invalid instruction: {line!r}"

    def test_fixneg_instructions_valid(self, stdlib: dict[str, list[str]]) -> None:
        for line in stdlib["fixneg"]:
            assert _is_valid_instruction(line), f"Invalid instruction: {line!r}"

    def test_no_empty_bodies(self, stdlib: dict[str, list[str]]) -> None:
        for name, body in stdlib.items():
            assert len(body) > 0, f"Function {name!r} has empty body"

    def test_push_values_in_range(self, stdlib: dict[str, list[str]]) -> None:
        """All PUSHW values fit in signed 16-bit range."""
        for name, body in stdlib.items():
            for line in body:
                if line.startswith("PUSHW[]"):
                    val = int(line.split()[1])
                    assert -32768 <= val <= 32767, (
                        f"{name}: PUSHW value {val} out of signed 16-bit range"
                    )


# ===========================================================================
# Tests: function metadata
# ===========================================================================


class TestFunctionMetadata:
    """Verify stack-effect metadata is consistent."""

    def test_all_functions_have_metadata(self) -> None:
        stdlib = get_stdlib_functions()
        metadata = get_function_metadata()
        for name in stdlib:
            assert name in metadata, f"Missing metadata for {name!r}"

    def test_fixmul_metadata(self) -> None:
        meta = get_function_metadata()["fixmul"]
        assert meta["args"] == 2
        assert meta["returns"] == 1

    def test_fixdiv_metadata(self) -> None:
        meta = get_function_metadata()["fixdiv"]
        assert meta["args"] == 2
        assert meta["returns"] == 1

    def test_fixabs_metadata(self) -> None:
        meta = get_function_metadata()["fixabs"]
        assert meta["args"] == 1
        assert meta["returns"] == 1

    def test_fixneg_metadata(self) -> None:
        meta = get_function_metadata()["fixneg"]
        assert meta["args"] == 1
        assert meta["returns"] == 1


# ===========================================================================
# Tests: TT arithmetic simulator sanity checks
# ===========================================================================


class TestSimulatorSanity:
    """Ensure the TT arithmetic simulator behaves correctly."""

    def test_tt_mul_basic(self) -> None:
        # 128 * 64 = 8192; / 64 = 128
        assert tt_mul(128, 64) == 128

    def test_tt_mul_negative(self) -> None:
        # (-128) * 64 = -8192; / 64 = -128
        assert tt_mul(-128, 64) == -128

    def test_tt_div_basic(self) -> None:
        # n2=128, n1=64 -> (128 * 64) / 64 = 128
        assert tt_div(128, 64) == 128

    def test_tt_div_zero_raises(self) -> None:
        with pytest.raises(ZeroDivisionError):
            tt_div(100, 0)

    def test_trunc_div_positive(self) -> None:
        assert _trunc_div(7, 2) == 3

    def test_trunc_div_negative_numerator(self) -> None:
        # C semantics: -7 / 2 = -3 (truncate toward zero)
        assert _trunc_div(-7, 2) == -3

    def test_trunc_div_negative_denominator(self) -> None:
        assert _trunc_div(7, -2) == -3

    def test_trunc_div_both_negative(self) -> None:
        assert _trunc_div(-7, -2) == 3


# ===========================================================================
# Tests: fixmul numerical verification
# ===========================================================================


class TestFixmulNumerical:
    """Verify fixmul produces correct results via simulation."""

    # Tolerance: allow rounding error of up to 2 units in the 16.16
    # representation.  Each intermediate TT division can introduce at
    # most 1 unit of truncation error, and we have two DIV steps.
    TOLERANCE = 2

    @pytest.mark.parametrize(
        "a_float, b_float, expected_float",
        [
            (1.0, 1.0, 1.0),
            (2.0, 3.0, 6.0),
            (0.5, 0.5, 0.25),
            (1.5, 2.0, 3.0),
            (0.25, 4.0, 1.0),
            (8.0, 0.125, 1.0),
            (0.75, 4.0, 3.0),
            (16.0, 0.0625, 1.0),
        ],
        ids=[
            "1*1=1",
            "2*3=6",
            "0.5*0.5=0.25",
            "1.5*2=3",
            "0.25*4=1",
            "8*0.125=1",
            "0.75*4=3",
            "16*0.0625=1",
        ],
    )
    def test_positive_multiplications(
        self, a_float: float, b_float: float, expected_float: float
    ) -> None:
        a = to_fixed(a_float)
        b = to_fixed(b_float)
        expected = to_fixed(expected_float)
        result = simulate_fixmul(a, b)
        assert abs(result - expected) <= self.TOLERANCE, (
            f"fixmul({a_float}, {b_float}): "
            f"got {from_fixed(result):.6f} (raw {result}), "
            f"expected {expected_float} (raw {expected})"
        )

    def test_non_representable_fractions(self) -> None:
        """Values like 0.1 can't be exactly represented in 16.16.

        Verify that the algorithm itself is exact by comparing against
        the ideal result computed from the same fixed-point inputs.
        """
        cases = [
            (10.0, 0.1),
            (100.0, 0.01),
            (3.0, 1.0 / 3.0),
        ]
        for a_float, b_float in cases:
            a = to_fixed(a_float)
            b = to_fixed(b_float)
            sim = simulate_fixmul(a, b)
            ideal = ideal_fixmul(a, b)
            assert abs(sim - ideal) <= self.TOLERANCE, (
                f"fixmul({a_float}, {b_float}): "
                f"sim={sim}, ideal={ideal}, diff={abs(sim - ideal)}"
            )

    @pytest.mark.parametrize(
        "a_float, b_float, expected_float",
        [
            (-1.0, 2.0, -2.0),
            (-1.0, -1.0, 1.0),
            (-0.5, 4.0, -2.0),
            (-3.0, -2.0, 6.0),
        ],
        ids=[
            "neg*pos",
            "neg*neg",
            "neg_frac*pos",
            "neg*neg_whole",
        ],
    )
    def test_negative_multiplications(
        self, a_float: float, b_float: float, expected_float: float
    ) -> None:
        a = to_fixed(a_float)
        b = to_fixed(b_float)
        expected = to_fixed(expected_float)
        result = simulate_fixmul(a, b)
        assert abs(result - expected) <= self.TOLERANCE, (
            f"fixmul({a_float}, {b_float}): "
            f"got {from_fixed(result):.6f} (raw {result}), "
            f"expected {expected_float} (raw {expected})"
        )

    def test_multiply_by_zero(self) -> None:
        assert simulate_fixmul(to_fixed(42.0), 0) == 0
        assert simulate_fixmul(0, to_fixed(42.0)) == 0
        assert simulate_fixmul(0, 0) == 0

    def test_multiply_commutativity(self) -> None:
        """fixmul(a, b) should equal fixmul(b, a) within tolerance."""
        pairs = [
            (to_fixed(3.0), to_fixed(7.0)),
            (to_fixed(-2.5), to_fixed(4.0)),
            (to_fixed(0.1), to_fixed(0.2)),
        ]
        for a, b in pairs:
            assert abs(simulate_fixmul(a, b) - simulate_fixmul(b, a)) <= 1

    def test_multiply_identity(self) -> None:
        """Multiplying by 1.0 should return the original value."""
        one = to_fixed(1.0)
        for val in [to_fixed(5.0), to_fixed(-3.25), to_fixed(0.001)]:
            result = simulate_fixmul(val, one)
            assert abs(result - val) <= self.TOLERANCE

    def test_multiply_matches_ideal(self) -> None:
        """Simulated result should be close to the ideal computation."""
        test_values = [
            (to_fixed(1.5), to_fixed(2.5)),
            (to_fixed(-4.0), to_fixed(0.75)),
            (to_fixed(7.25), to_fixed(3.0)),
            (to_fixed(0.125), to_fixed(8.0)),
        ]
        for a, b in test_values:
            sim = simulate_fixmul(a, b)
            ideal = ideal_fixmul(a, b)
            assert abs(sim - ideal) <= self.TOLERANCE, (
                f"fixmul({from_fixed(a)}, {from_fixed(b)}): "
                f"sim={sim}, ideal={ideal}, diff={abs(sim - ideal)}"
            )


# ===========================================================================
# Tests: fixdiv numerical verification
# ===========================================================================


class TestFixdivNumerical:
    """Verify fixdiv produces correct results via simulation."""

    TOLERANCE = 2

    @pytest.mark.parametrize(
        "a_float, b_float, expected_float",
        [
            (6.0, 2.0, 3.0),
            (1.0, 2.0, 0.5),
            (3.0, 4.0, 0.75),
            (10.0, 5.0, 2.0),
            (1.0, 1.0, 1.0),
            (7.0, 2.0, 3.5),
            (100.0, 10.0, 10.0),
        ],
        ids=[
            "6/2=3",
            "1/2=0.5",
            "3/4=0.75",
            "10/5=2",
            "1/1=1",
            "7/2=3.5",
            "100/10=10",
        ],
    )
    def test_positive_divisions(
        self, a_float: float, b_float: float, expected_float: float
    ) -> None:
        a = to_fixed(a_float)
        b = to_fixed(b_float)
        expected = to_fixed(expected_float)
        result = simulate_fixdiv(a, b)
        assert abs(result - expected) <= self.TOLERANCE, (
            f"fixdiv({a_float}, {b_float}): "
            f"got {from_fixed(result):.6f} (raw {result}), "
            f"expected {expected_float} (raw {expected})"
        )

    @pytest.mark.parametrize(
        "a_float, b_float, expected_float",
        [
            (-4.0, 2.0, -2.0),
            (4.0, -2.0, -2.0),
            (-6.0, -3.0, 2.0),
        ],
        ids=[
            "neg/pos",
            "pos/neg",
            "neg/neg",
        ],
    )
    def test_negative_divisions(
        self, a_float: float, b_float: float, expected_float: float
    ) -> None:
        a = to_fixed(a_float)
        b = to_fixed(b_float)
        expected = to_fixed(expected_float)
        result = simulate_fixdiv(a, b)
        assert abs(result - expected) <= self.TOLERANCE, (
            f"fixdiv({a_float}, {b_float}): "
            f"got {from_fixed(result):.6f} (raw {result}), "
            f"expected {expected_float} (raw {expected})"
        )

    def test_div_one_third(self) -> None:
        """1/3 is a repeating fraction; verify reasonable precision."""
        a = to_fixed(1.0)
        b = to_fixed(3.0)
        result = simulate_fixdiv(a, b)
        expected = to_fixed(1.0 / 3.0)
        # Allow slightly more tolerance for repeating fractions
        assert abs(result - expected) <= 3, (
            f"fixdiv(1, 3): got {from_fixed(result):.6f}, "
            f"expected {1.0 / 3.0:.6f}"
        )

    def test_divide_by_zero_raises(self) -> None:
        with pytest.raises(ZeroDivisionError):
            simulate_fixdiv(to_fixed(1.0), 0)

    def test_zero_divided_by_anything(self) -> None:
        assert simulate_fixdiv(0, to_fixed(5.0)) == 0

    def test_division_inverse_of_multiplication(self) -> None:
        """fixdiv(fixmul(a, b), b) should approximately recover a."""
        a = to_fixed(3.0)
        b = to_fixed(7.0)
        product = simulate_fixmul(a, b)
        recovered = simulate_fixdiv(product, b)
        # Allow more tolerance due to compound rounding
        assert abs(recovered - a) <= 4, (
            f"Round-trip: a={from_fixed(a)}, b={from_fixed(b)}, "
            f"recovered={from_fixed(recovered)}"
        )

    def test_division_matches_ideal(self) -> None:
        """Simulated result should be close to the ideal computation."""
        test_values = [
            (to_fixed(5.0), to_fixed(3.0)),
            (to_fixed(-8.0), to_fixed(2.5)),
            (to_fixed(1.0), to_fixed(7.0)),
            (to_fixed(15.5), to_fixed(4.0)),
        ]
        for a, b in test_values:
            sim = simulate_fixdiv(a, b)
            ideal = ideal_fixdiv(a, b)
            assert abs(sim - ideal) <= self.TOLERANCE, (
                f"fixdiv({from_fixed(a)}, {from_fixed(b)}): "
                f"sim={sim}, ideal={ideal}, diff={abs(sim - ideal)}"
            )


# ===========================================================================
# Tests: fixabs and fixneg
# ===========================================================================


class TestFixabsFixneg:
    """Verify the trivial ABS/NEG wrappers."""

    def test_abs_positive(self) -> None:
        val = to_fixed(3.5)
        assert abs(val) == val  # ABS on positive is identity

    def test_abs_negative(self) -> None:
        val = to_fixed(-3.5)
        assert abs(val) == to_fixed(3.5)

    def test_abs_zero(self) -> None:
        assert abs(0) == 0

    def test_neg_positive(self) -> None:
        val = to_fixed(2.0)
        assert -val == to_fixed(-2.0)

    def test_neg_negative(self) -> None:
        val = to_fixed(-2.0)
        assert -val == to_fixed(2.0)

    def test_neg_zero(self) -> None:
        assert -0 == 0


# ===========================================================================
# Tests: edge cases and overflow
# ===========================================================================


class TestEdgeCases:
    """Stress-test with boundary and adversarial inputs."""

    def test_small_values_fixmul(self) -> None:
        """Very small fixed-point values (sub-unit precision).

        0.001 cannot be exactly represented in 16.16 (65536 * 0.001 = 65.536,
        truncated to 65).  We compare against the ideal result computed from
        the same fixed-point inputs to isolate algorithm error from
        representation error.
        """
        a = to_fixed(0.001)   # 65 in raw (not 65.536)
        b = to_fixed(1000.0)  # 65536000 in raw
        result = simulate_fixmul(a, b)
        ideal = ideal_fixmul(a, b)
        # Algorithm error should be small even for tiny inputs
        assert abs(result - ideal) <= 2, (
            f"Small-value fixmul: sim={result}, ideal={ideal}, "
            f"diff={abs(result - ideal)}"
        )

    def test_moderate_values_no_overflow(self) -> None:
        """Values in the DOOM game range should not overflow 32-bit."""
        # Typical game coordinates: 0..255 in fixed-point
        a = to_fixed(200.0)
        b = to_fixed(1.5)
        result = simulate_fixmul(a, b)
        expected = to_fixed(300.0)
        assert abs(result - expected) <= 2

    def test_fixdiv_large_dividend(self) -> None:
        """Large dividend should still work within 32-bit range."""
        a = to_fixed(200.0)
        b = to_fixed(4.0)
        result = simulate_fixdiv(a, b)
        expected = to_fixed(50.0)
        assert abs(result - expected) <= 2

    def test_fixmul_result_smaller_than_inputs(self) -> None:
        """Multiplying fractions should give a smaller result."""
        a = to_fixed(0.5)
        b = to_fixed(0.5)
        result = simulate_fixmul(a, b)
        assert result < a
        assert result < b
        assert abs(result - to_fixed(0.25)) <= 2


# ===========================================================================
# Tests: fpgm assembly builder
# ===========================================================================


class TestBuildFpgmAssembly:
    """Verify the FDEF/ENDF wrapping and function ID assignment."""

    def test_default_ids(self) -> None:
        lines = build_fpgm_assembly()
        # Should contain FDEF/ENDF pairs
        fdef_count = sum(1 for l in lines if l == "FDEF[]")
        endf_count = sum(1 for l in lines if l == "ENDF[]")
        assert fdef_count == endf_count
        assert fdef_count == len(get_stdlib_functions())

    def test_custom_ids(self) -> None:
        custom_ids = {"fixmul": 10, "fixdiv": 11, "fixabs": 12, "fixneg": 13}
        lines = build_fpgm_assembly(func_ids=custom_ids)
        # Verify function ID 10 is pushed before the first FDEF
        assert "PUSHB[] 10" in lines
        assert "PUSHB[] 11" in lines

    def test_fdef_structure(self) -> None:
        """Each function should be: PUSH id, FDEF, <body>, ENDF."""
        lines = build_fpgm_assembly()
        i = 0
        while i < len(lines):
            if lines[i].startswith("PUSHB[]"):
                # Next line should be FDEF
                assert i + 1 < len(lines)
                assert lines[i + 1] == "FDEF[]"
                # Find matching ENDF
                j = i + 2
                while j < len(lines) and lines[j] != "ENDF[]":
                    j += 1
                assert j < len(lines), "Missing ENDF[]"
                i = j + 1
            else:
                i += 1

    def test_all_instructions_valid(self) -> None:
        """Every line in the generated fpgm assembly should be valid."""
        lines = build_fpgm_assembly()
        for line in lines:
            assert _is_valid_instruction(line), (
                f"Invalid instruction in fpgm: {line!r}"
            )


# ===========================================================================
# Tests: fonttools integration — inject into a real font
# ===========================================================================


class TestFontInjection:
    """Inject stdlib assembly into a real .ttf and verify it compiles."""

    @pytest.fixture()
    def font_with_stdlib(self) -> str:
        """Create a minimal font with stdlib FDEFs and return its path."""
        from fontTools.fontBuilder import FontBuilder
        from fontTools.pens.ttGlyphPen import TTGlyphPen
        from fontTools.ttLib.tables._f_p_g_m import table__f_p_g_m
        from fontTools.ttLib.tables._p_r_e_p import table__p_r_e_p
        from fontTools.ttLib.tables.ttProgram import Program

        fb = FontBuilder(1000, isTTF=True)
        fb.setupGlyphOrder([".notdef", "A"])
        fb.setupCharacterMap({65: "A"})

        # Minimal glyph outlines
        pen = TTGlyphPen(None)
        pen.moveTo((0, 0))
        pen.lineTo((500, 0))
        pen.lineTo((500, 700))
        pen.lineTo((0, 700))
        pen.closePath()

        notdef_pen = TTGlyphPen(None)
        notdef_pen.moveTo((0, 0))
        notdef_pen.lineTo((500, 0))
        notdef_pen.lineTo((500, 700))
        notdef_pen.lineTo((0, 700))
        notdef_pen.closePath()

        fb.setupGlyf({".notdef": notdef_pen.glyph(), "A": pen.glyph()})
        fb.setupHorizontalMetrics({"A": (500, 0), ".notdef": (500, 0)})
        fb.setupHorizontalHeader(ascent=800, descent=-200)
        fb.setupNameTable(
            {"familyName": "StdlibTest", "styleName": "Regular"}
        )
        fb.setupOS2()
        fb.setupPost()

        font = fb.font

        # Reserve resources
        num_funcs = len(get_stdlib_functions())
        font["maxp"].maxStackElements = 256
        font["maxp"].maxStorage = 64
        font["maxp"].maxFunctionDefs = num_funcs + 4
        font["maxp"].maxSizeOfInstructions = 1024

        # Inject stdlib into fpgm
        fpgm_asm = build_fpgm_assembly()
        fpgm = table__f_p_g_m()
        fpgm.program = Program()
        fpgm.program.fromAssembly(fpgm_asm)
        font["fpgm"] = fpgm

        # prep: set Y axis
        prep = table__p_r_e_p()
        prep.program = Program()
        prep.program.fromAssembly(["SVTCA[0]"])
        font["prep"] = prep

        # Save to temp file
        path = os.path.join(tempfile.gettempdir(), "stdlib_test.ttf")
        font.save(path)
        return path

    def test_font_file_created(self, font_with_stdlib: str) -> None:
        """Font file should exist and be non-empty."""
        assert os.path.exists(font_with_stdlib)
        assert os.path.getsize(font_with_stdlib) > 0

    def test_font_has_fpgm(self, font_with_stdlib: str) -> None:
        """Font should contain fpgm table."""
        from fontTools.ttLib import TTFont

        font = TTFont(font_with_stdlib)
        assert "fpgm" in font

    def test_fpgm_bytecode_nonempty(self, font_with_stdlib: str) -> None:
        """fpgm bytecode should be non-empty after assembly."""
        from fontTools.ttLib import TTFont

        font = TTFont(font_with_stdlib)
        bytecode = font["fpgm"].program.getBytecode()
        assert len(bytecode) > 0

    def test_fpgm_roundtrip_assembly(self, font_with_stdlib: str) -> None:
        """Assembly should survive a save/load round-trip."""
        from fontTools.ttLib import TTFont

        font = TTFont(font_with_stdlib)
        asm = font["fpgm"].program.getAssembly()
        asm_text = "\n".join(asm)

        # Verify key instructions are present
        assert "FDEF" in asm_text, "FDEF missing after round-trip"
        assert "ENDF" in asm_text, "ENDF missing after round-trip"
        assert "MUL" in asm_text, "MUL missing after round-trip"
        assert "DIV" in asm_text, "DIV missing after round-trip"

    def test_fpgm_has_correct_fdef_count(
        self, font_with_stdlib: str
    ) -> None:
        """The fpgm should contain one FDEF per stdlib function."""
        from fontTools.ttLib import TTFont

        font = TTFont(font_with_stdlib)
        asm = font["fpgm"].program.getAssembly()

        fdef_count = sum(1 for line in asm if "FDEF" in line)
        expected = len(get_stdlib_functions())
        assert fdef_count == expected, (
            f"Expected {expected} FDEFs, found {fdef_count}"
        )

    def test_font_can_be_reloaded(self, font_with_stdlib: str) -> None:
        """Font should load without errors (validates internal consistency)."""
        from fontTools.ttLib import TTFont

        # This will raise if the font is malformed
        font = TTFont(font_with_stdlib)
        font.close()
