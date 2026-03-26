"""AST node definitions for the TTDoom DSL.

The TTDoom DSL compiles down to TrueType hinting instructions. This module
defines every node type the parser can produce. The AST is consumed by later
compiler stages that emit TrueType bytecode.

Node categories:
    - Top-level declarations: VarDecl, ConstDecl, ArrayDecl, FuncDef
    - Expressions: IntLiteral, VarRef, BinOp, UnaryOp, FuncCall, ArrayAccess
    - Statements: Assignment, ArrayAssignment, IfStmt, WhileStmt,
                  ReturnStmt, ExprStmt
    - Root: Program
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union


# ---------------------------------------------------------------------------
# Top-level declarations
# ---------------------------------------------------------------------------

@dataclass
class VarDecl:
    """Global or local variable declaration.

    ``var player_x: int = 512``
    """

    name: str
    init_value: Optional["Expr"] = None
    line: int = 0


@dataclass
class ConstDecl:
    """Compile-time constant (always inlined).

    ``const SCALE = 16384``
    """

    name: str
    value: int
    line: int = 0


@dataclass
class ArrayDecl:
    """Contiguous storage-slot array.

    ``array sin_table[256]``
    """

    name: str
    size: int
    line: int = 0


@dataclass
class FuncDef:
    """Function definition with typed parameters and optional return type.

    ``func add(a: int, b: int) -> int:``
    """

    name: str
    params: list[str]
    body: list["Statement"]
    has_return: bool = False
    line: int = 0


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------

@dataclass
class IntLiteral:
    """Integer constant (decimal or hex)."""

    value: int


@dataclass
class VarRef:
    """Reference to a named variable or constant."""

    name: str


@dataclass
class BinOp:
    """Binary operation.

    Supported operators: ``+ - * / % == != < > <= >= and or``
    """

    op: str
    left: "Expr"
    right: "Expr"


@dataclass
class UnaryOp:
    """Unary operation: negation ``-`` or logical ``not``."""

    op: str
    operand: "Expr"


@dataclass
class FuncCall:
    """Function or intrinsic call.

    Intrinsics: ``get_axis``, ``set_point_y``, ``fixmul``, ``fixdiv``.
    """

    name: str
    args: list["Expr"]


@dataclass
class ArrayAccess:
    """Indexed array read: ``map_data[y * MAP_SIZE + x]``."""

    name: str
    index: "Expr"


# Type alias covering every expression variant.
Expr = Union[IntLiteral, VarRef, BinOp, UnaryOp, FuncCall, ArrayAccess]


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------

@dataclass
class Assignment:
    """Simple variable assignment: ``player_x = player_x + dx``."""

    target: str
    value: Expr
    line: int = 0


@dataclass
class ArrayAssignment:
    """Indexed array write: ``map_data[idx] = value``."""

    name: str
    index: Expr
    value: Expr
    line: int = 0


@dataclass
class IfStmt:
    """Conditional with optional else branch.

    The else branch may itself contain a single ``IfStmt`` for chaining.
    """

    condition: Expr
    then_body: list["Statement"]
    else_body: Optional[list["Statement"]] = None
    line: int = 0


@dataclass
class WhileStmt:
    """While-loop."""

    condition: Expr
    body: list["Statement"]
    line: int = 0


@dataclass
class ReturnStmt:
    """Return statement with optional expression."""

    value: Optional[Expr] = None
    line: int = 0


@dataclass
class ExprStmt:
    """Standalone expression (typically a function call)."""

    expr: Expr
    line: int = 0


# Type alias covering every statement variant.
Statement = Union[
    Assignment, ArrayAssignment, IfStmt, WhileStmt, ReturnStmt, ExprStmt, VarDecl
]


# ---------------------------------------------------------------------------
# Program (root node)
# ---------------------------------------------------------------------------

@dataclass
class Program:
    """Root AST node — a sequence of top-level declarations."""

    declarations: list[Union[VarDecl, ConstDecl, ArrayDecl, FuncDef]]
