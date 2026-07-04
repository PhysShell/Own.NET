//! Lexer — a token-for-token, message-for-message port of `ownlang/lexer.py`.
//!
//! Positions are 1-based line:col counted in **characters** (Python iterates
//! `str` code points, so a multi-byte character advances `col` by one — byte
//! offsets would diverge). Identifier characters follow `char::is_alphabetic`
//! / `is_alphanumeric` + `_`; **digits are ASCII-only**: Python's `str.isdigit`
//! also accepts exotic Unicode digits (and then `int()` crashes on some of
//! them) — a quirk deliberately not reproduced (recorded divergence; the
//! parity fixtures stay ASCII).

use crate::pyrepr::py_repr;

/// Token kinds — the exact `lexer.Tok` vocabulary. `python_name` must return
/// the Python enum member name verbatim: it appears inside `ParseError`
/// messages (`... (got IDENT 'x')`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Tok {
    Ident,
    Int,
    Str,
    Module,
    Resource,
    Acquire,
    Release,
    Extern,
    Fn,
    Let,
    Move,
    Borrow,
    BorrowMut,
    Consume,
    As,
    Use,
    Overspan,
    If,
    Else,
    While,
    Return,
    Mut,
    Policy,
    EmitType,
    EmitAcquire,
    EmitRelease,
    EmitBorrow,
    Lifetime,
    Subscribe,
    Rejected,
    LParen,
    RParen,
    LBrace,
    RBrace,
    Comma,
    Colon,
    Semi,
    Amp,
    Eq,
    Dot,
    Arrow,
    Lt,
    Eof,
}

impl Tok {
    #[must_use]
    pub const fn python_name(self) -> &'static str {
        match self {
            Self::Ident => "IDENT",
            Self::Int => "INT",
            Self::Str => "STRING",
            Self::Module => "MODULE",
            Self::Resource => "RESOURCE",
            Self::Acquire => "ACQUIRE",
            Self::Release => "RELEASE",
            Self::Extern => "EXTERN",
            Self::Fn => "FN",
            Self::Let => "LET",
            Self::Move => "MOVE",
            Self::Borrow => "BORROW",
            Self::BorrowMut => "BORROW_MUT",
            Self::Consume => "CONSUME",
            Self::As => "AS",
            Self::Use => "USE",
            Self::Overspan => "OVERSPAN",
            Self::If => "IF",
            Self::Else => "ELSE",
            Self::While => "WHILE",
            Self::Return => "RETURN",
            Self::Mut => "MUT",
            Self::Policy => "POLICY",
            Self::EmitType => "EMIT_TYPE",
            Self::EmitAcquire => "EMIT_ACQUIRE",
            Self::EmitRelease => "EMIT_RELEASE",
            Self::EmitBorrow => "EMIT_BORROW",
            Self::Lifetime => "LIFETIME",
            Self::Subscribe => "SUBSCRIBE",
            Self::Rejected => "REJECTED",
            Self::LParen => "LPAREN",
            Self::RParen => "RPAREN",
            Self::LBrace => "LBRACE",
            Self::RBrace => "RBRACE",
            Self::Comma => "COMMA",
            Self::Colon => "COLON",
            Self::Semi => "SEMI",
            Self::Amp => "AMP",
            Self::Eq => "EQ",
            Self::Dot => "DOT",
            Self::Arrow => "ARROW",
            Self::Lt => "LT",
            Self::Eof => "EOF",
        }
    }
}

fn keyword(word: &str) -> Option<Tok> {
    Some(match word {
        "module" => Tok::Module,
        "resource" => Tok::Resource,
        "acquire" => Tok::Acquire,
        "release" => Tok::Release,
        "extern" => Tok::Extern,
        "fn" => Tok::Fn,
        "let" => Tok::Let,
        "move" => Tok::Move,
        "borrow" => Tok::Borrow,
        "borrow_mut" => Tok::BorrowMut,
        "consume" => Tok::Consume,
        "as" => Tok::As,
        "use" => Tok::Use,
        "overspan" => Tok::Overspan,
        "if" => Tok::If,
        "else" => Tok::Else,
        "while" => Tok::While,
        "return" => Tok::Return,
        "mut" => Tok::Mut,
        "policy" => Tok::Policy,
        "emit_type" => Tok::EmitType,
        "emit_acquire" => Tok::EmitAcquire,
        "emit_release" => Tok::EmitRelease,
        "emit_borrow" => Tok::EmitBorrow,
        "lifetime" => Tok::Lifetime,
        "subscribe" => Tok::Subscribe,
        _ => return None,
    })
}

/// Deliberately-unsupported constructs, lexed so the parser can say so plainly.
const REJECTED_KEYWORDS: [&str; 6] = ["for", "loop", "async", "await", "yield", "spawn"];

/// One token. `text` is the *cooked* text (a string literal's unescaped
/// content), exactly like Python's `Token.text`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Token {
    pub kind: Tok,
    pub text: String,
    pub line: u32,
    pub col: u32,
}

/// Lexing failure. Displays exactly like Python's `str(LexError)`:
/// `"{line}:{col}: {msg}"`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LexError {
    pub msg: String,
    pub line: u32,
    pub col: u32,
}

impl std::fmt::Display for LexError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}:{}: {}", self.line, self.col, self.msg)
    }
}

impl std::error::Error for LexError {}

struct Lexer {
    chars: Vec<char>,
    i: usize,
    line: u32,
    col: u32,
}

impl Lexer {
    fn peek_at(&self, k: usize) -> Option<char> {
        self.chars.get(self.i.saturating_add(k)).copied()
    }

    fn cur(&self) -> Option<char> {
        self.peek_at(0)
    }

    fn advance(&mut self, k: usize) {
        for _ in 0..k {
            if self.cur() == Some('\n') {
                self.line = self.line.saturating_add(1);
                self.col = 1;
            } else {
                self.col = self.col.saturating_add(1);
            }
            self.i = self.i.saturating_add(1);
        }
    }
}

fn is_ident_start(c: char) -> bool {
    c.is_alphabetic() || c == '_'
}

fn is_ident_continue(c: char) -> bool {
    c.is_alphanumeric() || c == '_'
}

/// Tokenize a whole source text.
///
/// # Errors
/// [`LexError`] on an unterminated string literal or an unexpected character,
/// with the same message and position as the Python lexer.
// One long dispatch loop on purpose: it mirrors Python's single `lex()` so
// the two stay diffable statement by statement.
#[allow(clippy::too_many_lines)]
pub fn lex(src: &str) -> Result<Vec<Token>, LexError> {
    let mut lx = Lexer {
        chars: src.chars().collect(),
        i: 0,
        line: 1,
        col: 1,
    };
    let mut toks: Vec<Token> = Vec::new();

    while let Some(c) = lx.cur() {
        if c == ' ' || c == '\t' || c == '\r' || c == '\n' {
            lx.advance(1);
            continue;
        }
        if c == '/' && lx.peek_at(1) == Some('/') {
            while let Some(x) = lx.cur() {
                if x == '\n' {
                    break;
                }
                lx.advance(1);
            }
            continue;
        }

        let (start_line, start_col) = (lx.line, lx.col);

        if c == '"' {
            lx.advance(1); // opening quote
            let mut text = String::new();
            loop {
                match lx.cur() {
                    None => {
                        return Err(LexError {
                            msg: "unterminated string literal".to_owned(),
                            line: start_line,
                            col: start_col,
                        })
                    }
                    Some('"') => break,
                    Some('\\') if lx.peek_at(1).is_some() => {
                        let nxt = lx.peek_at(1).unwrap_or('\\');
                        text.push(match nxt {
                            'n' => '\n',
                            't' => '\t',
                            '"' => '"',
                            '\\' => '\\',
                            other => other,
                        });
                        lx.advance(2);
                    }
                    Some(x) => {
                        text.push(x);
                        lx.advance(1);
                    }
                }
            }
            lx.advance(1); // closing quote
            toks.push(Token {
                kind: Tok::Str,
                text,
                line: start_line,
                col: start_col,
            });
            continue;
        }

        if is_ident_start(c) {
            let mut word = String::new();
            while let Some(x) = lx.cur() {
                if !is_ident_continue(x) {
                    break;
                }
                word.push(x);
                lx.advance(1);
            }
            let kind = if REJECTED_KEYWORDS.contains(&word.as_str()) {
                Tok::Rejected
            } else {
                keyword(&word).unwrap_or(Tok::Ident)
            };
            toks.push(Token {
                kind,
                text: word,
                line: start_line,
                col: start_col,
            });
            continue;
        }

        if c.is_ascii_digit() {
            let mut num = String::new();
            while let Some(x) = lx.cur() {
                if !x.is_ascii_digit() {
                    break;
                }
                num.push(x);
                lx.advance(1);
            }
            toks.push(Token {
                kind: Tok::Int,
                text: num,
                line: start_line,
                col: start_col,
            });
            continue;
        }

        if c == '-' && lx.peek_at(1) == Some('>') {
            lx.advance(2);
            toks.push(Token {
                kind: Tok::Arrow,
                text: "->".to_owned(),
                line: start_line,
                col: start_col,
            });
            continue;
        }

        let simple = match c {
            '(' => Some(Tok::LParen),
            ')' => Some(Tok::RParen),
            '{' => Some(Tok::LBrace),
            '}' => Some(Tok::RBrace),
            ',' => Some(Tok::Comma),
            ':' => Some(Tok::Colon),
            ';' => Some(Tok::Semi),
            '&' => Some(Tok::Amp),
            '=' => Some(Tok::Eq),
            '.' => Some(Tok::Dot),
            '<' => Some(Tok::Lt),
            _ => None,
        };
        if let Some(kind) = simple {
            lx.advance(1);
            toks.push(Token {
                kind,
                text: c.to_string(),
                line: start_line,
                col: start_col,
            });
            continue;
        }

        return Err(LexError {
            msg: format!("unexpected character {}", py_repr(&c.to_string())),
            line: start_line,
            col: start_col,
        });
    }

    toks.push(Token {
        kind: Tok::Eof,
        text: String::new(),
        line: lx.line,
        col: lx.col,
    });
    Ok(toks)
}

#[cfg(test)]
#[allow(clippy::panic, clippy::expect_used, clippy::unwrap_used)]
mod tests {
    //! Token-level behaviour the parser-level fixtures only exercise
    //! indirectly: cooked string escapes, comment skipping, char-based
    //! (not byte-based) columns, and error positions.

    use super::{lex, Tok};

    #[test]
    fn string_escapes_are_cooked_like_python() {
        let toks = lex(r#""a\nb\t\"q\"\\z\d""#).expect("lexes");
        let s = toks.first().expect("string token");
        assert_eq!(s.kind, Tok::Str);
        // \n, \t, \", \\ from the escape map; unknown \d keeps the char.
        assert_eq!(s.text, "a\nb\t\"q\"\\zd");
    }

    #[test]
    fn comments_and_whitespace_vanish() {
        let toks = lex("let // rest of line\n  x").expect("lexes");
        let kinds: Vec<Tok> = toks.iter().map(|t| t.kind).collect();
        assert_eq!(kinds, [Tok::Let, Tok::Ident, Tok::Eof]);
        let x = toks.get(1).expect("x");
        assert_eq!((x.line, x.col), (2, 3));
    }

    #[test]
    fn columns_count_chars_not_bytes() {
        // 'ждать' is 5 chars / 10 UTF-8 bytes; Python counts str positions.
        let err = lex("ждать @").expect_err("@ rejects");
        assert_eq!((err.line, err.col), (1, 7));
        assert_eq!(err.to_string(), "1:7: unexpected character '@'");
    }

    #[test]
    fn unterminated_string_reports_opening_quote() {
        let err = lex("  \"oops").expect_err("unterminated");
        assert_eq!(err.to_string(), "1:3: unterminated string literal");
    }

    #[test]
    fn keywords_rejected_words_and_arrow() {
        let toks = lex("borrow_mut for x -> <").expect("lexes");
        let kinds: Vec<Tok> = toks.iter().map(|t| t.kind).collect();
        assert_eq!(
            kinds,
            [
                Tok::BorrowMut,
                Tok::Rejected,
                Tok::Ident,
                Tok::Arrow,
                Tok::Lt,
                Tok::Eof
            ]
        );
    }
}
