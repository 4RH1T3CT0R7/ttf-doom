"""Regex-based lexer for the TTDoom DSL.

Produces a stream of :class:`Token` objects from source text.  Handles:

* Python-style indentation (emits INDENT / DEDENT tokens)
* Line comments (``#`` to end of line)
* Hex literals (``0x1A``)
* Multi-character operators (``->``, ``==``, ``!=``, ``<=``, ``>=``)
* Keyword / identifier discrimination
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Iterator


# ---------------------------------------------------------------------------
# Token types
# ---------------------------------------------------------------------------

class TokenType(Enum):
    """Every token the lexer can emit."""

    # Keywords
    VAR = auto()
    CONST = auto()
    ARRAY = auto()
    FUNC = auto()
    IF = auto()
    ELSE = auto()
    WHILE = auto()
    RETURN = auto()
    INT_TYPE = auto()
    AND = auto()
    OR = auto()
    NOT = auto()

    # Literals & identifiers
    INT_LITERAL = auto()
    IDENTIFIER = auto()

    # Operators
    PLUS = auto()       # +
    MINUS = auto()      # -
    STAR = auto()       # *
    SLASH = auto()      # /
    PERCENT = auto()    # %
    ASSIGN = auto()     # =
    EQ = auto()         # ==
    NEQ = auto()        # !=
    LT = auto()         # <
    GT = auto()         # >
    LTEQ = auto()       # <=
    GTEQ = auto()       # >=

    # Delimiters
    LPAREN = auto()     # (
    RPAREN = auto()     # )
    LBRACKET = auto()   # [
    RBRACKET = auto()   # ]
    COLON = auto()      # :
    COMMA = auto()      # ,
    ARROW = auto()      # ->

    # Structure
    NEWLINE = auto()
    INDENT = auto()
    DEDENT = auto()
    EOF = auto()


# Keyword lookup table --------------------------------------------------

_KEYWORDS: dict[str, TokenType] = {
    "var": TokenType.VAR,
    "const": TokenType.CONST,
    "array": TokenType.ARRAY,
    "func": TokenType.FUNC,
    "if": TokenType.IF,
    "else": TokenType.ELSE,
    "while": TokenType.WHILE,
    "return": TokenType.RETURN,
    "int": TokenType.INT_TYPE,
    "and": TokenType.AND,
    "or": TokenType.OR,
    "not": TokenType.NOT,
}


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Token:
    """A single lexical token."""

    type: TokenType
    value: str | int | None
    line: int
    column: int

    def __repr__(self) -> str:  # pragma: no cover — cosmetic
        return f"Token({self.type.name}, {self.value!r}, L{self.line}:{self.column})"


# ---------------------------------------------------------------------------
# Lexer errors
# ---------------------------------------------------------------------------

class LexerError(Exception):
    """Raised when the lexer encounters an invalid character or token."""

    def __init__(self, message: str, line: int, column: int) -> None:
        self.line = line
        self.column = column
        super().__init__(f"Line {line}, column {column}: {message}")


# ---------------------------------------------------------------------------
# Token patterns (order matters — longer matches first)
# ---------------------------------------------------------------------------

# Each entry is (regex, token-type-or-None).  *None* means skip.
_TOKEN_SPEC: list[tuple[str, TokenType | None]] = [
    # Two-character operators (must precede single-char variants)
    (r"->",  TokenType.ARROW),
    (r"==",  TokenType.EQ),
    (r"!=",  TokenType.NEQ),
    (r"<=",  TokenType.LTEQ),
    (r">=",  TokenType.GTEQ),

    # Single-character operators / delimiters
    (r"\+",  TokenType.PLUS),
    (r"-",   TokenType.MINUS),
    (r"\*",  TokenType.STAR),
    (r"/",   TokenType.SLASH),
    (r"%",   TokenType.PERCENT),
    (r"=",   TokenType.ASSIGN),
    (r"<",   TokenType.LT),
    (r">",   TokenType.GT),
    (r"\(",  TokenType.LPAREN),
    (r"\)",  TokenType.RPAREN),
    (r"\[",  TokenType.LBRACKET),
    (r"\]",  TokenType.RBRACKET),
    (r":",   TokenType.COLON),
    (r",",   TokenType.COMMA),

    # Hex integer literal (before decimal so 0x… isn't eaten as '0')
    (r"0[xX][0-9a-fA-F]+", TokenType.INT_LITERAL),
    # Decimal integer literal
    (r"[0-9]+", TokenType.INT_LITERAL),

    # Identifiers / keywords (discrimination happens in code)
    (r"[a-zA-Z_][a-zA-Z0-9_]*", TokenType.IDENTIFIER),

    # Inline whitespace — skip
    (r"[ \t]+", None),
]

# Pre-compile into one big alternation for speed.
_MASTER_RE = re.compile(
    "|".join(f"(?P<G{i}>{pat})" for i, (pat, _) in enumerate(_TOKEN_SPEC))
)


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

class Lexer:
    """Tokenize TTDoom DSL source code.

    Usage::

        lexer = Lexer(source_code)
        tokens = lexer.tokenize()  # list[Token]
    """

    def __init__(self, source: str) -> None:
        self._source = source
        self._tokens: list[Token] = []

    # -- public API ---------------------------------------------------------

    def tokenize(self) -> list[Token]:
        """Return the complete list of tokens for the source text."""
        self._tokens = []
        self._tokenize_lines()
        return self._tokens

    # -- internals ----------------------------------------------------------

    def _tokenize_lines(self) -> None:
        """Walk source lines, handle indentation, and tokenize content."""
        lines = self._source.split("\n")
        indent_stack: list[int] = [0]  # current indentation levels
        line_no = 0

        for raw_line in lines:
            line_no += 1

            # Strip trailing whitespace / CR (keep leading spaces for indent)
            line = raw_line.rstrip()

            # Skip blank lines and comment-only lines
            stripped = line.lstrip()
            if not stripped or stripped.startswith("#"):
                continue

            # --- Indentation handling ---
            indent = len(line) - len(stripped)

            if indent > indent_stack[-1]:
                indent_stack.append(indent)
                self._tokens.append(
                    Token(TokenType.INDENT, None, line_no, 0)
                )
            else:
                while indent < indent_stack[-1]:
                    indent_stack.pop()
                    self._tokens.append(
                        Token(TokenType.DEDENT, None, line_no, 0)
                    )
                if indent != indent_stack[-1]:
                    raise LexerError(
                        "inconsistent indentation",
                        line_no,
                        indent,
                    )

            # --- Tokenize the content portion of the line ---
            self._scan_line(stripped, line_no, indent)

            # Every non-blank line ends with a NEWLINE
            self._tokens.append(
                Token(TokenType.NEWLINE, None, line_no, len(line))
            )

        # Close any remaining indentation at EOF
        while len(indent_stack) > 1:
            indent_stack.pop()
            self._tokens.append(
                Token(TokenType.DEDENT, None, line_no, 0)
            )

        self._tokens.append(Token(TokenType.EOF, None, line_no, 0))

    def _scan_line(self, text: str, line_no: int, col_offset: int) -> None:
        """Tokenize a single line of content (leading whitespace removed)."""
        pos = 0
        while pos < len(text):
            # Skip inline comments
            if text[pos] == "#":
                break

            m = _MASTER_RE.match(text, pos)
            if m is None:
                raise LexerError(
                    f"unexpected character {text[pos]!r}",
                    line_no,
                    col_offset + pos + 1,
                )

            # Figure out which group matched
            group_name = m.lastgroup
            assert group_name is not None
            idx = int(group_name[1:])  # strip leading 'G'
            _, tok_type = _TOKEN_SPEC[idx]
            raw = m.group()

            if tok_type is not None:
                token = self._make_token(
                    tok_type, raw, line_no, col_offset + pos + 1
                )
                self._tokens.append(token)

            pos = m.end()

    @staticmethod
    def _make_token(
        tok_type: TokenType,
        raw: str,
        line: int,
        column: int,
    ) -> Token:
        """Construct a :class:`Token`, converting values where needed."""
        if tok_type == TokenType.INT_LITERAL:
            value: str | int | None = int(raw, 0)  # handles 0x… automatically
            return Token(tok_type, value, line, column)

        if tok_type == TokenType.IDENTIFIER:
            # Keyword / identifier discrimination
            kw = _KEYWORDS.get(raw)
            if kw is not None:
                return Token(kw, raw, line, column)
            return Token(TokenType.IDENTIFIER, raw, line, column)

        # Operators and delimiters — keep the raw text as the value
        return Token(tok_type, raw, line, column)
