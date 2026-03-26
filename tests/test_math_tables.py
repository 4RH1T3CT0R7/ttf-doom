"""Tests for sin/cos lookup table generation.

Validates that generate_sin_cos_tables produces correct fixed-point
values for cardinal angles, that all values fit in PUSHW range, and
that generate_prep_load_tables emits valid TrueType assembly.
"""

import os
import sys

import pytest

# Ensure the project root is on sys.path so fontgen is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fontgen.math_tables import (
    _push_and_store,
    generate_prep_load_tables,
    generate_sin_cos_tables,
)


# ---------------------------------------------------------------------------
# Table size tests
# ---------------------------------------------------------------------------


def test_sin_table_has_256_entries() -> None:
    """Default sin table has exactly 256 entries."""
    sin_table, _ = generate_sin_cos_tables()
    assert len(sin_table) == 256


def test_cos_table_has_256_entries() -> None:
    """Default cos table has exactly 256 entries."""
    _, cos_table = generate_sin_cos_tables()
    assert len(cos_table) == 256


def test_custom_entry_count() -> None:
    """Tables respect custom entry count."""
    sin_table, cos_table = generate_sin_cos_tables(entries=128)
    assert len(sin_table) == 128
    assert len(cos_table) == 128


# ---------------------------------------------------------------------------
# Cardinal angle values (scale=256, 256 entries)
# ---------------------------------------------------------------------------
#
# With 256 entries covering a full circle:
#   index   0 =   0 deg -> sin=0,   cos=256
#   index  64 =  90 deg -> sin=256, cos=0
#   index 128 = 180 deg -> sin=0,   cos=-256
#   index 192 = 270 deg -> sin=-256,cos=0


def test_sin_0_is_zero() -> None:
    """sin(0) == 0."""
    sin_table, _ = generate_sin_cos_tables(scale=256)
    assert sin_table[0] == 0


def test_sin_90_is_scale() -> None:
    """sin(90 deg) == scale (256)."""
    sin_table, _ = generate_sin_cos_tables(scale=256)
    assert sin_table[64] == 256


def test_sin_180_is_zero() -> None:
    """sin(180 deg) == 0."""
    sin_table, _ = generate_sin_cos_tables(scale=256)
    assert sin_table[128] == 0


def test_sin_270_is_neg_scale() -> None:
    """sin(270 deg) == -scale (-256)."""
    sin_table, _ = generate_sin_cos_tables(scale=256)
    assert sin_table[192] == -256


def test_cos_0_is_scale() -> None:
    """cos(0) == scale (256)."""
    _, cos_table = generate_sin_cos_tables(scale=256)
    assert cos_table[0] == 256


def test_cos_90_is_zero() -> None:
    """cos(90 deg) == 0."""
    _, cos_table = generate_sin_cos_tables(scale=256)
    assert cos_table[64] == 0


def test_cos_180_is_neg_scale() -> None:
    """cos(180 deg) == -scale (-256)."""
    _, cos_table = generate_sin_cos_tables(scale=256)
    assert cos_table[128] == -256


def test_cos_270_is_zero() -> None:
    """cos(270 deg) == 0."""
    _, cos_table = generate_sin_cos_tables(scale=256)
    assert cos_table[192] == 0


# ---------------------------------------------------------------------------
# Value range tests
# ---------------------------------------------------------------------------


def test_all_sin_values_within_pushw_range() -> None:
    """All sin values with scale=256 fit in a signed 16-bit word."""
    sin_table, _ = generate_sin_cos_tables(scale=256)
    for i, val in enumerate(sin_table):
        assert -32768 <= val <= 32767, (
            f"sin_table[{i}] = {val} out of PUSHW range"
        )


def test_all_cos_values_within_pushw_range() -> None:
    """All cos values with scale=256 fit in a signed 16-bit word."""
    _, cos_table = generate_sin_cos_tables(scale=256)
    for i, val in enumerate(cos_table):
        assert -32768 <= val <= 32767, (
            f"cos_table[{i}] = {val} out of PUSHW range"
        )


def test_sin_values_bounded_by_scale() -> None:
    """All sin values have magnitude <= scale."""
    scale = 256
    sin_table, _ = generate_sin_cos_tables(scale=scale)
    for i, val in enumerate(sin_table):
        assert -scale <= val <= scale, (
            f"sin_table[{i}] = {val} exceeds scale {scale}"
        )


def test_cos_values_bounded_by_scale() -> None:
    """All cos values have magnitude <= scale."""
    scale = 256
    _, cos_table = generate_sin_cos_tables(scale=scale)
    for i, val in enumerate(cos_table):
        assert -scale <= val <= scale, (
            f"cos_table[{i}] = {val} exceeds scale {scale}"
        )


# ---------------------------------------------------------------------------
# Custom scale tests
# ---------------------------------------------------------------------------


def test_scale_32767() -> None:
    """Scale=32767 produces sin(90deg) == 32767."""
    sin_table, cos_table = generate_sin_cos_tables(scale=32767)
    assert sin_table[64] == 32767
    assert cos_table[0] == 32767


def test_scale_1() -> None:
    """Scale=1 produces sin(90deg) == 1."""
    sin_table, _ = generate_sin_cos_tables(scale=1)
    assert sin_table[64] == 1


# ---------------------------------------------------------------------------
# Symmetry tests
# ---------------------------------------------------------------------------


def test_sin_symmetry() -> None:
    """sin(x) == -sin(x + 128) for all x (half-circle symmetry)."""
    sin_table, _ = generate_sin_cos_tables(scale=256)
    for i in range(128):
        assert sin_table[i] == -sin_table[i + 128], (
            f"Symmetry broken at index {i}: "
            f"sin[{i}]={sin_table[i]}, sin[{i + 128}]={sin_table[i + 128]}"
        )


def test_cos_is_shifted_sin() -> None:
    """cos(x) == sin(x + 64) (quarter-circle phase shift)."""
    sin_table, cos_table = generate_sin_cos_tables(scale=256)
    for i in range(256):
        j = (i + 64) % 256
        assert cos_table[i] == sin_table[j], (
            f"Phase shift broken at index {i}: "
            f"cos[{i}]={cos_table[i]}, sin[{j}]={sin_table[j]}"
        )


# ---------------------------------------------------------------------------
# Assembly generation tests
# ---------------------------------------------------------------------------


def test_prep_load_tables_generates_assembly() -> None:
    """generate_prep_load_tables produces non-empty assembly."""
    sin_table, cos_table = generate_sin_cos_tables(entries=4, scale=256)
    asm = generate_prep_load_tables(sin_table, cos_table, sin_base=0, cos_base=4)
    assert len(asm) > 0


def test_prep_load_tables_correct_instruction_count() -> None:
    """Each table entry produces 4 instructions (push val, push idx, SWAP, WS)."""
    sin_table, cos_table = generate_sin_cos_tables(entries=4, scale=256)
    asm = generate_prep_load_tables(sin_table, cos_table, sin_base=0, cos_base=4)
    # 4 sin entries + 4 cos entries = 8 values, each needs 4 instructions
    assert len(asm) == 8 * 4


def test_prep_load_tables_contains_ws() -> None:
    """Assembly includes WS[] instructions for storing values."""
    sin_table, cos_table = generate_sin_cos_tables(entries=4, scale=256)
    asm = generate_prep_load_tables(sin_table, cos_table, sin_base=0, cos_base=4)
    ws_count = sum(1 for line in asm if line == "WS[]")
    assert ws_count == 8, f"Expected 8 WS[] instructions, got {ws_count}"


def test_prep_load_tables_correct_indices() -> None:
    """Assembly stores values at the correct storage indices."""
    sin_table, cos_table = generate_sin_cos_tables(entries=4, scale=256)
    asm = generate_prep_load_tables(
        sin_table, cos_table, sin_base=100, cos_base=200
    )
    # Extract all PUSHB/PUSHW instructions that set storage indices.
    # Pattern: value_push, index_push, SWAP, WS
    # Every 4th instruction starting at index 1 is the index push.
    indices_found = []
    for i in range(1, len(asm), 4):
        line = asm[i]
        if "PUSHB[]" in line:
            indices_found.append(int(line.split()[-1]))
        elif "PUSHW[]" in line:
            indices_found.append(int(line.split()[-1]))

    expected_indices = (
        [100, 101, 102, 103] +  # sin_base + 0..3
        [200, 201, 202, 203]    # cos_base + 0..3
    )
    assert indices_found == expected_indices, (
        f"Expected indices {expected_indices}, got {indices_found}"
    )


def test_prep_load_positive_value_uses_pushb() -> None:
    """Positive values in [0, 255] use PUSHB."""
    asm = _push_and_store(0, 128)
    assert asm[0] == "PUSHB[] 128"


def test_prep_load_negative_value_uses_pushw() -> None:
    """Negative values use PUSHW."""
    asm = _push_and_store(0, -100)
    assert asm[0] == "PUSHW[] -100"


def test_prep_load_large_index_uses_pushw() -> None:
    """Storage indices > 255 use PUSHW."""
    asm = _push_and_store(300, 42)
    assert asm[1] == "PUSHW[] 300"


def test_prep_load_small_index_uses_pushb() -> None:
    """Storage indices in [0, 255] use PUSHB."""
    asm = _push_and_store(10, 42)
    assert asm[1] == "PUSHB[] 10"


def test_prep_load_swap_and_ws() -> None:
    """Each _push_and_store call ends with SWAP[] and WS[]."""
    asm = _push_and_store(5, 100)
    assert asm[2] == "SWAP[]"
    assert asm[3] == "WS[]"
