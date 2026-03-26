"""Tests for the TTDoom DSL parser."""

from __future__ import annotations

import pytest

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
from compiler.parser import ParseError, Parser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse(src: str) -> Program:
    return Parser(src).parse()


def _first_decl(src: str):
    """Return the first top-level declaration."""
    return _parse(src).declarations[0]


# ---------------------------------------------------------------------------
# 1. Variable declarations
# ---------------------------------------------------------------------------

class TestVarDecl:
    def test_var_with_init(self) -> None:
        decl = _first_decl("var player_x: int = 512")
        assert isinstance(decl, VarDecl)
        assert decl.name == "player_x"
        assert isinstance(decl.init_value, IntLiteral)
        assert decl.init_value.value == 512

    def test_var_without_init(self) -> None:
        decl = _first_decl("var temp: int")
        assert isinstance(decl, VarDecl)
        assert decl.name == "temp"
        assert decl.init_value is None

    def test_var_with_expression_init(self) -> None:
        decl = _first_decl("var x: int = 2 + 3")
        assert isinstance(decl, VarDecl)
        assert isinstance(decl.init_value, BinOp)
        assert decl.init_value.op == "+"

    def test_var_line_number(self) -> None:
        prog = _parse("var x: int\nvar y: int")
        assert prog.declarations[0].line == 1
        assert prog.declarations[1].line == 2


# ---------------------------------------------------------------------------
# 2. Constant declarations
# ---------------------------------------------------------------------------

class TestConstDecl:
    def test_const(self) -> None:
        decl = _first_decl("const SCALE = 16384")
        assert isinstance(decl, ConstDecl)
        assert decl.name == "SCALE"
        assert decl.value == 16384

    def test_const_hex(self) -> None:
        decl = _first_decl("const MASK = 0xFF")
        assert isinstance(decl, ConstDecl)
        assert decl.value == 255

    def test_const_negative(self) -> None:
        decl = _first_decl("const NEG = -1")
        assert isinstance(decl, ConstDecl)
        assert decl.value == -1


# ---------------------------------------------------------------------------
# 3. Array declarations
# ---------------------------------------------------------------------------

class TestArrayDecl:
    def test_array(self) -> None:
        decl = _first_decl("array sin_table[256]")
        assert isinstance(decl, ArrayDecl)
        assert decl.name == "sin_table"
        assert decl.size == 256


# ---------------------------------------------------------------------------
# 4. Function definitions
# ---------------------------------------------------------------------------

class TestFuncDef:
    def test_func_with_return(self) -> None:
        src = (
            "func add(a: int, b: int) -> int:\n"
            "    return a + b\n"
        )
        decl = _first_decl(src)
        assert isinstance(decl, FuncDef)
        assert decl.name == "add"
        assert decl.params == ["a", "b"]
        assert decl.has_return is True
        assert len(decl.body) == 1
        assert isinstance(decl.body[0], ReturnStmt)

    def test_func_no_return_type(self) -> None:
        src = (
            "func noop():\n"
            "    return\n"
        )
        decl = _first_decl(src)
        assert isinstance(decl, FuncDef)
        assert decl.params == []
        assert decl.has_return is False

    def test_func_with_assignment_body(self) -> None:
        src = (
            "func move(dx: int):\n"
            "    player_x = player_x + dx\n"
        )
        decl = _first_decl(src)
        assert isinstance(decl, FuncDef)
        assert decl.params == ["dx"]
        body_stmt = decl.body[0]
        assert isinstance(body_stmt, Assignment)
        assert body_stmt.target == "player_x"


# ---------------------------------------------------------------------------
# 5. If / else statements
# ---------------------------------------------------------------------------

class TestIfStmt:
    def test_simple_if(self) -> None:
        src = (
            "func f(x: int):\n"
            "    if x > 0:\n"
            "        return x\n"
        )
        func = _first_decl(src)
        assert isinstance(func, FuncDef)
        if_stmt = func.body[0]
        assert isinstance(if_stmt, IfStmt)
        assert isinstance(if_stmt.condition, BinOp)
        assert if_stmt.condition.op == ">"
        assert if_stmt.else_body is None

    def test_if_else(self) -> None:
        src = (
            "func f(x: int) -> int:\n"
            "    if x > 0:\n"
            "        return 1\n"
            "    else:\n"
            "        return 0\n"
        )
        func = _first_decl(src)
        assert isinstance(func, FuncDef)
        if_stmt = func.body[0]
        assert isinstance(if_stmt, IfStmt)
        assert if_stmt.else_body is not None
        assert len(if_stmt.else_body) == 1

    def test_nested_if(self) -> None:
        src = (
            "func f(x: int) -> int:\n"
            "    if x > 100:\n"
            "        return 100\n"
            "    else:\n"
            "        if x < 0:\n"
            "            return 0\n"
        )
        func = _first_decl(src)
        if_stmt = func.body[0]
        assert isinstance(if_stmt, IfStmt)
        assert if_stmt.else_body is not None
        nested = if_stmt.else_body[0]
        assert isinstance(nested, IfStmt)
        assert isinstance(nested.condition, BinOp)
        assert nested.condition.op == "<"


# ---------------------------------------------------------------------------
# 6. While loops
# ---------------------------------------------------------------------------

class TestWhileStmt:
    def test_while(self) -> None:
        src = (
            "func f():\n"
            "    while x > 0:\n"
            "        x = x - 1\n"
        )
        func = _first_decl(src)
        while_stmt = func.body[0]
        assert isinstance(while_stmt, WhileStmt)
        assert isinstance(while_stmt.condition, BinOp)
        assert while_stmt.condition.op == ">"
        assert len(while_stmt.body) == 1
        assert isinstance(while_stmt.body[0], Assignment)


# ---------------------------------------------------------------------------
# 7. Return statements
# ---------------------------------------------------------------------------

class TestReturnStmt:
    def test_return_with_value(self) -> None:
        src = (
            "func f() -> int:\n"
            "    return 42\n"
        )
        func = _first_decl(src)
        ret = func.body[0]
        assert isinstance(ret, ReturnStmt)
        assert isinstance(ret.value, IntLiteral)
        assert ret.value.value == 42

    def test_return_void(self) -> None:
        src = (
            "func f():\n"
            "    return\n"
        )
        func = _first_decl(src)
        ret = func.body[0]
        assert isinstance(ret, ReturnStmt)
        assert ret.value is None

    def test_return_expression(self) -> None:
        src = (
            "func f(a: int, b: int) -> int:\n"
            "    return a + b * 2\n"
        )
        func = _first_decl(src)
        ret = func.body[0]
        assert isinstance(ret, ReturnStmt)
        assert isinstance(ret.value, BinOp)
        assert ret.value.op == "+"


# ---------------------------------------------------------------------------
# 8. Binary expression precedence
# ---------------------------------------------------------------------------

class TestExprPrecedence:
    def test_mul_before_add(self) -> None:
        """2 + 3 * 4 should parse as 2 + (3 * 4)."""
        src = (
            "func f() -> int:\n"
            "    return 2 + 3 * 4\n"
        )
        func = _first_decl(src)
        ret = func.body[0]
        assert isinstance(ret, ReturnStmt)
        expr = ret.value
        assert isinstance(expr, BinOp)
        assert expr.op == "+"
        assert isinstance(expr.left, IntLiteral)
        assert expr.left.value == 2
        assert isinstance(expr.right, BinOp)
        assert expr.right.op == "*"

    def test_parentheses_override(self) -> None:
        """(2 + 3) * 4 should group addition first."""
        src = (
            "func f() -> int:\n"
            "    return (2 + 3) * 4\n"
        )
        func = _first_decl(src)
        ret = func.body[0]
        assert isinstance(ret, ReturnStmt)
        expr = ret.value
        assert isinstance(expr, BinOp)
        assert expr.op == "*"
        assert isinstance(expr.left, BinOp)
        assert expr.left.op == "+"

    def test_comparison_lower_than_arithmetic(self) -> None:
        """a + 1 > b should parse as (a + 1) > b."""
        src = (
            "func f(a: int, b: int) -> int:\n"
            "    if a + 1 > b:\n"
            "        return 1\n"
        )
        func = _first_decl(src)
        if_stmt = func.body[0]
        assert isinstance(if_stmt, IfStmt)
        cond = if_stmt.condition
        assert isinstance(cond, BinOp)
        assert cond.op == ">"
        assert isinstance(cond.left, BinOp)
        assert cond.left.op == "+"

    def test_logical_operators(self) -> None:
        """a and b or c should parse as (a and b) or c."""
        src = (
            "func f() -> int:\n"
            "    if a and b or c:\n"
            "        return 1\n"
        )
        func = _first_decl(src)
        if_stmt = func.body[0]
        cond = if_stmt.condition
        assert isinstance(cond, BinOp)
        assert cond.op == "or"
        assert isinstance(cond.left, BinOp)
        assert cond.left.op == "and"

    def test_unary_negation(self) -> None:
        src = (
            "func f() -> int:\n"
            "    return -x\n"
        )
        func = _first_decl(src)
        ret = func.body[0]
        assert isinstance(ret, ReturnStmt)
        assert isinstance(ret.value, UnaryOp)
        assert ret.value.op == "-"
        assert isinstance(ret.value.operand, VarRef)

    def test_not_operator(self) -> None:
        src = (
            "func f() -> int:\n"
            "    if not x:\n"
            "        return 0\n"
        )
        func = _first_decl(src)
        if_stmt = func.body[0]
        assert isinstance(if_stmt, IfStmt)
        assert isinstance(if_stmt.condition, UnaryOp)
        assert if_stmt.condition.op == "not"

    def test_left_associativity(self) -> None:
        """1 - 2 - 3 should parse as (1 - 2) - 3."""
        src = (
            "func f() -> int:\n"
            "    return 1 - 2 - 3\n"
        )
        func = _first_decl(src)
        ret = func.body[0]
        assert isinstance(ret, ReturnStmt)
        expr = ret.value
        assert isinstance(expr, BinOp)
        assert expr.op == "-"
        # Left should be (1 - 2)
        assert isinstance(expr.left, BinOp)
        assert expr.left.op == "-"
        # Right should be 3
        assert isinstance(expr.right, IntLiteral)
        assert expr.right.value == 3


# ---------------------------------------------------------------------------
# 9. Function calls
# ---------------------------------------------------------------------------

class TestFuncCall:
    def test_simple_call(self) -> None:
        src = (
            "func f():\n"
            "    set_point_y(0, 100)\n"
        )
        func = _first_decl(src)
        stmt = func.body[0]
        assert isinstance(stmt, ExprStmt)
        call = stmt.expr
        assert isinstance(call, FuncCall)
        assert call.name == "set_point_y"
        assert len(call.args) == 2

    def test_nested_call(self) -> None:
        src = (
            "func f() -> int:\n"
            "    return fixmul(a, fixdiv(b, c))\n"
        )
        func = _first_decl(src)
        ret = func.body[0]
        assert isinstance(ret, ReturnStmt)
        call = ret.value
        assert isinstance(call, FuncCall)
        assert call.name == "fixmul"
        inner = call.args[1]
        assert isinstance(inner, FuncCall)
        assert inner.name == "fixdiv"

    def test_call_no_args(self) -> None:
        src = (
            "func f():\n"
            "    reset()\n"
        )
        func = _first_decl(src)
        stmt = func.body[0]
        assert isinstance(stmt, ExprStmt)
        call = stmt.expr
        assert isinstance(call, FuncCall)
        assert call.args == []


# ---------------------------------------------------------------------------
# 10. Array access
# ---------------------------------------------------------------------------

class TestArrayAccess:
    def test_array_read(self) -> None:
        src = (
            "func f() -> int:\n"
            "    return map_data[y * 16 + x]\n"
        )
        func = _first_decl(src)
        ret = func.body[0]
        assert isinstance(ret, ReturnStmt)
        acc = ret.value
        assert isinstance(acc, ArrayAccess)
        assert acc.name == "map_data"
        assert isinstance(acc.index, BinOp)

    def test_array_write(self) -> None:
        src = (
            "func f():\n"
            "    map_data[0] = 42\n"
        )
        func = _first_decl(src)
        stmt = func.body[0]
        assert isinstance(stmt, ArrayAssignment)
        assert stmt.name == "map_data"
        assert isinstance(stmt.index, IntLiteral)
        assert isinstance(stmt.value, IntLiteral)
        assert stmt.value.value == 42


# ---------------------------------------------------------------------------
# 11. Nested expressions
# ---------------------------------------------------------------------------

class TestNestedExpr:
    def test_complex_arithmetic(self) -> None:
        src = (
            "func f(a: int, b: int) -> int:\n"
            "    return (a + b) * (a - b) / 2\n"
        )
        func = _first_decl(src)
        ret = func.body[0]
        assert isinstance(ret, ReturnStmt)
        # Top-level should be / (left-assoc: ((a+b)*(a-b)) / 2)
        expr = ret.value
        assert isinstance(expr, BinOp)
        assert expr.op == "/"

    def test_array_access_in_expression(self) -> None:
        src = (
            "func f() -> int:\n"
            "    return data[i] + data[i + 1]\n"
        )
        func = _first_decl(src)
        ret = func.body[0]
        assert isinstance(ret, ReturnStmt)
        expr = ret.value
        assert isinstance(expr, BinOp)
        assert expr.op == "+"
        assert isinstance(expr.left, ArrayAccess)
        assert isinstance(expr.right, ArrayAccess)


# ---------------------------------------------------------------------------
# 12. Complete program
# ---------------------------------------------------------------------------

class TestCompleteProgram:
    def test_full_program(self) -> None:
        src = (
            "# TTDoom program\n"
            "var player_x: int = 512\n"
            "var player_y: int = 512\n"
            "const SCALE = 16384\n"
            "const MAP_SIZE = 16\n"
            "array map_data[256]\n"
            "\n"
            "func get_map(x: int, y: int) -> int:\n"
            "    return map_data[y * MAP_SIZE + x]\n"
            "\n"
            "func move(dx: int, dy: int):\n"
            "    player_x = player_x + dx\n"
            "    player_y = player_y + dy\n"
            "\n"
            "func clamp(v: int) -> int:\n"
            "    if v > 100:\n"
            "        return 100\n"
            "    else:\n"
            "        if v < 0:\n"
            "            return 0\n"
            "    return v\n"
        )
        prog = _parse(src)
        assert isinstance(prog, Program)
        # 2 vars + 2 consts + 1 array + 3 funcs = 8
        assert len(prog.declarations) == 8
        assert isinstance(prog.declarations[0], VarDecl)
        assert isinstance(prog.declarations[1], VarDecl)
        assert isinstance(prog.declarations[2], ConstDecl)
        assert isinstance(prog.declarations[3], ConstDecl)
        assert isinstance(prog.declarations[4], ArrayDecl)
        assert isinstance(prog.declarations[5], FuncDef)
        assert isinstance(prog.declarations[6], FuncDef)
        assert isinstance(prog.declarations[7], FuncDef)

        # Check the get_map function
        get_map = prog.declarations[5]
        assert isinstance(get_map, FuncDef)
        assert get_map.name == "get_map"
        assert get_map.params == ["x", "y"]
        assert get_map.has_return is True

        # Check the move function
        move = prog.declarations[6]
        assert isinstance(move, FuncDef)
        assert move.name == "move"
        assert len(move.body) == 2

        # Check the clamp function
        clamp = prog.declarations[7]
        assert isinstance(clamp, FuncDef)
        assert clamp.name == "clamp"
        assert clamp.has_return is True
        assert len(clamp.body) == 2  # if_stmt + return

    def test_program_with_while(self) -> None:
        src = (
            "func countdown(n: int) -> int:\n"
            "    var total: int = 0\n"
            "    while n > 0:\n"
            "        total = total + n\n"
            "        n = n - 1\n"
            "    return total\n"
        )
        prog = _parse(src)
        func = prog.declarations[0]
        assert isinstance(func, FuncDef)
        assert len(func.body) == 3  # var, while, return
        assert isinstance(func.body[0], VarDecl)
        assert isinstance(func.body[1], WhileStmt)
        assert isinstance(func.body[2], ReturnStmt)
        assert len(func.body[1].body) == 2


# ---------------------------------------------------------------------------
# 13. Syntax errors
# ---------------------------------------------------------------------------

class TestSyntaxErrors:
    def test_missing_colon_after_func(self) -> None:
        src = (
            "func f()\n"
            "    return 1\n"
        )
        with pytest.raises(ParseError, match="expected COLON"):
            _parse(src)

    def test_missing_type_annotation(self) -> None:
        src = "var x = 5\n"
        with pytest.raises(ParseError, match="expected COLON"):
            _parse(src)

    def test_unexpected_token(self) -> None:
        src = "123 badstuff\n"
        with pytest.raises(ParseError, match="expected declaration"):
            _parse(src)

    def test_error_has_line_number(self) -> None:
        src = "var x: int\n123 bad\n"
        try:
            _parse(src)
            assert False, "should have raised"
        except ParseError as exc:
            assert exc.line == 2
            assert "Line 2" in str(exc)

    def test_missing_rparen(self) -> None:
        src = (
            "func f(a: int:\n"
            "    return a\n"
        )
        with pytest.raises(ParseError):
            _parse(src)

    def test_empty_function_body(self) -> None:
        src = "func f():\n"
        with pytest.raises(ParseError):
            _parse(src)


# ---------------------------------------------------------------------------
# 14. Local variable declarations in function body
# ---------------------------------------------------------------------------

class TestLocalVarDecl:
    def test_local_var_in_func(self) -> None:
        src = (
            "func f(x: int) -> int:\n"
            "    var local: int = x * 2\n"
            "    return local\n"
        )
        func = _first_decl(src)
        assert isinstance(func, FuncDef)
        assert isinstance(func.body[0], VarDecl)
        assert func.body[0].name == "local"
        assert isinstance(func.body[0].init_value, BinOp)
        assert isinstance(func.body[1], ReturnStmt)


# ---------------------------------------------------------------------------
# 15. All comparison operators
# ---------------------------------------------------------------------------

class TestComparisonOps:
    @pytest.mark.parametrize(
        "op_str",
        ["==", "!=", "<", ">", "<=", ">="],
    )
    def test_comparison(self, op_str: str) -> None:
        src = (
            "func f(a: int, b: int) -> int:\n"
            f"    if a {op_str} b:\n"
            "        return 1\n"
        )
        func = _first_decl(src)
        if_stmt = func.body[0]
        assert isinstance(if_stmt, IfStmt)
        assert isinstance(if_stmt.condition, BinOp)
        assert if_stmt.condition.op == op_str


# ---------------------------------------------------------------------------
# 16. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_deeply_nested_if_else(self) -> None:
        src = (
            "func f(x: int) -> int:\n"
            "    if x > 100:\n"
            "        return 100\n"
            "    else:\n"
            "        if x > 50:\n"
            "            return 50\n"
            "        else:\n"
            "            if x > 0:\n"
            "                return x\n"
            "    return 0\n"
        )
        func = _first_decl(src)
        assert isinstance(func, FuncDef)
        # Should have if_stmt and return at top level
        assert isinstance(func.body[0], IfStmt)
        assert isinstance(func.body[1], ReturnStmt)

    def test_multiple_statements_in_block(self) -> None:
        src = (
            "func f():\n"
            "    var a: int = 1\n"
            "    var b: int = 2\n"
            "    var c: int = 3\n"
        )
        func = _first_decl(src)
        assert isinstance(func, FuncDef)
        assert len(func.body) == 3
        for stmt in func.body:
            assert isinstance(stmt, VarDecl)

    def test_expression_with_call_and_array(self) -> None:
        src = (
            "func f() -> int:\n"
            "    return fixmul(data[i], SCALE)\n"
        )
        func = _first_decl(src)
        ret = func.body[0]
        assert isinstance(ret, ReturnStmt)
        call = ret.value
        assert isinstance(call, FuncCall)
        assert isinstance(call.args[0], ArrayAccess)
        assert isinstance(call.args[1], VarRef)
