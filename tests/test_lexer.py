"""Tests for the TTDoom DSL lexer."""

from __future__ import annotations

import pytest

from compiler.lexer import Lexer, LexerError, Token, TokenType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _types(source: str) -> list[TokenType]:
    """Return just the token types for *source* (excluding EOF)."""
    tokens = Lexer(source).tokenize()
    return [t.type for t in tokens if t.type != TokenType.EOF]


def _values(source: str) -> list[str | int | None]:
    """Return just the token values for *source* (excluding EOF)."""
    tokens = Lexer(source).tokenize()
    return [t.value for t in tokens if t.type != TokenType.EOF]


# ---------------------------------------------------------------------------
# 1. Simple variable declaration
# ---------------------------------------------------------------------------

class TestVarDecl:
    def test_var_decl_with_init(self) -> None:
        tokens = Lexer("var player_x: int = 512").tokenize()
        types = [t.type for t in tokens[:-1]]  # drop EOF
        assert types == [
            TokenType.VAR,
            TokenType.IDENTIFIER,
            TokenType.COLON,
            TokenType.INT_TYPE,
            TokenType.ASSIGN,
            TokenType.INT_LITERAL,
            TokenType.NEWLINE,
        ]
        # Value of the integer literal
        assert tokens[5].value == 512

    def test_var_decl_no_init(self) -> None:
        types = _types("var temp: int")
        assert types == [
            TokenType.VAR,
            TokenType.IDENTIFIER,
            TokenType.COLON,
            TokenType.INT_TYPE,
            TokenType.NEWLINE,
        ]


# ---------------------------------------------------------------------------
# 2. Function definition (header only — no body for this test)
# ---------------------------------------------------------------------------

class TestFuncDef:
    def test_func_header(self) -> None:
        src = "func add(a: int, b: int) -> int:"
        types = _types(src)
        assert types == [
            TokenType.FUNC,
            TokenType.IDENTIFIER,  # add
            TokenType.LPAREN,
            TokenType.IDENTIFIER,  # a
            TokenType.COLON,
            TokenType.INT_TYPE,
            TokenType.COMMA,
            TokenType.IDENTIFIER,  # b
            TokenType.COLON,
            TokenType.INT_TYPE,
            TokenType.RPAREN,
            TokenType.ARROW,
            TokenType.INT_TYPE,
            TokenType.COLON,
            TokenType.NEWLINE,
        ]


# ---------------------------------------------------------------------------
# 3. Comments
# ---------------------------------------------------------------------------

class TestComments:
    def test_comment_only_line(self) -> None:
        """A comment-only line should produce no tokens (besides EOF)."""
        tokens = Lexer("# this is a comment").tokenize()
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.EOF

    def test_inline_comment(self) -> None:
        """Tokens before a comment should be emitted; comment text ignored."""
        types = _types("var x: int  # a comment")
        assert types == [
            TokenType.VAR,
            TokenType.IDENTIFIER,
            TokenType.COLON,
            TokenType.INT_TYPE,
            TokenType.NEWLINE,
        ]

    def test_multiple_comment_lines(self) -> None:
        src = "# comment1\n# comment2\nvar x: int"
        types = _types(src)
        assert types == [
            TokenType.VAR,
            TokenType.IDENTIFIER,
            TokenType.COLON,
            TokenType.INT_TYPE,
            TokenType.NEWLINE,
        ]


# ---------------------------------------------------------------------------
# 4. Indentation (INDENT / DEDENT)
# ---------------------------------------------------------------------------

class TestIndentation:
    def test_indent_dedent(self) -> None:
        src = (
            "func f():\n"
            "    return 1\n"
        )
        types = _types(src)
        assert types == [
            TokenType.FUNC,
            TokenType.IDENTIFIER,
            TokenType.LPAREN,
            TokenType.RPAREN,
            TokenType.COLON,
            TokenType.NEWLINE,
            TokenType.INDENT,
            TokenType.RETURN,
            TokenType.INT_LITERAL,
            TokenType.NEWLINE,
            TokenType.DEDENT,
        ]

    def test_nested_indent(self) -> None:
        src = (
            "if x:\n"
            "    if y:\n"
            "        return 1\n"
        )
        types = _types(src)
        assert TokenType.INDENT in types
        # Should have two INDENTs and two DEDENTs
        assert types.count(TokenType.INDENT) == 2
        assert types.count(TokenType.DEDENT) == 2

    def test_multiple_dedents_at_once(self) -> None:
        src = (
            "if x:\n"
            "    if y:\n"
            "        return 1\n"
            "var z: int\n"
        )
        types = _types(src)
        # Going from indent=8 back to indent=0 should emit 2 DEDENTs
        assert types.count(TokenType.INDENT) == 2
        assert types.count(TokenType.DEDENT) == 2

    def test_inconsistent_indent_raises(self) -> None:
        src = (
            "if x:\n"
            "    return 1\n"
            "  return 2\n"  # only 2 spaces — inconsistent
        )
        with pytest.raises(LexerError, match="inconsistent indentation"):
            Lexer(src).tokenize()


# ---------------------------------------------------------------------------
# 5. All operators
# ---------------------------------------------------------------------------

class TestOperators:
    @pytest.mark.parametrize(
        "symbol, expected_type",
        [
            ("+", TokenType.PLUS),
            ("-", TokenType.MINUS),
            ("*", TokenType.STAR),
            ("/", TokenType.SLASH),
            ("%", TokenType.PERCENT),
            ("=", TokenType.ASSIGN),
            ("==", TokenType.EQ),
            ("!=", TokenType.NEQ),
            ("<", TokenType.LT),
            (">", TokenType.GT),
            ("<=", TokenType.LTEQ),
            (">=", TokenType.GTEQ),
            ("->", TokenType.ARROW),
        ],
    )
    def test_operator(self, symbol: str, expected_type: TokenType) -> None:
        # Wrap in an expression context so the lexer doesn't choke on bare op
        src = f"a {symbol} b" if symbol not in ("=", "->") else f"a{symbol}b"
        tokens = Lexer(src).tokenize()
        op_tokens = [t for t in tokens if t.type == expected_type]
        assert len(op_tokens) == 1

    def test_all_delimiters(self) -> None:
        src = "( ) [ ] : ,"
        types = _types(src)
        assert TokenType.LPAREN in types
        assert TokenType.RPAREN in types
        assert TokenType.LBRACKET in types
        assert TokenType.RBRACKET in types
        assert TokenType.COLON in types
        assert TokenType.COMMA in types


# ---------------------------------------------------------------------------
# 6. Integer literals (decimal and hex)
# ---------------------------------------------------------------------------

class TestIntLiterals:
    def test_decimal(self) -> None:
        tokens = Lexer("42").tokenize()
        assert tokens[0].type == TokenType.INT_LITERAL
        assert tokens[0].value == 42

    def test_hex_lower(self) -> None:
        tokens = Lexer("0xff").tokenize()
        assert tokens[0].value == 255

    def test_hex_upper(self) -> None:
        tokens = Lexer("0XAB").tokenize()
        assert tokens[0].value == 0xAB

    def test_zero(self) -> None:
        tokens = Lexer("0").tokenize()
        assert tokens[0].value == 0


# ---------------------------------------------------------------------------
# 7. Invalid token
# ---------------------------------------------------------------------------

class TestErrors:
    def test_invalid_character(self) -> None:
        with pytest.raises(LexerError, match="unexpected character"):
            Lexer("var x = @").tokenize()

    def test_error_has_line_info(self) -> None:
        try:
            Lexer("var x = @").tokenize()
        except LexerError as exc:
            assert exc.line == 1
            assert exc.column > 0


# ---------------------------------------------------------------------------
# 8. Multi-line program
# ---------------------------------------------------------------------------

class TestMultiLine:
    def test_multi_line(self) -> None:
        src = (
            "var x: int = 1\n"
            "var y: int = 2\n"
        )
        types = _types(src)
        # Should have two NEWLINE tokens (one per line)
        assert types.count(TokenType.NEWLINE) == 2
        # Should have two VAR keywords
        assert types.count(TokenType.VAR) == 2

    def test_complete_function(self) -> None:
        src = (
            "func add(a: int, b: int) -> int:\n"
            "    return a + b\n"
        )
        tokens = Lexer(src).tokenize()
        types = [t.type for t in tokens]
        assert TokenType.FUNC in types
        assert TokenType.ARROW in types
        assert TokenType.INDENT in types
        assert TokenType.RETURN in types
        assert TokenType.PLUS in types
        assert TokenType.DEDENT in types


# ---------------------------------------------------------------------------
# 9. Arrow operator (->)
# ---------------------------------------------------------------------------

class TestArrow:
    def test_arrow_not_confused_with_minus_gt(self) -> None:
        """-> should be a single ARROW token, not MINUS then GT."""
        src = "-> int"
        tokens = Lexer(src).tokenize()
        assert tokens[0].type == TokenType.ARROW
        assert tokens[0].value == "->"


# ---------------------------------------------------------------------------
# 10. Empty lines between statements
# ---------------------------------------------------------------------------

class TestEmptyLines:
    def test_blank_lines_ignored(self) -> None:
        src = (
            "var x: int\n"
            "\n"
            "\n"
            "var y: int\n"
        )
        types = _types(src)
        assert types.count(TokenType.VAR) == 2
        assert types.count(TokenType.NEWLINE) == 2

    def test_blank_lines_inside_block(self) -> None:
        src = (
            "func f():\n"
            "    var x: int\n"
            "\n"
            "    return x\n"
        )
        types = _types(src)
        # Blank line between two indented lines should not affect indent level
        assert types.count(TokenType.INDENT) == 1
        assert types.count(TokenType.DEDENT) == 1


# ---------------------------------------------------------------------------
# 11. Keywords vs identifiers
# ---------------------------------------------------------------------------

class TestKeywordsVsIdentifiers:
    def test_keywords_recognised(self) -> None:
        src = "var const array func if else while return int and or not"
        types = _types(src)
        expected = [
            TokenType.VAR, TokenType.CONST, TokenType.ARRAY, TokenType.FUNC,
            TokenType.IF, TokenType.ELSE, TokenType.WHILE, TokenType.RETURN,
            TokenType.INT_TYPE, TokenType.AND, TokenType.OR, TokenType.NOT,
            TokenType.NEWLINE,
        ]
        assert types == expected

    def test_keyword_prefix_is_identifier(self) -> None:
        """An identifier that starts with a keyword should remain IDENTIFIER."""
        tokens = Lexer("variable").tokenize()
        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[0].value == "variable"


# ---------------------------------------------------------------------------
# 12. Line numbers
# ---------------------------------------------------------------------------

class TestLineNumbers:
    def test_line_tracking(self) -> None:
        src = "var x: int\nvar y: int\n"
        tokens = Lexer(src).tokenize()
        # First VAR on line 1
        assert tokens[0].line == 1
        # Second VAR token (after NEWLINE) should be on line 2
        var_tokens = [t for t in tokens if t.type == TokenType.VAR]
        assert var_tokens[0].line == 1
        assert var_tokens[1].line == 2
