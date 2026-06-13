"""
Lexer for OwnLang — a tiny ownership-checked language.

Deliberately small. We tokenize keywords, identifiers, integer literals, string
literals (used only for C#-emit templates on a resource), and a handful of
punctuation. The features we explicitly DON'T support (loops, async) are lexed
as their own token class so the parser can emit an honest "out of scope"
diagnostic instead of a confusing parse error.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class Tok(Enum):
    # literals / names
    IDENT = auto()
    INT = auto()
    STRING = auto()
    # keywords
    MODULE = auto()
    RESOURCE = auto()
    ACQUIRE = auto()
    RELEASE = auto()
    EXTERN = auto()
    FN = auto()
    LET = auto()
    MOVE = auto()
    BORROW = auto()
    BORROW_MUT = auto()
    CONSUME = auto()
    AS = auto()
    USE = auto()
    IF = auto()
    ELSE = auto()
    RETURN = auto()
    MUT = auto()
    # emit-template keywords (only meaningful inside a resource body)
    EMIT_TYPE = auto()
    EMIT_ACQUIRE = auto()
    EMIT_RELEASE = auto()
    EMIT_BORROW = auto()
    # explicitly-unsupported keywords (reported, not parsed)
    REJECTED = auto()
    # punctuation
    LPAREN = auto()
    RPAREN = auto()
    LBRACE = auto()
    RBRACE = auto()
    COMMA = auto()
    COLON = auto()
    SEMI = auto()
    AMP = auto()
    EQ = auto()
    ARROW = auto()
    EOF = auto()


KEYWORDS = {
    "module": Tok.MODULE,
    "resource": Tok.RESOURCE,
    "acquire": Tok.ACQUIRE,
    "release": Tok.RELEASE,
    "extern": Tok.EXTERN,
    "fn": Tok.FN,
    "let": Tok.LET,
    "move": Tok.MOVE,
    "borrow": Tok.BORROW,
    "borrow_mut": Tok.BORROW_MUT,
    "consume": Tok.CONSUME,
    "as": Tok.AS,
    "use": Tok.USE,
    "if": Tok.IF,
    "else": Tok.ELSE,
    "return": Tok.RETURN,
    "mut": Tok.MUT,
    "emit_type": Tok.EMIT_TYPE,
    "emit_acquire": Tok.EMIT_ACQUIRE,
    "emit_release": Tok.EMIT_RELEASE,
    "emit_borrow": Tok.EMIT_BORROW,
}

# Things we refuse to analyze in the MVP. Lexed so we can say so plainly.
REJECTED_KEYWORDS = {"while", "for", "loop", "async", "await", "yield", "spawn"}


@dataclass(frozen=True)
class Token:
    kind: Tok
    text: str
    line: int
    col: int

    def __repr__(self) -> str:  # nicer test output
        return f"{self.kind.name}({self.text!r})@{self.line}:{self.col}"


class LexError(Exception):
    def __init__(self, msg: str, line: int, col: int):
        super().__init__(f"{line}:{col}: {msg}")
        self.line = line
        self.col = col


def lex(src: str) -> list[Token]:
    toks: list[Token] = []
    i = 0
    line = 1
    col = 1
    n = len(src)

    def advance(k: int = 1) -> None:
        nonlocal i, line, col
        for _ in range(k):
            if i < n and src[i] == "\n":
                line += 1
                col = 1
            else:
                col += 1
            i += 1

    while i < n:
        c = src[i]

        # whitespace
        if c in " \t\r\n":
            advance()
            continue

        # line comments  // ...
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                advance()
            continue

        start_line, start_col = line, col

        # string literal "..."
        if c == '"':
            advance()  # opening quote
            chars: list[str] = []
            while i < n and src[i] != '"':
                if src[i] == "\\" and i + 1 < n:
                    nxt = src[i + 1]
                    chars.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(nxt, nxt))
                    advance(2)
                else:
                    chars.append(src[i])
                    advance()
            if i >= n:
                raise LexError("unterminated string literal", start_line, start_col)
            advance()  # closing quote
            toks.append(Token(Tok.STRING, "".join(chars), start_line, start_col))
            continue

        # identifiers / keywords
        if c.isalpha() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            word = src[i:j]
            advance(j - i)
            if word in REJECTED_KEYWORDS:
                toks.append(Token(Tok.REJECTED, word, start_line, start_col))
            elif word in KEYWORDS:
                toks.append(Token(KEYWORDS[word], word, start_line, start_col))
            else:
                toks.append(Token(Tok.IDENT, word, start_line, start_col))
            continue

        # integer literals
        if c.isdigit():
            j = i
            while j < n and src[j].isdigit():
                j += 1
            num = src[i:j]
            advance(j - i)
            toks.append(Token(Tok.INT, num, start_line, start_col))
            continue

        # arrow ->
        if c == "-" and i + 1 < n and src[i + 1] == ">":
            advance(2)
            toks.append(Token(Tok.ARROW, "->", start_line, start_col))
            continue

        # single-char punctuation
        simple = {
            "(": Tok.LPAREN,
            ")": Tok.RPAREN,
            "{": Tok.LBRACE,
            "}": Tok.RBRACE,
            ",": Tok.COMMA,
            ":": Tok.COLON,
            ";": Tok.SEMI,
            "&": Tok.AMP,
            "=": Tok.EQ,
        }
        if c in simple:
            advance()
            toks.append(Token(simple[c], c, start_line, start_col))
            continue

        raise LexError(f"unexpected character {c!r}", start_line, start_col)

    toks.append(Token(Tok.EOF, "", line, col))
    return toks
