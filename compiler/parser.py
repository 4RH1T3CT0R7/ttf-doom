"""Recursive-descent parser for the TTDoom DSL.

Consumes a token stream produced by :class:`compiler.lexer.Lexer` and builds
an AST defined in :mod:`compiler.ast_nodes`.

Grammar (simplified)::

    program      := (declaration NEWLINE)*
    declaration  := var_decl | const_decl | array_decl | func_def
    var_decl     := 'var' IDENT ':' 'int' ('=' expr)?
    const_decl   := 'const' IDENT '=' INT_LITERAL
    array_decl   := 'array' IDENT '[' INT_LITERAL ']'
    func_def     := 'func' IDENT '(' params ')' ('->' 'int')? ':'
                    NEWLINE INDENT body DEDENT
    params       := (IDENT ':' 'int' (',' IDENT ':' 'int')*)?
    body         := statement+
    statement    := var_decl NEWLINE | assignment | if_stmt | while_stmt
                  | return_stmt | expr_stmt
    assignment   := (IDENT | IDENT '[' expr ']') '=' expr NEWLINE
    if_stmt      := 'if' expr ':' NEWLINE INDENT body DEDENT
                    ('else' ':' NEWLINE INDENT body DEDENT)?
    while_stmt   := 'while' expr ':' NEWLINE INDENT body DEDENT
    return_stmt  := 'return' expr? NEWLINE
    expr_stmt    := expr NEWLINE
    expr         := or_expr
    or_expr      := and_expr ('or' and_expr)*
    and_expr     := not_expr ('and' not_expr)*
    not_expr     := 'not' not_expr | comparison
    comparison   := add_expr (comp_op add_expr)?
    add_expr     := mul_expr (('+' | '-') mul_expr)*
    mul_expr     := unary_expr (('*' | '/' | '%') unary_expr)*
    unary_expr   := '-' unary_expr | atom
    atom         := INT_LITERAL
                  | IDENT '(' args ')'
                  | IDENT '[' expr ']'
                  | IDENT
                  | '(' expr ')'
    args         := (expr (',' expr)*)?
"""

from __future__ import annotations

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
from compiler.lexer import Lexer, Token, TokenType


# ---------------------------------------------------------------------------
# Parser error
# ---------------------------------------------------------------------------

class ParseError(Exception):
    """Raised when the parser encounters a syntax error."""

    def __init__(self, message: str, line: int) -> None:
        self.line = line
        super().__init__(f"Line {line}: {message}")


# ---------------------------------------------------------------------------
# Comparison operator tokens
# ---------------------------------------------------------------------------

_COMPARISON_OPS: set[TokenType] = {
    TokenType.EQ,
    TokenType.NEQ,
    TokenType.LT,
    TokenType.GT,
    TokenType.LTEQ,
    TokenType.GTEQ,
}

_OP_STRINGS: dict[TokenType, str] = {
    TokenType.PLUS: "+",
    TokenType.MINUS: "-",
    TokenType.STAR: "*",
    TokenType.SLASH: "/",
    TokenType.PERCENT: "%",
    TokenType.EQ: "==",
    TokenType.NEQ: "!=",
    TokenType.LT: "<",
    TokenType.GT: ">",
    TokenType.LTEQ: "<=",
    TokenType.GTEQ: ">=",
}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class Parser:
    """Recursive-descent parser for the TTDoom DSL.

    Usage::

        parser = Parser(source_code)
        program = parser.parse()   # returns ast_nodes.Program
    """

    def __init__(self, source: str) -> None:
        self._tokens: list[Token] = Lexer(source).tokenize()
        self._pos: int = 0

    # -- public API ---------------------------------------------------------

    def parse(self) -> Program:
        """Parse the complete source and return a :class:`Program` AST."""
        declarations: list[VarDecl | ConstDecl | ArrayDecl | FuncDef] = []

        # Skip leading newlines
        self._skip_newlines()

        while not self._check(TokenType.EOF):
            decl = self._declaration()
            declarations.append(decl)
            self._skip_newlines()

        return Program(declarations=declarations)

    # -- token helpers ------------------------------------------------------

    def _peek(self) -> Token:
        """Return the current token without consuming it."""
        return self._tokens[self._pos]

    def _advance(self) -> Token:
        """Consume and return the current token."""
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _check(self, tt: TokenType) -> bool:
        """Return True if the current token has the given type."""
        return self._peek().type == tt

    def _match(self, *types: TokenType) -> Token | None:
        """If the current token matches any of *types*, consume and return it."""
        if self._peek().type in types:
            return self._advance()
        return None

    def _expect(self, tt: TokenType, context: str = "") -> Token:
        """Consume a token of type *tt* or raise :class:`ParseError`."""
        tok = self._peek()
        if tok.type != tt:
            ctx = f" {context}" if context else ""
            raise ParseError(
                f"expected {tt.name}{ctx}, got {tok.type.name} ({tok.value!r})",
                tok.line,
            )
        return self._advance()

    def _skip_newlines(self) -> None:
        """Consume any NEWLINE tokens at the current position."""
        while self._check(TokenType.NEWLINE):
            self._advance()

    # -- top-level declarations ---------------------------------------------

    def _declaration(self) -> VarDecl | ConstDecl | ArrayDecl | FuncDef:
        """Parse one top-level declaration."""
        tok = self._peek()
        if tok.type == TokenType.VAR:
            decl = self._var_decl()
            self._expect(TokenType.NEWLINE, "after variable declaration")
            return decl
        if tok.type == TokenType.CONST:
            decl = self._const_decl()
            self._expect(TokenType.NEWLINE, "after constant declaration")
            return decl
        if tok.type == TokenType.ARRAY:
            decl = self._array_decl()
            self._expect(TokenType.NEWLINE, "after array declaration")
            return decl
        if tok.type == TokenType.FUNC:
            return self._func_def()
        raise ParseError(
            f"expected declaration (var, const, array, func), got {tok.type.name}",
            tok.line,
        )

    def _var_decl(self) -> VarDecl:
        """``var IDENT : int ( = expr )?``"""
        var_tok = self._expect(TokenType.VAR)
        name_tok = self._expect(TokenType.IDENTIFIER, "for variable name")
        self._expect(TokenType.COLON, "after variable name")
        self._expect(TokenType.INT_TYPE, "for variable type")

        init_value: Expr | None = None
        if self._match(TokenType.ASSIGN):
            init_value = self._expr()

        return VarDecl(
            name=str(name_tok.value),
            init_value=init_value,
            line=var_tok.line,
        )

    def _const_decl(self) -> ConstDecl:
        """``const IDENT = INT_LITERAL``"""
        const_tok = self._expect(TokenType.CONST)
        name_tok = self._expect(TokenType.IDENTIFIER, "for constant name")
        self._expect(TokenType.ASSIGN, "after constant name")

        # Allow expressions as const values (but typically just a literal)
        val_tok = self._peek()
        negative = False
        if self._match(TokenType.MINUS):
            negative = True
            val_tok = self._peek()
        lit_tok = self._expect(TokenType.INT_LITERAL, "for constant value")
        value = int(lit_tok.value)  # type: ignore[arg-type]
        if negative:
            value = -value

        return ConstDecl(
            name=str(name_tok.value),
            value=value,
            line=const_tok.line,
        )

    def _array_decl(self) -> ArrayDecl:
        """``array IDENT [ INT_LITERAL ]``"""
        arr_tok = self._expect(TokenType.ARRAY)
        name_tok = self._expect(TokenType.IDENTIFIER, "for array name")
        self._expect(TokenType.LBRACKET, "after array name")
        size_tok = self._expect(TokenType.INT_LITERAL, "for array size")
        self._expect(TokenType.RBRACKET, "after array size")
        return ArrayDecl(
            name=str(name_tok.value),
            size=int(size_tok.value),  # type: ignore[arg-type]
            line=arr_tok.line,
        )

    def _func_def(self) -> FuncDef:
        """``func IDENT ( params ) ( -> int )? : NEWLINE INDENT body DEDENT``"""
        func_tok = self._expect(TokenType.FUNC)
        name_tok = self._expect(TokenType.IDENTIFIER, "for function name")
        self._expect(TokenType.LPAREN, "after function name")
        params = self._params()
        self._expect(TokenType.RPAREN, "after function parameters")

        has_return = False
        if self._match(TokenType.ARROW):
            self._expect(TokenType.INT_TYPE, "for return type")
            has_return = True

        self._expect(TokenType.COLON, "after function signature")
        self._expect(TokenType.NEWLINE, "after ':'")
        self._expect(TokenType.INDENT, "for function body")
        body = self._body()
        self._expect(TokenType.DEDENT, "after function body")

        return FuncDef(
            name=str(name_tok.value),
            params=params,
            body=body,
            has_return=has_return,
            line=func_tok.line,
        )

    def _params(self) -> list[str]:
        """``(IDENT : int (, IDENT : int)*)?``"""
        params: list[str] = []
        if self._check(TokenType.RPAREN):
            return params

        name_tok = self._expect(TokenType.IDENTIFIER, "for parameter name")
        self._expect(TokenType.COLON, "after parameter name")
        self._expect(TokenType.INT_TYPE, "for parameter type")
        params.append(str(name_tok.value))

        while self._match(TokenType.COMMA):
            name_tok = self._expect(TokenType.IDENTIFIER, "for parameter name")
            self._expect(TokenType.COLON, "after parameter name")
            self._expect(TokenType.INT_TYPE, "for parameter type")
            params.append(str(name_tok.value))

        return params

    # -- body / statements --------------------------------------------------

    def _body(self) -> list[Statement]:
        """Parse one or more statements until DEDENT (without consuming it)."""
        stmts: list[Statement] = []
        while not self._check(TokenType.DEDENT) and not self._check(TokenType.EOF):
            stmts.append(self._statement())
            self._skip_newlines()
        if not stmts:
            raise ParseError("expected at least one statement in block", self._peek().line)
        return stmts

    def _statement(self) -> Statement:
        """Dispatch to the appropriate statement parser."""
        tok = self._peek()

        if tok.type == TokenType.VAR:
            decl = self._var_decl()
            self._expect(TokenType.NEWLINE, "after variable declaration")
            return decl

        if tok.type == TokenType.IF:
            return self._if_stmt()

        if tok.type == TokenType.WHILE:
            return self._while_stmt()

        if tok.type == TokenType.RETURN:
            return self._return_stmt()

        # Assignment or expression statement.
        # We need lookahead to distinguish:
        #   IDENT = expr            (assignment)
        #   IDENT [ expr ] = expr   (array assignment)
        #   expr                    (expression statement, e.g. function call)
        if tok.type == TokenType.IDENTIFIER:
            return self._assignment_or_expr_stmt()

        # Fallback: expression statement
        return self._expr_stmt()

    def _if_stmt(self) -> IfStmt:
        """``if expr : NEWLINE INDENT body DEDENT (else ...)?``"""
        if_tok = self._expect(TokenType.IF)
        condition = self._expr()
        self._expect(TokenType.COLON, "after if condition")
        self._expect(TokenType.NEWLINE, "after ':'")
        self._expect(TokenType.INDENT, "for if body")
        then_body = self._body()
        self._expect(TokenType.DEDENT, "after if body")

        else_body: list[Statement] | None = None
        if self._match(TokenType.ELSE):
            self._expect(TokenType.COLON, "after else")
            self._expect(TokenType.NEWLINE, "after ':'")
            self._expect(TokenType.INDENT, "for else body")
            else_body = self._body()
            self._expect(TokenType.DEDENT, "after else body")

        return IfStmt(
            condition=condition,
            then_body=then_body,
            else_body=else_body,
            line=if_tok.line,
        )

    def _while_stmt(self) -> WhileStmt:
        """``while expr : NEWLINE INDENT body DEDENT``"""
        while_tok = self._expect(TokenType.WHILE)
        condition = self._expr()
        self._expect(TokenType.COLON, "after while condition")
        self._expect(TokenType.NEWLINE, "after ':'")
        self._expect(TokenType.INDENT, "for while body")
        body = self._body()
        self._expect(TokenType.DEDENT, "after while body")
        return WhileStmt(condition=condition, body=body, line=while_tok.line)

    def _return_stmt(self) -> ReturnStmt:
        """``return expr? NEWLINE``"""
        ret_tok = self._expect(TokenType.RETURN)
        value: Expr | None = None
        if not self._check(TokenType.NEWLINE):
            value = self._expr()
        self._expect(TokenType.NEWLINE, "after return statement")
        return ReturnStmt(value=value, line=ret_tok.line)

    def _assignment_or_expr_stmt(self) -> Statement:
        """Parse IDENT-led statement: assignment, array assignment, or expr."""
        tok = self._peek()
        line = tok.line

        # Peek ahead to decide
        # Save position for backtracking
        saved = self._pos
        name_tok = self._advance()  # consume IDENT
        name = str(name_tok.value)

        # Case 1: IDENT = expr  (simple assignment)
        if self._match(TokenType.ASSIGN):
            value = self._expr()
            self._expect(TokenType.NEWLINE, "after assignment")
            return Assignment(target=name, value=value, line=line)

        # Case 2: IDENT [ expr ] = expr  (array assignment)
        if self._check(TokenType.LBRACKET):
            # We need to check if this is array assignment vs. array access
            # in an expression. Peek further: IDENT [ expr ] = ... is assignment.
            bracket_pos = self._pos
            self._advance()  # consume [
            index = self._expr()
            self._expect(TokenType.RBRACKET, "after array index")

            if self._match(TokenType.ASSIGN):
                value = self._expr()
                self._expect(TokenType.NEWLINE, "after array assignment")
                return ArrayAssignment(name=name, index=index, value=value, line=line)

            # Not an assignment — backtrack and parse as expression statement
            self._pos = saved
            return self._expr_stmt()

        # Case 3: expression statement (e.g. function call)
        self._pos = saved
        return self._expr_stmt()

    def _expr_stmt(self) -> ExprStmt:
        """Parse a standalone expression (usually a function call)."""
        line = self._peek().line
        expr = self._expr()
        self._expect(TokenType.NEWLINE, "after expression")
        return ExprStmt(expr=expr, line=line)

    # -- expressions (precedence climbing) ----------------------------------

    def _expr(self) -> Expr:
        """Top-level expression: or_expr."""
        return self._or_expr()

    def _or_expr(self) -> Expr:
        """``and_expr ('or' and_expr)*``"""
        left = self._and_expr()
        while self._match(TokenType.OR):
            right = self._and_expr()
            left = BinOp(op="or", left=left, right=right)
        return left

    def _and_expr(self) -> Expr:
        """``not_expr ('and' not_expr)*``"""
        left = self._not_expr()
        while self._match(TokenType.AND):
            right = self._not_expr()
            left = BinOp(op="and", left=left, right=right)
        return left

    def _not_expr(self) -> Expr:
        """``'not' not_expr | comparison``"""
        if self._match(TokenType.NOT):
            operand = self._not_expr()
            return UnaryOp(op="not", operand=operand)
        return self._comparison()

    def _comparison(self) -> Expr:
        """``add_expr (comp_op add_expr)?``"""
        left = self._add_expr()
        if self._peek().type in _COMPARISON_OPS:
            op_tok = self._advance()
            right = self._add_expr()
            left = BinOp(op=_OP_STRINGS[op_tok.type], left=left, right=right)
        return left

    def _add_expr(self) -> Expr:
        """``mul_expr (('+' | '-') mul_expr)*``"""
        left = self._mul_expr()
        while self._peek().type in (TokenType.PLUS, TokenType.MINUS):
            op_tok = self._advance()
            right = self._mul_expr()
            left = BinOp(op=_OP_STRINGS[op_tok.type], left=left, right=right)
        return left

    def _mul_expr(self) -> Expr:
        """``unary_expr (('*' | '/' | '%') unary_expr)*``"""
        left = self._unary_expr()
        while self._peek().type in (TokenType.STAR, TokenType.SLASH, TokenType.PERCENT):
            op_tok = self._advance()
            right = self._unary_expr()
            left = BinOp(op=_OP_STRINGS[op_tok.type], left=left, right=right)
        return left

    def _unary_expr(self) -> Expr:
        """``'-' unary_expr | atom``"""
        if self._match(TokenType.MINUS):
            operand = self._unary_expr()
            return UnaryOp(op="-", operand=operand)
        return self._atom()

    def _atom(self) -> Expr:
        """Parse an atomic expression.

        ``INT_LITERAL | IDENT '(' args ')' | IDENT '[' expr ']' | IDENT | '(' expr ')'``
        """
        tok = self._peek()

        # Integer literal
        if tok.type == TokenType.INT_LITERAL:
            self._advance()
            return IntLiteral(value=int(tok.value))  # type: ignore[arg-type]

        # Parenthesised expression
        if tok.type == TokenType.LPAREN:
            self._advance()
            expr = self._expr()
            self._expect(TokenType.RPAREN, "after parenthesised expression")
            return expr

        # Identifier — may be bare ref, function call, or array access
        if tok.type == TokenType.IDENTIFIER:
            self._advance()
            name = str(tok.value)

            # Function call: IDENT ( args )
            if self._match(TokenType.LPAREN):
                args = self._args()
                self._expect(TokenType.RPAREN, "after function arguments")
                return FuncCall(name=name, args=args)

            # Array access: IDENT [ expr ]
            if self._match(TokenType.LBRACKET):
                index = self._expr()
                self._expect(TokenType.RBRACKET, "after array index")
                return ArrayAccess(name=name, index=index)

            # Bare variable / constant reference
            return VarRef(name=name)

        raise ParseError(
            f"expected expression, got {tok.type.name} ({tok.value!r})",
            tok.line,
        )

    def _args(self) -> list[Expr]:
        """``(expr (',' expr)*)?``"""
        args: list[Expr] = []
        if self._check(TokenType.RPAREN):
            return args

        args.append(self._expr())
        while self._match(TokenType.COMMA):
            args.append(self._expr())

        return args
