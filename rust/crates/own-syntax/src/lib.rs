//! `own-syntax` — `OwnLang` lexer, recursive-descent parser and AST: the port
//! of `ownlang/{lexer,parser,ast_nodes}.py` (P-022 migration step 2).
//!
//! Contract: **accept exactly what Python accepts, reject exactly what Python
//! rejects, with byte-identical error text** (`LexError` / `ParseError`
//! `Display` match Python's `str()`, down to `CPython` `repr()` quoting of the
//! offending token). The shared fixtures under `tests/fixtures/` in the repo
//! root are asserted from both sides — Python regenerates/verifies them, the
//! Rust integration test replays them.
//!
//! Recorded divergences (deliberate, loud, out of the corpus envelope):
//! digits are ASCII-only (`token`), integer literals cap at `u64` (`ast`).

pub mod ast;
pub mod parser;
mod pyrepr;
pub mod token;

pub use parser::{parse, ParseError, SyntaxError};
pub use token::{lex, LexError, Tok, Token};
