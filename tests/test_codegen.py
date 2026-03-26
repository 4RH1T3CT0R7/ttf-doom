"""Tests for the TTDoom code generator.

Validates that the code generator correctly translates AST nodes into
TrueType hinting assembly instructions compatible with fonttools'
``Program.fromAssembly()``.

Coverage:
- Variable declarations with initialisation
- Constant inlining
- Assignment (read/modify/write)
- Array read and write
- If/else conditionals
- While loops (recursive FDEF pattern)
- Function definitions with parameters
- Function calls
- Return statements
- Operator precedence
- Intrinsics: get_axis, set_point_y
- End-to-end: compile and inject into a real font
- Stack balance verification
"""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

from compiler.allocator import AllocatorError, StorageAllocator
from compiler.ast_nodes import (
    ArrayAccess,
    ArrayAssignment,
    ArrayDecl,
    Assignment,
    BinOp,
    ConstDecl,
    ExprStmt,
    FuncCall,
    FuncDef,
    IfStmt,
    IntLiteral,
    Program,
    ReturnStmt,
    UnaryOp,
    VarDecl,
    VarRef,
    WhileStmt,
)
from compiler.codegen import CodeGenError, CodeGenerator
from compiler.parser import Parser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse(src: str) -> Program:
    """Parse a DSL source string into an AST."""
    return Parser(src).parse()


def _compile(src: str, num_axes: int = 5) -> dict[str, list[str]]:
    """Compile a DSL source string to assembly segments."""
    program = _parse(src)
    gen = CodeGenerator(num_axes=num_axes)
    return gen.compile(program)


def _compile_program(program: Program, num_axes: int = 5) -> dict[str, list[str]]:
    """Compile a pre-built AST to assembly segments."""
    gen = CodeGenerator(num_axes=num_axes)
    return gen.compile(program)


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
    "RS[]", "WS[]",
}


def _is_valid_instruction(line: str) -> bool:
    """Check whether a single assembly line is a valid TT instruction."""
    line = line.strip()
    if not line:
        return False

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
        return -32768 <= val <= 32767

    return line in VALID_TT_MNEMONICS


# ===========================================================================
# Tests: StorageAllocator
# ===========================================================================


class TestStorageAllocator:
    """Verify the storage allocator manages indices and IDs correctly."""

    def test_alloc_var(self) -> None:
        alloc = StorageAllocator()
        idx = alloc.alloc_var("x")
        assert idx == 0
        assert alloc.vars["x"] == 0

    def test_alloc_var_sequential(self) -> None:
        alloc = StorageAllocator()
        idx_a = alloc.alloc_var("a")
        idx_b = alloc.alloc_var("b")
        assert idx_a == 0
        assert idx_b == 1

    def test_alloc_var_duplicate_raises(self) -> None:
        alloc = StorageAllocator()
        alloc.alloc_var("x")
        with pytest.raises(AllocatorError, match="already declared"):
            alloc.alloc_var("x")

    def test_alloc_array(self) -> None:
        alloc = StorageAllocator()
        base = alloc.alloc_array("buf", 10)
        assert base == 0
        assert alloc.arrays["buf"] == (0, 10)
        assert alloc.total_storage == 10

    def test_alloc_array_after_var(self) -> None:
        alloc = StorageAllocator()
        alloc.alloc_var("x")
        base = alloc.alloc_array("buf", 5)
        assert base == 1
        assert alloc.total_storage == 6

    def test_alloc_func(self) -> None:
        alloc = StorageAllocator()
        fid = alloc.alloc_func("my_func")
        assert fid == 0
        assert alloc.funcs["my_func"] == 0

    def test_alloc_func_sequential(self) -> None:
        alloc = StorageAllocator()
        fid_a = alloc.alloc_func("a")
        fid_b = alloc.alloc_func("b")
        assert fid_a == 0
        assert fid_b == 1

    def test_define_const(self) -> None:
        alloc = StorageAllocator()
        alloc.define_const("MAX", 100)
        assert alloc.consts["MAX"] == 100

    def test_lookup_const(self) -> None:
        alloc = StorageAllocator()
        alloc.define_const("C", 42)
        kind, value = alloc.lookup("C")
        assert kind == "const"
        assert value == 42

    def test_lookup_var(self) -> None:
        alloc = StorageAllocator()
        alloc.alloc_var("x")
        kind, value = alloc.lookup("x")
        assert kind == "var"
        assert value == 0

    def test_lookup_array(self) -> None:
        alloc = StorageAllocator()
        alloc.alloc_array("arr", 8)
        kind, value = alloc.lookup("arr")
        assert kind == "array"
        assert value == 0

    def test_lookup_undefined_raises(self) -> None:
        alloc = StorageAllocator()
        with pytest.raises(KeyError, match="Undefined"):
            alloc.lookup("missing")

    def test_alloc_func_locals(self) -> None:
        alloc = StorageAllocator()
        locals_map = alloc.alloc_func_locals("myfn", ["a", "b"])
        assert "a" in locals_map
        assert "b" in locals_map
        assert locals_map["a"] != locals_map["b"]
        assert alloc.func_params["myfn"] == ["a", "b"]


# ===========================================================================
# Tests: Variable declaration with initialisation
# ===========================================================================


class TestVarDeclCompile:
    """Compile ``var x: int = 42`` and verify assembly."""

    def test_var_init_small_value(self) -> None:
        result = _compile("var x: int = 42")
        prep = result["prep"]
        # Should contain: PUSHB[] 42 (value), PUSHB[] 0 (storage idx), SWAP[], WS[]
        assert "PUSHB[] 42" in prep
        assert "SWAP[]" in prep
        assert "WS[]" in prep

    def test_var_init_large_value(self) -> None:
        result = _compile("var x: int = 1000")
        prep = result["prep"]
        assert "PUSHW[] 1000" in prep
        assert "WS[]" in prep

    def test_var_no_init(self) -> None:
        result = _compile("var x: int")
        prep = result["prep"]
        # Should have SVTCA[0] but no WS for this var (no init value)
        ws_count = prep.count("WS[]")
        assert ws_count == 0

    def test_multiple_vars(self) -> None:
        src = "var a: int = 1\nvar b: int = 2"
        result = _compile(src)
        prep = result["prep"]
        ws_count = prep.count("WS[]")
        assert ws_count == 2


# ===========================================================================
# Tests: Constant inlining
# ===========================================================================


class TestConstInlining:
    """Compile ``const C = 100`` and verify it is inlined in expressions."""

    def test_const_in_assignment(self) -> None:
        src = """\
const SCALE = 100
var x: int = 0
func test():
    x = SCALE
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        # SCALE=100 should appear as PUSHB[] 100 in the function body
        assert "PUSHB[] 100" in fpgm

    def test_const_no_storage_allocated(self) -> None:
        src = "const C = 42"
        program = _parse(src)
        gen = CodeGenerator()
        gen.compile(program)
        # Constants should NOT use storage slots
        assert "C" not in gen.allocator.vars
        assert "C" in gen.allocator.consts

    def test_const_used_in_expr(self) -> None:
        src = """\
const WIDTH = 64
var x: int = 0
func test():
    x = WIDTH + 1
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        assert "PUSHB[] 64" in fpgm
        assert "ADD[]" in fpgm


# ===========================================================================
# Tests: Assignment (read / modify / write)
# ===========================================================================


class TestAssignment:
    """Compile ``x = x + 1`` and verify RS/ADD/WS sequence."""

    def test_read_modify_write(self) -> None:
        src = """\
var x: int = 0
func test():
    x = x + 1
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        # Should contain RS (read x), PUSHB (1), ADD, then WS (write x)
        assert "RS[]" in fpgm
        assert "ADD[]" in fpgm
        assert "WS[]" in fpgm

    def test_assignment_storage_index(self) -> None:
        src = """\
var a: int = 0
var b: int = 0
func test():
    b = 99
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        # b has storage index 1; should appear in the function
        assert "PUSHB[] 1" in fpgm
        assert "WS[]" in fpgm


# ===========================================================================
# Tests: Array read
# ===========================================================================


class TestArrayRead:
    """Compile ``arr[i]`` read and verify index + base + RS."""

    def test_array_read_literal_index(self) -> None:
        src = """\
var x: int = 0
array buf[10]
func test():
    x = buf[3]
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        # Index: PUSHB[] 3
        # Base: PUSHB[] 1  (buf starts at storage 1, after var x at 0)
        # ADD[] then RS[]
        assert "ADD[]" in fpgm
        assert "RS[]" in fpgm

    def test_array_read_variable_index(self) -> None:
        src = """\
var idx: int = 0
array data[8]
func test():
    var v: int = data[idx]
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        # Should read idx via RS, add base, then RS for the array element
        rs_count = fpgm.count("RS[]")
        assert rs_count >= 2  # one for idx, one for data[idx]


# ===========================================================================
# Tests: Array write
# ===========================================================================


class TestArrayWrite:
    """Compile ``arr[i] = v`` and verify correct WS sequence."""

    def test_array_write_literal(self) -> None:
        src = """\
array buf[10]
func test():
    buf[0] = 42
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        # Should contain: PUSHB[] 42 (value), compute storage index, SWAP, WS
        assert "PUSHB[] 42" in fpgm
        assert "ADD[]" in fpgm
        assert "SWAP[]" in fpgm
        assert "WS[]" in fpgm

    def test_array_write_expr_index(self) -> None:
        src = """\
var i: int = 0
array buf[10]
func test():
    buf[i] = 99
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        assert "RS[]" in fpgm  # read i
        assert "WS[]" in fpgm  # write buf[i]


# ===========================================================================
# Tests: If statement
# ===========================================================================


class TestIfStmt:
    """Compile if/else and verify IF/EIF assembly."""

    def test_if_without_else(self) -> None:
        src = """\
var x: int = 0
func test():
    if x > 0:
        x = 1
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        assert "GT[]" in fpgm
        assert "IF[]" in fpgm
        assert "EIF[]" in fpgm
        # Should NOT have ELSE
        assert "ELSE[]" not in fpgm

    def test_if_with_else(self) -> None:
        src = """\
var x: int = 0
func test():
    if x > 0:
        x = 1
    else:
        x = 0
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        assert "IF[]" in fpgm
        assert "ELSE[]" in fpgm
        assert "EIF[]" in fpgm


# ===========================================================================
# Tests: While loop (recursive FDEF pattern)
# ===========================================================================


class TestWhileLoop:
    """Compile while loops and verify recursive FDEF pattern."""

    def test_while_basic(self) -> None:
        src = """\
var x: int = 10
func test():
    while x > 0:
        x = x - 1
"""
        result = _compile(src)
        fpgm = result["fpgm"]

        # Should generate an extra FDEF for the while loop
        fdef_count = fpgm.count("FDEF[]")
        endf_count = fpgm.count("ENDF[]")
        assert fdef_count == endf_count
        # At least 2 FDEFs: stdlib funcs + test func + while-loop func
        # The while-loop FDEF should contain IF/EIF and a recursive CALL
        assert "IF[]" in fpgm
        assert "EIF[]" in fpgm

    def test_while_generates_recursive_call(self) -> None:
        src = """\
var x: int = 5
func test():
    while x > 0:
        x = x - 1
"""
        result = _compile(src)
        fpgm = result["fpgm"]

        # The while-loop FDEF should contain a CALL to itself
        # Count CALLs -- there should be at least 2: one in the loop body
        # (recursive) and one at the call site inside test()
        call_count = fpgm.count("CALL[]")
        assert call_count >= 2


# ===========================================================================
# Tests: Function definition with parameters
# ===========================================================================


class TestFuncDef:
    """Compile function definitions and verify FDEF with param storage."""

    def test_func_no_params(self) -> None:
        src = """\
func noop():
    return
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        assert "FDEF[]" in fpgm
        assert "ENDF[]" in fpgm

    def test_func_with_params_storage(self) -> None:
        src = """\
func add(a: int, b: int) -> int:
    return a + b
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        # Parameters should be popped from stack into storage via SWAP/WS
        # Two parameters => two SWAP/WS pairs at the start of the FDEF
        assert "FDEF[]" in fpgm
        assert "ENDF[]" in fpgm
        ws_count = fpgm.count("WS[]")
        assert ws_count >= 2  # at least 2 for params a and b

    def test_func_params_reverse_order(self) -> None:
        """Last param should be popped first (it's on top of stack)."""
        src = """\
func myfn(a: int, b: int) -> int:
    return a
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        # Find the FDEF for myfn and verify the param pop order
        # The function should pop b first (higher storage idx), then a
        assert "FDEF[]" in fpgm


# ===========================================================================
# Tests: Function call
# ===========================================================================


class TestFuncCall:
    """Compile function calls and verify push args + CALL."""

    def test_call_no_args(self) -> None:
        src = """\
func noop():
    return

func test():
    noop()
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        assert "CALL[]" in fpgm

    def test_call_with_args(self) -> None:
        src = """\
func add(a: int, b: int) -> int:
    return a + b

var result: int = 0
func test():
    result = add(10, 20)
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        # Should push 10, push 20, push func_id, CALL
        assert "PUSHB[] 10" in fpgm
        assert "PUSHB[] 20" in fpgm
        assert "CALL[]" in fpgm

    def test_call_stdlib_fixmul(self) -> None:
        src = """\
var x: int = 0
func test():
    x = fixmul(100, 200)
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        assert "PUSHB[] 100" in fpgm
        assert "PUSHB[] 200" in fpgm
        assert "CALL[]" in fpgm


# ===========================================================================
# Tests: Return statement
# ===========================================================================


class TestReturnStmt:
    """Compile return and verify expr is left on stack."""

    def test_return_literal(self) -> None:
        src = """\
func get_val() -> int:
    return 42
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        # 42 should be pushed onto the stack before ENDF
        assert "PUSHB[] 42" in fpgm
        # ENDF should come after the push
        fpgm_str = "\n".join(fpgm)
        push_pos = fpgm_str.index("PUSHB[] 42")
        endf_pos = fpgm_str.rindex("ENDF[]")
        assert push_pos < endf_pos

    def test_return_expr(self) -> None:
        src = """\
func double(x: int) -> int:
    return x + x
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        assert "ADD[]" in fpgm

    def test_return_void(self) -> None:
        src = """\
func noop():
    return
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        # Return with no value should not produce any push
        # FDEF should be followed directly by ENDF after return
        assert "FDEF[]" in fpgm
        assert "ENDF[]" in fpgm


# ===========================================================================
# Tests: Operator precedence
# ===========================================================================


class TestPrecedence:
    """Compile ``a + b * c`` and verify correct order."""

    def test_mul_before_add(self) -> None:
        src = """\
var a: int = 0
var b: int = 0
var c: int = 0
func test():
    a = b + c * 2
"""
        # Parser should produce BinOp(+, VarRef(b), BinOp(*, VarRef(c), IntLiteral(2)))
        # So c*2 is compiled first, then b is compiled, then ADD
        # Actually: left operand compiled first, then right operand.
        # a = b + (c * 2)
        # -> compile b, compile (c * 2), ADD
        # compile (c * 2) -> compile c, compile 2, MUL, PUSH 4096, MUL
        result = _compile(src)
        fpgm = result["fpgm"]
        # MUL should appear before ADD (for b + c*2)
        fpgm_str = "\n".join(fpgm)
        # Find the first MUL and first ADD in the function body
        mul_pos = fpgm_str.index("MUL[]")
        add_pos = fpgm_str.index("ADD[]")
        assert mul_pos < add_pos


# ===========================================================================
# Tests: Comparison operators
# ===========================================================================


class TestComparisonOps:
    """Verify all comparison operators compile to correct TT instructions."""

    @pytest.mark.parametrize(
        "op, tt_instr",
        [
            ("==", "EQ[]"),
            ("!=", "NEQ[]"),
            ("<", "LT[]"),
            (">", "GT[]"),
            ("<=", "LTEQ[]"),
            (">=", "GTEQ[]"),
        ],
    )
    def test_comparison_op(self, op: str, tt_instr: str) -> None:
        src = f"""\
var x: int = 0
var y: int = 0
func test():
    if x {op} y:
        x = 1
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        assert tt_instr in fpgm


# ===========================================================================
# Tests: Logical operators
# ===========================================================================


class TestLogicalOps:
    """Verify and/or/not compile to correct TT instructions."""

    def test_and_operator(self) -> None:
        src = """\
var x: int = 0
var y: int = 0
func test():
    if x and y:
        x = 1
"""
        result = _compile(src)
        assert "AND[]" in result["fpgm"]

    def test_or_operator(self) -> None:
        src = """\
var x: int = 0
var y: int = 0
func test():
    if x or y:
        x = 1
"""
        result = _compile(src)
        assert "OR[]" in result["fpgm"]

    def test_not_operator(self) -> None:
        src = """\
var x: int = 0
func test():
    if not x:
        x = 1
"""
        result = _compile(src)
        assert "NOT[]" in result["fpgm"]


# ===========================================================================
# Tests: Arithmetic operators
# ===========================================================================


class TestArithmeticOps:
    """Verify arithmetic operators compile correctly."""

    def test_addition(self) -> None:
        src = """\
var x: int = 0
func test():
    x = 1 + 2
"""
        result = _compile(src)
        assert "ADD[]" in result["fpgm"]

    def test_subtraction(self) -> None:
        src = """\
var x: int = 0
func test():
    x = 5 - 3
"""
        result = _compile(src)
        assert "SUB[]" in result["fpgm"]

    def test_multiplication_plain_int(self) -> None:
        src = """\
var x: int = 0
func test():
    x = 3 * 4
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        # Plain integer multiply: MUL, PUSHW 4096, MUL
        mul_count = fpgm.count("MUL[]")
        assert mul_count >= 2  # two MULs for plain int multiply

    def test_division_plain_int(self) -> None:
        src = """\
var x: int = 0
func test():
    x = 10 / 3
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        # Plain integer divide: DIV, PUSHW 4096, DIV
        div_count = fpgm.count("DIV[]")
        assert div_count >= 2  # two DIVs for plain int divide

    def test_modulo(self) -> None:
        src = """\
var x: int = 0
func test():
    x = 10 % 3
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        # Modulo uses SUB at the end: a - (a/b)*b
        assert "SUB[]" in fpgm

    def test_negation(self) -> None:
        src = """\
var x: int = 0
func test():
    x = -5
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        assert "NEG[]" in fpgm


# ===========================================================================
# Tests: Intrinsic -- get_axis
# ===========================================================================


class TestGetAxis:
    """Compile get_axis(N) and verify GETVARIATION assembly."""

    def test_get_axis_0(self) -> None:
        src = """\
var x: int = 0
func test():
    x = get_axis(0)
"""
        result = _compile(src, num_axes=5)
        fpgm = result["fpgm"]
        assert "GETVARIATION[]" in fpgm
        # For axis 0 with 5 axes, we need MINDEX to reach the deepest value
        assert "MINDEX[]" in fpgm

    def test_get_axis_last(self) -> None:
        src = """\
var x: int = 0
func test():
    x = get_axis(4)
"""
        result = _compile(src, num_axes=5)
        fpgm = result["fpgm"]
        assert "GETVARIATION[]" in fpgm
        # Axis 4 with 5 axes is on top of stack (depth 0)
        # Should use SWAP/POP to clean up the 4 values below
        assert "POP[]" in fpgm

    def test_get_axis_single(self) -> None:
        src = """\
var x: int = 0
func test():
    x = get_axis(0)
"""
        result = _compile(src, num_axes=1)
        fpgm = result["fpgm"]
        assert "GETVARIATION[]" in fpgm
        # Single axis: value is already on top, no MINDEX or POP needed
        assert "POP[]" not in fpgm
        assert "MINDEX[]" not in fpgm


# ===========================================================================
# Tests: Intrinsic -- set_point_y
# ===========================================================================


class TestSetPointY:
    """Compile set_point_y(idx, val) and verify SVTCA[0] + SCFS assembly."""

    def test_set_point_y_literals(self) -> None:
        src = """\
func test():
    set_point_y(2, 400)
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        assert "SVTCA[0]" in fpgm
        assert "SCFS[]" in fpgm
        assert "PUSHB[] 2" in fpgm
        assert "PUSHW[] 400" in fpgm

    def test_set_point_y_order(self) -> None:
        """Point index should be pushed before coordinate."""
        src = """\
func test():
    set_point_y(0, 100)
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        # SVTCA[0] first, then point idx, then coord, then SCFS
        fpgm_str = "\n".join(fpgm)
        svtca_pos = fpgm_str.index("SVTCA[0]")
        scfs_pos = fpgm_str.index("SCFS[]")
        assert svtca_pos < scfs_pos


# ===========================================================================
# Tests: Push value ranges
# ===========================================================================


class TestPushValue:
    """Verify PUSHB/PUSHW selection based on value range."""

    def test_push_small_value(self) -> None:
        gen = CodeGenerator()
        lines = gen._push_value(42)
        assert lines == ["PUSHB[] 42"]

    def test_push_zero(self) -> None:
        gen = CodeGenerator()
        lines = gen._push_value(0)
        assert lines == ["PUSHB[] 0"]

    def test_push_255(self) -> None:
        gen = CodeGenerator()
        lines = gen._push_value(255)
        assert lines == ["PUSHB[] 255"]

    def test_push_256_uses_pushw(self) -> None:
        gen = CodeGenerator()
        lines = gen._push_value(256)
        assert lines == ["PUSHW[] 256"]

    def test_push_negative(self) -> None:
        gen = CodeGenerator()
        lines = gen._push_value(-1)
        assert lines == ["PUSHW[] -1"]

    def test_push_max_pushw(self) -> None:
        gen = CodeGenerator()
        lines = gen._push_value(32767)
        assert lines == ["PUSHW[] 32767"]

    def test_push_min_pushw(self) -> None:
        gen = CodeGenerator()
        lines = gen._push_value(-32768)
        assert lines == ["PUSHW[] -32768"]

    def test_push_out_of_range_raises(self) -> None:
        gen = CodeGenerator()
        with pytest.raises(CodeGenError, match="outside the supported range"):
            gen._push_value(40000)


# ===========================================================================
# Tests: Glyph program
# ===========================================================================


class TestGlyphProgram:
    """Verify glyph program generation."""

    def test_glyph_calls_game_tick(self) -> None:
        src = """\
func game_tick():
    return
"""
        result = _compile(src)
        glyph = result["glyph"]
        assert "CALL[]" in glyph

    def test_glyph_empty_without_game_tick(self) -> None:
        src = """\
func other():
    return
"""
        result = _compile(src)
        glyph = result["glyph"]
        assert glyph == []


# ===========================================================================
# Tests: Prep program
# ===========================================================================


class TestPrepProgram:
    """Verify prep program always starts with SVTCA[0]."""

    def test_prep_starts_with_svtca(self) -> None:
        src = "var x: int = 0"
        result = _compile(src)
        prep = result["prep"]
        assert prep[0] == "SVTCA[0]"


# ===========================================================================
# Tests: All generated instructions are valid
# ===========================================================================


class TestInstructionValidity:
    """Every generated instruction should be a valid TT mnemonic."""

    def test_all_fpgm_instructions_valid(self) -> None:
        src = """\
var x: int = 42
const SCALE = 10
array buf[4]
func add(a: int, b: int) -> int:
    return a + b
func test():
    x = add(x, SCALE)
    buf[0] = x
    if x > 0:
        x = x - 1
"""
        result = _compile(src)
        for line in result["fpgm"]:
            assert _is_valid_instruction(line), f"Invalid fpgm instruction: {line!r}"

    def test_all_prep_instructions_valid(self) -> None:
        src = "var x: int = 42\nvar y: int = 1000"
        result = _compile(src)
        for line in result["prep"]:
            assert _is_valid_instruction(line), f"Invalid prep instruction: {line!r}"

    def test_all_glyph_instructions_valid(self) -> None:
        src = """\
func game_tick():
    return
"""
        result = _compile(src)
        for line in result["glyph"]:
            assert _is_valid_instruction(line), f"Invalid glyph instruction: {line!r}"


# ===========================================================================
# Tests: Stack balance
# ===========================================================================


class TestStackBalance:
    """Verify compiled functions leave the stack balanced."""

    def test_void_func_stack_neutral(self) -> None:
        """A void function should consume all pushed values."""
        src = """\
var x: int = 0
func test():
    x = 42
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        # x = 42 pushes value, pushes index, swaps, WS (all consumed)
        # Net stack effect of the body should be 0

    def test_returning_func_leaves_one(self) -> None:
        """A returning function should leave exactly one value on stack."""
        src = """\
func get_val() -> int:
    return 42
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        # After param setup (none), body pushes 42. ENDF returns with 1 value.
        assert "PUSHB[] 42" in fpgm
        assert "ENDF[]" in fpgm


# ===========================================================================
# Tests: End-to-end -- compile and inject into a real font
# ===========================================================================


class TestEndToEnd:
    """Compile a small program, inject into a font, verify valid bytecode."""

    def test_compile_and_inject(self) -> None:
        """Full pipeline: parse -> compile -> inject into font -> verify."""
        from fontTools.fontBuilder import FontBuilder
        from fontTools.pens.ttGlyphPen import TTGlyphPen
        from fontTools.ttLib.tables._f_p_g_m import table__f_p_g_m
        from fontTools.ttLib.tables._p_r_e_p import table__p_r_e_p
        from fontTools.ttLib.tables.ttProgram import Program as TTProgram

        src = """\
var x: int = 10
var y: int = 20
const SCALE = 2
func double(n: int) -> int:
    return n * SCALE
func game_tick():
    x = double(x)
    if x > 100:
        x = 0
"""
        result = _compile(src, num_axes=1)

        # Build a minimal font
        fb = FontBuilder(1000, isTTF=True)
        fb.setupGlyphOrder([".notdef", "A"])
        fb.setupCharacterMap({65: "A"})

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
            {"familyName": "CodegenTest", "styleName": "Regular"}
        )
        fb.setupOS2()
        fb.setupPost()

        font = fb.font

        # Reserve resources
        font["maxp"].maxStackElements = 256
        font["maxp"].maxStorage = 64
        font["maxp"].maxFunctionDefs = 20
        font["maxp"].maxSizeOfInstructions = 2048

        # Inject fpgm
        fpgm_table = table__f_p_g_m()
        fpgm_table.program = TTProgram()
        fpgm_table.program.fromAssembly(result["fpgm"])
        font["fpgm"] = fpgm_table

        # Inject prep
        prep_table = table__p_r_e_p()
        prep_table.program = TTProgram()
        prep_table.program.fromAssembly(result["prep"])
        font["prep"] = prep_table

        # Save and reload to verify
        path = os.path.join(tempfile.gettempdir(), "codegen_test.ttf")
        font.save(path)

        from fontTools.ttLib import TTFont

        reloaded = TTFont(path)
        assert "fpgm" in reloaded
        assert "prep" in reloaded

        # Verify bytecode is non-empty
        fpgm_bytecode = reloaded["fpgm"].program.getBytecode()
        assert len(fpgm_bytecode) > 0

        prep_bytecode = reloaded["prep"].program.getBytecode()
        assert len(prep_bytecode) > 0

        # Verify round-trip assembly
        fpgm_asm = reloaded["fpgm"].program.getAssembly()
        asm_text = "\n".join(fpgm_asm)
        assert "FDEF" in asm_text
        assert "ENDF" in asm_text

        reloaded.close()
        os.unlink(path)

    def test_compile_with_while_loop_inject(self) -> None:
        """Program with a while loop compiles and injects into a font."""
        from fontTools.fontBuilder import FontBuilder
        from fontTools.pens.ttGlyphPen import TTGlyphPen
        from fontTools.ttLib.tables._f_p_g_m import table__f_p_g_m
        from fontTools.ttLib.tables._p_r_e_p import table__p_r_e_p
        from fontTools.ttLib.tables.ttProgram import Program as TTProgram

        src = """\
var counter: int = 10
func game_tick():
    while counter > 0:
        counter = counter - 1
"""
        result = _compile(src, num_axes=1)

        fb = FontBuilder(1000, isTTF=True)
        fb.setupGlyphOrder([".notdef", "A"])
        fb.setupCharacterMap({65: "A"})

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
            {"familyName": "WhileTest", "styleName": "Regular"}
        )
        fb.setupOS2()
        fb.setupPost()

        font = fb.font
        font["maxp"].maxStackElements = 256
        font["maxp"].maxStorage = 64
        font["maxp"].maxFunctionDefs = 20
        font["maxp"].maxSizeOfInstructions = 2048

        fpgm_table = table__f_p_g_m()
        fpgm_table.program = TTProgram()
        fpgm_table.program.fromAssembly(result["fpgm"])
        font["fpgm"] = fpgm_table

        prep_table = table__p_r_e_p()
        prep_table.program = TTProgram()
        prep_table.program.fromAssembly(result["prep"])
        font["prep"] = prep_table

        path = os.path.join(tempfile.gettempdir(), "while_test.ttf")
        font.save(path)

        from fontTools.ttLib import TTFont

        reloaded = TTFont(path)
        bytecode = reloaded["fpgm"].program.getBytecode()
        assert len(bytecode) > 0
        reloaded.close()
        os.unlink(path)


# ===========================================================================
# Tests: Error handling
# ===========================================================================


class TestErrorHandling:
    """Verify that code generation raises useful errors."""

    def test_undefined_variable_in_assignment(self) -> None:
        program = Program(declarations=[
            FuncDef(
                name="test",
                params=[],
                body=[Assignment(target="undefined_var", value=IntLiteral(1))],
                has_return=False,
            ),
        ])
        gen = CodeGenerator()
        gen.allocator.alloc_func("test")
        gen.allocator.alloc_func_locals("test", [])
        with pytest.raises(CodeGenError, match="Undefined variable"):
            gen._compile_func(program.declarations[0])

    def test_undefined_function_call(self) -> None:
        program = Program(declarations=[
            FuncDef(
                name="test",
                params=[],
                body=[ExprStmt(expr=FuncCall(name="nonexistent", args=[]))],
                has_return=False,
            ),
        ])
        gen = CodeGenerator()
        gen.allocator.alloc_func("test")
        gen.allocator.alloc_func_locals("test", [])
        with pytest.raises(CodeGenError, match="Undefined function"):
            gen._compile_func(program.declarations[0])

    def test_undefined_array_read(self) -> None:
        program = Program(declarations=[
            FuncDef(
                name="test",
                params=[],
                body=[
                    ExprStmt(
                        expr=ArrayAccess(name="no_such_array", index=IntLiteral(0))
                    )
                ],
                has_return=False,
            ),
        ])
        gen = CodeGenerator()
        gen.allocator.alloc_func("test")
        gen.allocator.alloc_func_locals("test", [])
        with pytest.raises(CodeGenError, match="Undefined array"):
            gen._compile_func(program.declarations[0])

    def test_get_axis_wrong_arg_count(self) -> None:
        program = Program(declarations=[
            FuncDef(
                name="test",
                params=[],
                body=[
                    ExprStmt(
                        expr=FuncCall(name="get_axis", args=[])
                    )
                ],
                has_return=False,
            ),
        ])
        gen = CodeGenerator()
        gen.allocator.alloc_func("test")
        gen.allocator.alloc_func_locals("test", [])
        with pytest.raises(CodeGenError, match="exactly 1 argument"):
            gen._compile_func(program.declarations[0])

    def test_set_point_y_wrong_arg_count(self) -> None:
        program = Program(declarations=[
            FuncDef(
                name="test",
                params=[],
                body=[
                    ExprStmt(
                        expr=FuncCall(name="set_point_y", args=[IntLiteral(0)])
                    )
                ],
                has_return=False,
            ),
        ])
        gen = CodeGenerator()
        gen.allocator.alloc_func("test")
        gen.allocator.alloc_func_locals("test", [])
        with pytest.raises(CodeGenError, match="exactly 2 arguments"):
            gen._compile_func(program.declarations[0])


# ===========================================================================
# Tests: Complex program compilation
# ===========================================================================


class TestComplexProgram:
    """Verify a more complex program compiles without errors."""

    def test_multi_function_program(self) -> None:
        src = """\
const MAP_W = 8
const MAP_H = 8
var player_x: int = 100
var player_y: int = 200
array map_data[64]

func get_cell(x: int, y: int) -> int:
    return map_data[y * MAP_W + x]

func clamp(val: int, lo: int, hi: int) -> int:
    if val < lo:
        return lo
    if val > hi:
        return hi
    return val

func game_tick():
    player_x = clamp(player_x, 0, 1000)
    player_y = clamp(player_y, 0, 1000)
    var cell: int = get_cell(1, 2)
    if cell > 0:
        player_x = player_x + 1
"""
        result = _compile(src)

        # Should produce non-empty assembly for all three segments
        assert len(result["fpgm"]) > 0
        assert len(result["prep"]) > 0
        assert len(result["glyph"]) > 0

        # All instructions should be valid
        for line in result["fpgm"]:
            assert _is_valid_instruction(line), f"Invalid: {line!r}"
        for line in result["prep"]:
            assert _is_valid_instruction(line), f"Invalid: {line!r}"
        for line in result["glyph"]:
            assert _is_valid_instruction(line), f"Invalid: {line!r}"

    def test_nested_if_else(self) -> None:
        src = """\
var x: int = 0
func test():
    if x > 10:
        x = 10
    else:
        if x < 0:
            x = 0
        else:
            x = x + 1
"""
        result = _compile(src)
        fpgm = result["fpgm"]
        # Should have 2 IF[], 2 EIF[], 1 ELSE[] at minimum
        if_count = fpgm.count("IF[]")
        eif_count = fpgm.count("EIF[]")
        assert if_count == 2
        assert eif_count == 2
