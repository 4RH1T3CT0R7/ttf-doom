"""Code generator: AST to TrueType hinting assembly.

Translates the AST produced by :mod:`compiler.parser` into TrueType
hinting assembly instructions compatible with fonttools'
``Program.fromAssembly()``.

The output is split into three program segments:

* **fpgm** -- All ``FDEF`` / ``ENDF`` blocks (user functions + stdlib).
* **prep** -- Variable/array initialisation and constant loading.
* **glyph** -- A thin wrapper that calls the main ``game_tick`` function.

Key TrueType assembly facts
----------------------------
* ``SVTCA[0]`` = Y-axis, ``SVTCA[1]`` = X-axis.
* ``MUL[]`` computes ``(n1 * n2) / 64``  (F26Dot6 semantics).
* ``DIV[]`` pops n1 (top), n2 (below), pushes ``(n2 * 64) / n1``.
* ``ADD[]`` / ``SUB[]`` are plain integer operations.
* ``PUSHB[]`` max value: 255; ``PUSHW[]``: signed 16-bit (-32768..32767).
* ``RS[]`` reads from storage; ``WS[]`` writes to storage.
* ``WS[]`` pops index (top), then value (below).
* ``FDEF[]`` ... ``ENDF[]`` defines a function; ``CALL[]`` invokes it.

Arithmetic decisions
--------------------
In this DSL ``*`` and ``/`` have **plain integer** semantics:

* ``a * b`` = ``MUL(MUL(a, b), 4096)`` -- compensates for the /64 factor.
* ``a / b`` = ``DIV(DIV(a, b), 4096)`` -- compensates for the *64 factor.
* ``a % b`` = ``a - (a / b) * b``.

While loops
-----------
Converted to a recursive ``CALL`` pattern: each while loop becomes a
private ``FDEF`` that tests its condition, executes the body if true,
and calls itself again.
"""

from __future__ import annotations

from typing import Optional, Union

from compiler.allocator import StorageAllocator
from compiler.ast_nodes import (
    ArrayAccess,
    ArrayAssignment,
    ArrayDecl,
    Assignment,
    BinOp,
    ConstDecl,
    Expr,
    ExprStmt,
    FuncCall,
    FuncDef,
    IfStmt,
    IntLiteral,
    Program,
    ReturnStmt,
    Statement,
    UnaryOp,
    VarDecl,
    VarRef,
    WhileStmt,
)
from compiler.stdlib import get_stdlib_functions


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class CodeGenError(Exception):
    """Raised when code generation encounters an unrecoverable error."""


# ---------------------------------------------------------------------------
# Intrinsic names
# ---------------------------------------------------------------------------

_INTRINSICS = {"get_axis", "set_point_y"}


# ---------------------------------------------------------------------------
# Code generator
# ---------------------------------------------------------------------------

class CodeGenerator:
    """Translates a ``Program`` AST into TrueType hinting assembly.

    Usage::

        gen = CodeGenerator()
        result = gen.compile(program_ast)
        fpgm_lines = result['fpgm']   # list[str]
        prep_lines  = result['prep']   # list[str]
        glyph_lines = result['glyph'] # list[str]
    """

    def __init__(self, num_axes: int = 5) -> None:
        self.allocator = StorageAllocator()
        self.fpgm_asm: list[str] = []
        self.prep_asm: list[str] = []
        self._while_func_counter: int = 0
        self._num_axes: int = num_axes
        # Active local scope: set when compiling a function body.
        self._current_func_locals: dict[str, int] | None = None

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def compile(self, program: Program) -> dict[str, list[str]]:
        """Compile a ``Program`` AST to assembly.

        Args:
            program: The root AST node.

        Returns:
            Dict with keys ``'fpgm'``, ``'prep'``, ``'glyph'``, each
            mapping to a list of assembly instruction strings.
        """
        # Pass 1: register all top-level declarations (allocate storage / IDs)
        self._register_declarations(program)

        # Pass 2: register stdlib functions
        self._register_stdlib()

        # Pass 3: compile user function bodies -> FDEF blocks
        for decl in program.declarations:
            if isinstance(decl, FuncDef):
                self._compile_func(decl)

        # Pass 4: generate prep (global variable initialisation)
        self._generate_prep(program)

        # Pass 5: generate glyph program (calls game_tick if defined)
        glyph_asm = self._generate_glyph()

        return {
            "fpgm": list(self.fpgm_asm),
            "prep": list(self.prep_asm),
            "glyph": list(glyph_asm),
        }

    # --------------------------------------------------------------------- #
    # Pass 1 -- register declarations
    # --------------------------------------------------------------------- #

    def _register_declarations(self, program: Program) -> None:
        """Walk top-level declarations and allocate storage / IDs."""
        for decl in program.declarations:
            if isinstance(decl, VarDecl):
                self.allocator.alloc_var(decl.name)
            elif isinstance(decl, ConstDecl):
                self.allocator.define_const(decl.name, decl.value)
            elif isinstance(decl, ArrayDecl):
                self.allocator.alloc_array(decl.name, decl.size)
            elif isinstance(decl, FuncDef):
                self.allocator.alloc_func(decl.name)
                self.allocator.alloc_func_locals(decl.name, decl.params)

    # --------------------------------------------------------------------- #
    # Pass 2 -- register stdlib
    # --------------------------------------------------------------------- #

    def _register_stdlib(self) -> None:
        """Register stdlib functions and emit their FDEFs."""
        stdlib = get_stdlib_functions()
        for name, body in stdlib.items():
            fid = self.allocator.alloc_func(name)
            self.fpgm_asm.extend(self._push_value(fid))
            self.fpgm_asm.append("FDEF[]")
            self.fpgm_asm.extend(body)
            self.fpgm_asm.append("ENDF[]")

    # --------------------------------------------------------------------- #
    # Pass 3 -- compile user functions
    # --------------------------------------------------------------------- #

    def _compile_func(self, func: FuncDef) -> None:
        """Emit an FDEF block for a user-defined function."""
        fid = self.allocator.funcs[func.name]
        local_storage = self.allocator.func_local_storage.get(func.name, {})

        lines: list[str] = []
        lines.extend(self._push_value(fid))
        lines.append("FDEF[]")

        # Pop parameters from stack into storage.
        # Parameters are pushed left-to-right by the caller, so the last
        # parameter is on top of the stack and must be popped first.
        for param_name in reversed(func.params):
            storage_idx = local_storage[param_name]
            lines.extend(self._push_value(storage_idx))
            lines.append("SWAP[]")
            lines.append("WS[]")

        # Compile body
        self._current_func_locals = local_storage
        for stmt in func.body:
            lines.extend(self._compile_stmt(stmt))
        self._current_func_locals = None

        lines.append("ENDF[]")
        self.fpgm_asm.extend(lines)

    # --------------------------------------------------------------------- #
    # Pass 4 -- generate prep
    # --------------------------------------------------------------------- #

    def _generate_prep(self, program: Program) -> None:
        """Emit prep assembly for global variable initialisation."""
        self.prep_asm.append("SVTCA[0]")  # Y-axis for coordinate ops

        for decl in program.declarations:
            if isinstance(decl, VarDecl) and decl.init_value is not None:
                storage_idx = self.allocator.vars[decl.name]
                # Compile the init expression
                self.prep_asm.extend(self._compile_expr(decl.init_value))
                # Store: value on stack, push index, swap, WS
                self.prep_asm.extend(self._push_value(storage_idx))
                self.prep_asm.append("SWAP[]")
                self.prep_asm.append("WS[]")

    # --------------------------------------------------------------------- #
    # Pass 5 -- generate glyph program
    # --------------------------------------------------------------------- #

    def _generate_glyph(self) -> list[str]:
        """Emit glyph assembly that calls game_tick (if defined)."""
        lines: list[str] = []
        if "game_tick" in self.allocator.funcs:
            fid = self.allocator.funcs["game_tick"]
            lines.extend(self._push_value(fid))
            lines.append("CALL[]")
        return lines

    # --------------------------------------------------------------------- #
    # Expression compilation
    # --------------------------------------------------------------------- #

    def _compile_expr(self, expr: Expr) -> list[str]:
        """Compile an expression, leaving its result on the stack.

        Args:
            expr: An AST expression node.

        Returns:
            List of assembly instructions.
        """
        if isinstance(expr, IntLiteral):
            return self._push_value(expr.value)

        if isinstance(expr, VarRef):
            return self._compile_var_ref(expr)

        if isinstance(expr, BinOp):
            return self._compile_binop(expr)

        if isinstance(expr, UnaryOp):
            return self._compile_unaryop(expr)

        if isinstance(expr, FuncCall):
            return self._compile_func_call(expr)

        if isinstance(expr, ArrayAccess):
            return self._compile_array_access(expr)

        raise CodeGenError(f"Unknown expression type: {type(expr).__name__}")

    def _compile_var_ref(self, ref: VarRef) -> list[str]:
        """Compile a variable or constant reference."""
        # Check function locals first
        if self._current_func_locals and ref.name in self._current_func_locals:
            storage_idx = self._current_func_locals[ref.name]
            lines = self._push_value(storage_idx)
            lines.append("RS[]")
            return lines

        kind, value = self.allocator.lookup(ref.name)
        if kind == "const":
            return self._push_value(value)
        if kind == "var":
            lines = self._push_value(value)
            lines.append("RS[]")
            return lines
        # Array name used as bare reference -> push base index
        if kind == "array":
            return self._push_value(value)

        raise CodeGenError(f"Cannot reference '{ref.name}' as an expression")

    def _compile_binop(self, op: BinOp) -> list[str]:
        """Compile a binary operation."""
        lines: list[str] = []
        lines.extend(self._compile_expr(op.left))
        lines.extend(self._compile_expr(op.right))

        if op.op == "+":
            lines.append("ADD[]")
        elif op.op == "-":
            lines.append("SUB[]")
        elif op.op == "*":
            # Plain integer multiply:
            # MUL(a, b) = (a*b)/64.  MUL(result, 4096) = (result*4096)/64
            # = result * 64 = a*b.
            lines.append("MUL[]")
            lines.extend(self._push_value(4096))
            lines.append("MUL[]")
        elif op.op == "/":
            # Plain integer divide:
            # DIV(a, b) = (a*64)/b.  DIV(result, 4096) = (result*64)/4096
            # = result/64 = a/b.
            lines.append("DIV[]")
            lines.extend(self._push_value(4096))
            lines.append("DIV[]")
        elif op.op == "%":
            # Modulo: a % b = a - (a / b) * b
            # We need a and b again, but they're already consumed.
            # Recompile: this is a code-size trade-off for simplicity.
            lines = []
            lines.extend(self._compile_expr(op.left))   # a
            lines.extend(self._compile_expr(op.left))   # a, a
            lines.extend(self._compile_expr(op.right))   # a, a, b
            lines.append("DIV[]")                         # a, (a*64)/b
            lines.extend(self._push_value(4096))
            lines.append("DIV[]")                         # a, a/b (integer)
            lines.extend(self._compile_expr(op.right))   # a, a/b, b
            lines.append("MUL[]")                         # a, ((a/b)*b)/64
            lines.extend(self._push_value(4096))
            lines.append("MUL[]")                         # a, (a/b)*b
            lines.append("SUB[]")                         # a - (a/b)*b
        elif op.op == "==":
            lines.append("EQ[]")
        elif op.op == "!=":
            lines.append("NEQ[]")
        elif op.op == "<":
            lines.append("LT[]")
        elif op.op == ">":
            lines.append("GT[]")
        elif op.op == "<=":
            lines.append("LTEQ[]")
        elif op.op == ">=":
            lines.append("GTEQ[]")
        elif op.op == "and":
            lines.append("AND[]")
        elif op.op == "or":
            lines.append("OR[]")
        else:
            raise CodeGenError(f"Unknown binary operator: {op.op!r}")

        return lines

    def _compile_unaryop(self, op: UnaryOp) -> list[str]:
        """Compile a unary operation."""
        lines = self._compile_expr(op.operand)
        if op.op == "-":
            lines.append("NEG[]")
        elif op.op == "not":
            lines.append("NOT[]")
        else:
            raise CodeGenError(f"Unknown unary operator: {op.op!r}")
        return lines

    def _compile_func_call(self, call: FuncCall) -> list[str]:
        """Compile a function or intrinsic call."""
        if call.name in _INTRINSICS:
            return self._compile_intrinsic(call)

        # Regular function call: push args left-to-right, then CALL
        lines: list[str] = []
        for arg in call.args:
            lines.extend(self._compile_expr(arg))

        if call.name not in self.allocator.funcs:
            raise CodeGenError(f"Undefined function: '{call.name}'")

        fid = self.allocator.funcs[call.name]
        lines.extend(self._push_value(fid))
        lines.append("CALL[]")
        return lines

    def _compile_intrinsic(self, call: FuncCall) -> list[str]:
        """Compile an intrinsic function call."""
        if call.name == "get_axis":
            return self._compile_get_axis(call)
        if call.name == "set_point_y":
            return self._compile_set_point_y(call)
        raise CodeGenError(f"Unknown intrinsic: '{call.name}'")

    def _compile_get_axis(self, call: FuncCall) -> list[str]:
        """Compile get_axis(N) intrinsic.

        GETVARIATION[] pushes N values onto the stack (one per axis).
        We need to extract the Nth value.

        For axis index 0 (first axis), it is deepest on the stack.
        For axis index N-1 (last axis), it is on top.

        To get axis ``i``, we push all axis values, then use MINDEX
        to move the desired one to the top, and POP the rest.
        """
        if len(call.args) != 1:
            raise CodeGenError("get_axis() requires exactly 1 argument")

        lines: list[str] = ["GETVARIATION[]"]

        # The axis index argument must be a compile-time constant (IntLiteral
        # or const reference).
        axis_idx = self._resolve_const_expr(call.args[0])
        if axis_idx is None:
            raise CodeGenError("get_axis() argument must be a compile-time constant")

        # After GETVARIATION[], stack has [axis0, axis1, ..., axisN-1]
        # with axisN-1 on top.  We want axis[axis_idx].
        # The value at axis_idx is at depth (num_axes - 1 - axis_idx) from top.
        # depth=0 means top of stack.
        depth = self._num_axes - 1 - axis_idx

        if depth == 0:
            # Already on top; pop the rest below (none above)
            # Actually we need to pop the (num_axes - 1) values below.
            # But they are below us. Use: save top, pop others.
            if self._num_axes > 1:
                for _ in range(self._num_axes - 1):
                    lines.append("SWAP[]")
                    lines.append("POP[]")
        elif depth > 0:
            # Use MINDEX to move element at (depth+1) position to top
            # MINDEX pops an index k from the stack and moves the kth
            # element (1-indexed from top, BEFORE popping k) to the top.
            # But wait -- after GETVARIATION pushes N values, the stack is:
            #   [axis0, axis1, ..., axisN-1]  (axisN-1 on top)
            # We want axis[axis_idx] which is at position
            #   (num_axes - axis_idx) from the top (1-indexed).
            # But first we push the MINDEX argument which shifts things.
            mindex_arg = self._num_axes - axis_idx
            lines.extend(self._push_value(mindex_arg))
            lines.append("MINDEX[]")
            # Now our desired value is on top, pop the remaining N-1 values
            for _ in range(self._num_axes - 1):
                lines.append("SWAP[]")
                lines.append("POP[]")

        return lines

    def _compile_set_point_y(self, call: FuncCall) -> list[str]:
        """Compile set_point_y(point_idx, coordinate) intrinsic.

        Emits: SVTCA[0] (Y-axis), then push point index, push coordinate,
        then SCFS[].

        SCFS pops coordinate (top), then point index (below).
        So stack before SCFS must be: [point_idx, coord].
        """
        if len(call.args) != 2:
            raise CodeGenError("set_point_y() requires exactly 2 arguments")

        lines: list[str] = []
        lines.append("SVTCA[0]")
        # Push point index first, then coordinate
        lines.extend(self._compile_expr(call.args[0]))  # point_idx
        lines.extend(self._compile_expr(call.args[1]))  # coordinate
        lines.append("SCFS[]")
        return lines

    def _compile_array_access(self, access: ArrayAccess) -> list[str]:
        """Compile an array element read: ``arr[i]``.

        Assembly: compile index, push base, ADD, RS.
        """
        if access.name not in self.allocator.arrays:
            raise CodeGenError(f"Undefined array: '{access.name}'")

        base_idx = self.allocator.arrays[access.name][0]
        lines = self._compile_expr(access.index)
        lines.extend(self._push_value(base_idx))
        lines.append("ADD[]")
        lines.append("RS[]")
        return lines

    # --------------------------------------------------------------------- #
    # Statement compilation
    # --------------------------------------------------------------------- #

    def _compile_stmt(self, stmt: Statement) -> list[str]:
        """Compile a single statement.

        Args:
            stmt: An AST statement node.

        Returns:
            List of assembly instructions.
        """
        if isinstance(stmt, Assignment):
            return self._compile_assignment(stmt)

        if isinstance(stmt, ArrayAssignment):
            return self._compile_array_assignment(stmt)

        if isinstance(stmt, IfStmt):
            return self._compile_if(stmt)

        if isinstance(stmt, WhileStmt):
            return self._compile_while(stmt)

        if isinstance(stmt, ReturnStmt):
            return self._compile_return(stmt)

        if isinstance(stmt, ExprStmt):
            return self._compile_expr(stmt.expr)

        if isinstance(stmt, VarDecl):
            return self._compile_local_var_decl(stmt)

        raise CodeGenError(f"Unknown statement type: {type(stmt).__name__}")

    def _compile_assignment(self, stmt: Assignment) -> list[str]:
        """Compile ``target = expr``.

        Assembly: compile expr, push storage index, SWAP, WS.
        """
        lines: list[str] = []
        lines.extend(self._compile_expr(stmt.value))

        # Resolve storage index -- check local scope first
        storage_idx: int | None = None
        if self._current_func_locals and stmt.target in self._current_func_locals:
            storage_idx = self._current_func_locals[stmt.target]
        elif stmt.target in self.allocator.vars:
            storage_idx = self.allocator.vars[stmt.target]
        else:
            raise CodeGenError(f"Undefined variable: '{stmt.target}'")

        lines.extend(self._push_value(storage_idx))
        lines.append("SWAP[]")
        lines.append("WS[]")
        return lines

    def _compile_array_assignment(self, stmt: ArrayAssignment) -> list[str]:
        """Compile ``arr[i] = expr``.

        Assembly: compile value, compile index, push base, ADD, SWAP, WS.
        WS pops index (top) then value (below), so we need:
        stack = [value, computed_storage_index]
        -> SWAP to get [computed_storage_index, value]
        -> WS
        """
        if stmt.name not in self.allocator.arrays:
            raise CodeGenError(f"Undefined array: '{stmt.name}'")

        base_idx = self.allocator.arrays[stmt.name][0]
        lines: list[str] = []
        # Push value first
        lines.extend(self._compile_expr(stmt.value))
        # Compute storage index: index + base
        lines.extend(self._compile_expr(stmt.index))
        lines.extend(self._push_value(base_idx))
        lines.append("ADD[]")
        # Stack now: [value, storage_index]
        # WS needs: index on top, value below -> SWAP
        lines.append("SWAP[]")
        lines.append("WS[]")
        return lines

    def _compile_if(self, stmt: IfStmt) -> list[str]:
        """Compile if/else statement.

        Assembly: compile condition, IF, body, (ELSE, body)?, EIF.
        """
        lines: list[str] = []
        lines.extend(self._compile_expr(stmt.condition))
        lines.append("IF[]")

        for s in stmt.then_body:
            lines.extend(self._compile_stmt(s))

        if stmt.else_body:
            lines.append("ELSE[]")
            for s in stmt.else_body:
                lines.extend(self._compile_stmt(s))

        lines.append("EIF[]")
        return lines

    def _compile_while(self, stmt: WhileStmt) -> list[str]:
        """Compile a while loop via recursive FDEF pattern.

        Each while loop becomes a private FDEF that tests its condition,
        executes the body if true, and recursively calls itself.
        """
        # Allocate a unique function ID for the while-loop helper
        loop_name = f"__while_{self._while_func_counter}"
        self._while_func_counter += 1
        fid = self.allocator.alloc_func(loop_name)

        # Build the FDEF
        fdef_lines: list[str] = []
        fdef_lines.extend(self._push_value(fid))
        fdef_lines.append("FDEF[]")
        fdef_lines.extend(self._compile_expr(stmt.condition))
        fdef_lines.append("IF[]")
        for s in stmt.body:
            fdef_lines.extend(self._compile_stmt(s))
        # Recursive call
        fdef_lines.extend(self._push_value(fid))
        fdef_lines.append("CALL[]")
        fdef_lines.append("EIF[]")
        fdef_lines.append("ENDF[]")

        # Append the FDEF to fpgm
        self.fpgm_asm.extend(fdef_lines)

        # At the call site, invoke the loop function
        call_lines: list[str] = []
        call_lines.extend(self._push_value(fid))
        call_lines.append("CALL[]")
        return call_lines

    def _compile_return(self, stmt: ReturnStmt) -> list[str]:
        """Compile a return statement.

        If there is a return value, compile the expression so it is left
        on the stack for the caller.  If there is no value, emit nothing
        (the function simply falls through to ENDF).
        """
        if stmt.value is not None:
            return self._compile_expr(stmt.value)
        return []

    def _compile_local_var_decl(self, decl: VarDecl) -> list[str]:
        """Compile a local variable declaration inside a function body.

        Allocates a new storage slot and optionally initialises it.
        Local variables inside functions get their own storage slots
        without registering in the global ``vars`` dict, so that
        different functions can use the same local variable names.
        """
        # If we are inside a function and this var is already in func locals,
        # it was a parameter -- skip allocation.
        if self._current_func_locals and decl.name in self._current_func_locals:
            storage_idx = self._current_func_locals[decl.name]
        elif self._current_func_locals is not None:
            # Inside a function: allocate a private storage slot without
            # polluting the global vars namespace.
            storage_idx = self.allocator._next_storage
            self.allocator._next_storage += 1
            self._current_func_locals[decl.name] = storage_idx
        else:
            storage_idx = self.allocator.alloc_var(decl.name)
            # Also add to current function locals so it can be referenced
            if self._current_func_locals is not None:
                self._current_func_locals[decl.name] = storage_idx

        if decl.init_value is not None:
            lines = self._compile_expr(decl.init_value)
            lines.extend(self._push_value(storage_idx))
            lines.append("SWAP[]")
            lines.append("WS[]")
            return lines
        return []

    # --------------------------------------------------------------------- #
    # Push helper
    # --------------------------------------------------------------------- #

    def _push_value(self, value: int) -> list[str]:
        """Generate a PUSH instruction for an integer value.

        Args:
            value: The integer to push onto the TT stack.

        Returns:
            List containing one or two assembly instructions.
        """
        if 0 <= value <= 255:
            return [f"PUSHB[] {value}"]
        if -32768 <= value <= 32767:
            return [f"PUSHW[] {value}"]
        # Large values: decompose into high and low 16-bit parts.
        # Push high part, multiply by 65536 (using MUL tricks), add low.
        # For simplicity and the range of values we expect in DOOM (~64K storage max),
        # raise an error for now.
        raise CodeGenError(
            f"Value {value} is outside the supported range "
            f"(-32768..32767) for a single PUSH instruction"
        )

    # --------------------------------------------------------------------- #
    # Constant expression resolution
    # --------------------------------------------------------------------- #

    def _resolve_const_expr(self, expr: Expr) -> int | None:
        """Try to resolve an expression to a compile-time constant.

        Returns the integer value if the expression is a constant, or
        ``None`` if it cannot be resolved at compile time.
        """
        if isinstance(expr, IntLiteral):
            return expr.value
        if isinstance(expr, VarRef):
            if expr.name in self.allocator.consts:
                return self.allocator.consts[expr.name]
        return None
