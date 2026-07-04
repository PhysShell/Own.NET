//! Recursive-descent parser — a method-for-method port of `ownlang/parser.py`.
//!
//! The grammar comment there is normative; this file mirrors its structure so
//! the two stay diffable side by side. Error-message parity is a hard
//! requirement: `ParseError` renders exactly like Python's
//! `str(ParseError)` — `"{line}:{col}: {msg} (got {KIND} {text!r})"` — with
//! the position, the Python enum member name, and `CPython` `repr()` quoting.
//!
//! Parity-first, perf-later (P-022 doctrine): tokens are cloned on `eat` and
//! condition text is joined per parse; interning/arenas come only after the
//! differential oracle locks behaviour.

use crate::ast;
use crate::pyrepr::py_repr;
use crate::token::{lex, LexError, Tok, Token};

/// Parse failure. Displays exactly like Python's `str(ParseError)`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParseError {
    pub line: u32,
    pub col: u32,
    rendered: String,
}

impl ParseError {
    fn new(msg: &str, tok: &Token) -> Self {
        Self {
            line: tok.line,
            col: tok.col,
            rendered: format!(
                "{}:{}: {} (got {} {})",
                tok.line,
                tok.col,
                msg,
                tok.kind.python_name(),
                py_repr(&tok.text)
            ),
        }
    }
}

impl std::fmt::Display for ParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.rendered)
    }
}

impl std::error::Error for ParseError {}

/// Either failure of [`parse`] — Python surfaces both `LexError` and
/// `ParseError` from `parse()`; each `Display`s identically to its
/// Python `str()`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SyntaxError {
    Lex(LexError),
    Parse(ParseError),
}

impl std::fmt::Display for SyntaxError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Lex(e) => e.fmt(f),
            Self::Parse(e) => e.fmt(f),
        }
    }
}

impl std::error::Error for SyntaxError {}

impl From<LexError> for SyntaxError {
    fn from(e: LexError) -> Self {
        Self::Lex(e)
    }
}

impl From<ParseError> for SyntaxError {
    fn from(e: ParseError) -> Self {
        Self::Parse(e)
    }
}

const fn effect_of(kind: Tok) -> Option<ast::Effect> {
    match kind {
        Tok::Borrow => Some(ast::Effect::Borrow),
        Tok::BorrowMut => Some(ast::Effect::BorrowMut),
        Tok::Consume => Some(ast::Effect::Consume),
        _ => None,
    }
}

const fn emit_field_of(kind: Tok) -> Option<&'static str> {
    match kind {
        Tok::EmitType => Some("emit_type"),
        Tok::EmitAcquire => Some("emit_acquire"),
        Tok::EmitRelease => Some("emit_release"),
        Tok::EmitBorrow => Some("emit_borrow"),
        _ => None,
    }
}

/// Sorted, deduplicated keys that appear more than once — Python's
/// `tuple(sorted({k for k in seen if seen.count(k) > 1}))`.
fn dups_of(seen: &[String]) -> Vec<String> {
    let mut dups: Vec<String> = seen
        .iter()
        .filter(|k| seen.iter().filter(|x| x == k).count() > 1)
        .cloned()
        .collect();
    dups.sort();
    dups.dedup();
    dups
}

/// `int(tok.text)` — see the `IntLit` note in [`ast`]: a literal above
/// `u64::MAX` errors loudly instead of silently truncating (recorded
/// divergence from Python's arbitrary-precision `int`).
fn int_value(tok: &Token) -> Result<u64, ParseError> {
    tok.text.parse::<u64>().map_err(|_| {
        ParseError::new(
            "integer literal exceeds the u64 parity envelope (recorded divergence)",
            tok,
        )
    })
}

struct Parser {
    toks: Vec<Token>,
    pos: usize,
    /// Never reached (the lexer always appends EOF); satisfies the
    /// no-indexing discipline without a panic path.
    fallback: Token,
}

impl Parser {
    const fn new(toks: Vec<Token>) -> Self {
        Self {
            toks,
            pos: 0,
            fallback: Token {
                kind: Tok::Eof,
                text: String::new(),
                line: 1,
                col: 1,
            },
        }
    }

    // -- token helpers --------------------------------------------------------

    fn tok_at(&self, j: usize) -> &Token {
        let last = self.toks.len().saturating_sub(1);
        self.toks.get(j.min(last)).unwrap_or(&self.fallback)
    }

    fn cur(&self) -> &Token {
        self.tok_at(self.pos)
    }

    fn at(&self, kind: Tok) -> bool {
        self.cur().kind == kind
    }

    fn peek(&self) -> &Token {
        self.tok_at(self.pos.saturating_add(1))
    }

    fn bump(&mut self) {
        self.pos = self.pos.saturating_add(1);
    }

    fn eat(&mut self, kind: Tok) -> Result<Token, ParseError> {
        if self.cur().kind != kind {
            return Err(ParseError::new(
                &format!("expected {}", kind.python_name()),
                self.cur(),
            ));
        }
        let t = self.cur().clone();
        self.bump();
        Ok(t)
    }

    fn accept(&mut self, kind: Tok) -> Option<Token> {
        if self.cur().kind == kind {
            let t = self.cur().clone();
            self.bump();
            return Some(t);
        }
        None
    }

    fn reject_guard(&self) -> Result<(), ParseError> {
        if self.at(Tok::Rejected) {
            let t = self.cur();
            return Err(ParseError::new(
                &format!(
                    "'{}' is out of scope for the MVP — for/loop-style \
                     iteration and async are deliberately unsupported ('while' is \
                     supported; see README, 'Where it cheats')",
                    t.text
                ),
                t,
            ));
        }
        Ok(())
    }

    // -- entry ---------------------------------------------------------------

    fn parse_module(&mut self) -> Result<ast::Module, ParseError> {
        self.eat(Tok::Module)?;
        let name = self.eat(Tok::Ident)?.text;
        let mut module = ast::Module {
            name,
            resources: Vec::new(),
            externs: Vec::new(),
            functions: Vec::new(),
            policies: Vec::new(),
            lifetimes: Vec::new(),
        };
        while !self.at(Tok::Eof) {
            self.reject_guard()?;
            if self.at(Tok::Resource) {
                module.resources.push(self.parse_resource()?);
            } else if self.at(Tok::Extern) {
                module.externs.push(self.parse_extern()?);
            } else if self.at(Tok::Fn) {
                module.functions.push(self.parse_fn()?);
            } else if self.at(Tok::Policy) {
                module.policies.push(self.parse_policy()?);
            } else if self.at(Tok::Lifetime) {
                module.lifetimes.push(self.parse_lifetime()?);
            } else {
                return Err(ParseError::new(
                    "expected 'resource', 'extern', 'fn', 'policy' or 'lifetime'",
                    self.cur(),
                ));
            }
        }
        Ok(module)
    }

    fn parse_lifetime(&mut self) -> Result<ast::LifetimeDecl, ParseError> {
        let kw = self.eat(Tok::Lifetime)?;
        let name = self.eat(Tok::Ident)?.text;
        let longer: Option<String> = if self.accept(Tok::Lt).is_some() {
            // `lifetime Window < App;`
            Some(self.eat(Tok::Ident)?.text)
        } else {
            None
        };
        self.eat(Tok::Semi)?;
        Ok(ast::LifetimeDecl {
            name,
            longer,
            line: kw.line,
        })
    }

    // -- policies --------------------------------------------------------------

    fn parse_policy(&mut self) -> Result<ast::PolicyDecl, ParseError> {
        let kw = self.eat(Tok::Policy)?;
        let name = self.eat(Tok::Ident)?.text;
        self.eat(Tok::LBrace)?;
        let mut settings: ast::OrderedMap<ast::PolicyValue> = ast::OrderedMap::new();
        let mut seen: Vec<String> = Vec::new();
        while !self.at(Tok::RBrace) {
            let key = self.eat(Tok::Ident)?.text;
            self.eat(Tok::Eq)?;
            let value = self.policy_value()?;
            settings.insert(&key, value);
            self.eat(Tok::Semi)?;
            seen.push(key);
        }
        self.eat(Tok::RBrace)?;
        Ok(ast::PolicyDecl {
            name,
            settings,
            line: kw.line,
            dups: dups_of(&seen),
        })
    }

    /// A policy setting value: an int, or an identifier interpreted as a
    /// bool (true/false) or a bare keyword string (pool/forbidden/debug/...).
    fn policy_value(&mut self) -> Result<ast::PolicyValue, ParseError> {
        if self.at(Tok::Int) {
            let t = self.eat(Tok::Int)?;
            return Ok(ast::PolicyValue::Int(int_value(&t)?));
        }
        let word = self.eat(Tok::Ident)?.text;
        if word == "true" {
            return Ok(ast::PolicyValue::Bool(true));
        }
        if word == "false" {
            return Ok(ast::PolicyValue::Bool(false));
        }
        Ok(ast::PolicyValue::Word(word))
    }

    // -- resources --------------------------------------------------------------

    fn parse_resource(&mut self) -> Result<ast::ResourceDecl, ParseError> {
        let kw = self.eat(Tok::Resource)?;
        let name = self.eat(Tok::Ident)?.text;
        self.eat(Tok::LBrace)?;
        let mut members: Vec<ast::ResourceMember> = Vec::new();
        let mut emit: ast::OrderedMap<String> = ast::OrderedMap::new();
        let mut kind: Option<String> = None;
        while !self.at(Tok::RBrace) {
            if self.at(Tok::Acquire) {
                self.eat(Tok::Acquire)?;
                let m = self.eat(Tok::Ident)?;
                members.push(ast::ResourceMember {
                    role: ast::MemberRole::Acquire,
                    name: m.text,
                    line: m.line,
                });
            } else if self.at(Tok::Release) {
                self.eat(Tok::Release)?;
                let m = self.eat(Tok::Ident)?;
                members.push(ast::ResourceMember {
                    role: ast::MemberRole::Release,
                    name: m.text,
                    line: m.line,
                });
            } else if let Some(field) = emit_field_of(self.cur().kind) {
                self.bump();
                let val = self.eat(Tok::Str)?.text;
                emit.insert(field, val);
            } else if self.at(Tok::Ident) && self.cur().text == "kind" {
                // contextual keyword (not globally reserved): kind "subscription token"
                self.bump();
                kind = Some(self.eat(Tok::Str)?.text);
            } else {
                return Err(ParseError::new(
                    "expected 'acquire', 'release', 'kind' or an emit_* template",
                    self.cur(),
                ));
            }
        }
        self.eat(Tok::RBrace)?;
        Ok(ast::ResourceDecl {
            name,
            members,
            line: kw.line,
            emit_type: emit.get("emit_type").cloned(),
            emit_acquire: emit.get("emit_acquire").cloned(),
            emit_release: emit.get("emit_release").cloned(),
            emit_borrow: emit.get("emit_borrow").cloned(),
            kind,
        })
    }

    // -- externs ----------------------------------------------------------------

    fn parse_extern(&mut self) -> Result<ast::ExternDecl, ParseError> {
        let kw = self.eat(Tok::Extern)?;
        self.eat(Tok::Fn)?;
        let name = self.eat(Tok::Ident)?.text;
        self.eat(Tok::LParen)?;
        let mut params: Vec<ast::EffectParam> = Vec::new();
        if !self.at(Tok::RParen) {
            params.push(self.parse_eparam()?);
            while self.accept(Tok::Comma).is_some() {
                params.push(self.parse_eparam()?);
            }
        }
        self.eat(Tok::RParen)?;
        let ret: Option<ast::TypeRef> = if self.accept(Tok::Arrow).is_some() {
            Some(self.parse_type()?)
        } else {
            None
        };
        self.eat(Tok::Semi)?;
        Ok(ast::ExternDecl {
            name,
            params,
            ret,
            line: kw.line,
        })
    }

    fn parse_eparam(&mut self) -> Result<ast::EffectParam, ParseError> {
        let line = self.cur().line;
        if let Some(effect) = effect_of(self.cur().kind) {
            self.bump();
            let type_name = self.eat(Tok::Ident)?.text;
            return Ok(ast::EffectParam {
                effect,
                type_name,
                line,
            });
        }
        // no effect keyword -> plain by-value (e.g. int)
        let type_name = self.eat(Tok::Ident)?.text;
        Ok(ast::EffectParam {
            effect: ast::Effect::Plain,
            type_name,
            line,
        })
    }

    // -- functions ----------------------------------------------------------------

    fn parse_fn(&mut self) -> Result<ast::FnDecl, ParseError> {
        let kw = self.eat(Tok::Fn)?;
        let name = self.eat(Tok::Ident)?.text;
        self.eat(Tok::LParen)?;
        let mut params: Vec<ast::Param> = Vec::new();
        if !self.at(Tok::RParen) {
            params.push(self.parse_param()?);
            while self.accept(Tok::Comma).is_some() {
                params.push(self.parse_param()?);
            }
        }
        self.eat(Tok::RParen)?;
        let ret: Option<ast::TypeRef> = if self.accept(Tok::Arrow).is_some() {
            Some(self.parse_type()?)
        } else {
            None
        };
        // `fn F(...) lifetime ViewModel { }`
        let lifetime: Option<String> = if self.accept(Tok::Lifetime).is_some() {
            Some(self.eat(Tok::Ident)?.text)
        } else {
            None
        };
        let body = self.parse_block()?;
        Ok(ast::FnDecl {
            name,
            params,
            ret,
            body,
            line: kw.line,
            lifetime,
        })
    }

    fn parse_param(&mut self) -> Result<ast::Param, ParseError> {
        let nm = self.eat(Tok::Ident)?;
        self.eat(Tok::Colon)?;
        let ty = self.parse_type()?;
        // `bus: EventBus lifetime App`
        let lifetime: Option<String> = if self.accept(Tok::Lifetime).is_some() {
            Some(self.eat(Tok::Ident)?.text)
        } else {
            None
        };
        Ok(ast::Param {
            name: nm.text,
            ty,
            line: nm.line,
            lifetime,
        })
    }

    fn parse_type(&mut self) -> Result<ast::TypeRef, ParseError> {
        let line = self.cur().line;
        if self.accept(Tok::Amp).is_some() {
            let mutable = self.accept(Tok::Mut).is_some();
            let nm = self.eat(Tok::Ident)?;
            return Ok(ast::TypeRef {
                name: nm.text,
                borrowed: true,
                mutable,
                line,
            });
        }
        let nm = self.eat(Tok::Ident)?;
        Ok(ast::TypeRef {
            name: nm.text,
            borrowed: false,
            mutable: false,
            line,
        })
    }

    // -- statements ----------------------------------------------------------------

    fn parse_block(&mut self) -> Result<Vec<ast::Stmt>, ParseError> {
        self.eat(Tok::LBrace)?;
        let mut stmts: Vec<ast::Stmt> = Vec::new();
        while !self.at(Tok::RBrace) {
            self.reject_guard()?;
            stmts.push(self.parse_stmt()?);
        }
        self.eat(Tok::RBrace)?;
        Ok(stmts)
    }

    fn parse_stmt(&mut self) -> Result<ast::Stmt, ParseError> {
        self.reject_guard()?;
        if self.at(Tok::Let) {
            return Ok(ast::Stmt::Let(self.parse_let()?));
        }
        if self.at(Tok::Release) {
            return Ok(ast::Stmt::Release(self.parse_release()?));
        }
        if self.at(Tok::Use) {
            return Ok(ast::Stmt::Use(self.parse_use()?));
        }
        if self.at(Tok::Overspan) {
            return Ok(ast::Stmt::Overspan(self.parse_overspan()?));
        }
        if self.at(Tok::Borrow) || self.at(Tok::BorrowMut) {
            return Ok(ast::Stmt::BorrowBlock(self.parse_borrow()?));
        }
        if self.at(Tok::If) {
            return Ok(ast::Stmt::If(self.parse_if()?));
        }
        if self.at(Tok::While) {
            return Ok(ast::Stmt::While(self.parse_while()?));
        }
        if self.at(Tok::Return) {
            return Ok(ast::Stmt::Return(self.parse_return()?));
        }
        if self.at(Tok::Subscribe) {
            return Ok(ast::Stmt::Subscribe(self.parse_subscribe()?));
        }
        if self.at(Tok::Ident) && self.peek().kind == Tok::LParen {
            return Ok(ast::Stmt::Call(self.parse_call()?));
        }
        Err(ParseError::new("expected a statement", self.cur()))
    }

    fn parse_subscribe(&mut self) -> Result<ast::Subscribe, ParseError> {
        let kw = self.eat(Tok::Subscribe)?;
        // `self` and `to` are contextual here (not globally reserved words).
        let kw_self = self.eat(Tok::Ident)?;
        if kw_self.text != "self" {
            return Err(ParseError::new(
                "expected 'self' after 'subscribe'",
                &kw_self,
            ));
        }
        let kw_to = self.eat(Tok::Ident)?;
        if kw_to.text != "to" {
            return Err(ParseError::new(
                "expected 'to' in 'subscribe self to <source>'",
                &kw_to,
            ));
        }
        let source = self.eat(Tok::Ident)?.text;
        self.eat(Tok::Semi)?;
        Ok(ast::Subscribe {
            source,
            line: kw.line,
        })
    }

    fn parse_let(&mut self) -> Result<ast::Let, ParseError> {
        let kw = self.eat(Tok::Let)?;
        let nm = self.eat(Tok::Ident)?;
        self.eat(Tok::Eq)?;
        let rhs = self.parse_rhs()?;
        self.eat(Tok::Semi)?;
        Ok(ast::Let {
            name: nm.text,
            rhs,
            line: kw.line,
        })
    }

    fn parse_rhs(&mut self) -> Result<ast::Expr, ParseError> {
        if self.at(Tok::Acquire) {
            let kw = self.eat(Tok::Acquire)?;
            let resource = self.eat(Tok::Ident)?.text;
            self.eat(Tok::LParen)?;
            let args = self.parse_args()?;
            self.eat(Tok::RParen)?;
            return Ok(ast::Expr::Acquire(ast::Acquire {
                resource,
                args,
                line: kw.line,
            }));
        }
        if self.at(Tok::Move) {
            let kw = self.eat(Tok::Move)?;
            let v = self.eat(Tok::Ident)?;
            return Ok(ast::Expr::Move(ast::Move {
                var: v.text,
                line: kw.line,
            }));
        }
        // buffer intent:  Namespace "." mode "(" bargs? ")"   e.g. Buffer.scratch(...)
        if self.at(Tok::Ident) && self.peek().kind == Tok::Dot {
            return Ok(ast::Expr::BufferIntent(self.parse_buffer_intent()?));
        }
        self.parse_atom()
    }

    fn parse_buffer_intent(&mut self) -> Result<ast::BufferIntent, ParseError> {
        let ns = self.eat(Tok::Ident)?; // namespace, conventionally "Buffer"
        self.eat(Tok::Dot)?;
        let mode = self.eat(Tok::Ident)?.text;
        self.eat(Tok::LParen)?;
        let mut size: Option<ast::Expr> = None;
        let mut options: ast::OrderedMap<ast::Expr> = ast::OrderedMap::new();
        let mut seen: Vec<String> = Vec::new(); // option names in order (for dup detect)
        let mut first = true;
        if !self.at(Tok::RParen) {
            let (got, still_first) = self.buffer_arg(&mut options, &mut seen, first)?;
            size = got;
            first = still_first;
            while self.accept(Tok::Comma).is_some() {
                let (got, still_first) = self.buffer_arg(&mut options, &mut seen, first)?;
                first = still_first;
                if let Some(expr) = got {
                    size = Some(expr);
                }
            }
        }
        self.eat(Tok::RParen)?;
        Ok(ast::BufferIntent {
            mode,
            size: size.map(Box::new),
            options,
            line: ns.line,
            ns: ns.text,
            col: ns.col,
            dups: dups_of(&seen),
        })
    }

    /// Parse one buffer argument: a named option, or the leading positional
    /// size. Returns `(size_expr_or_None, still_first)`.
    fn buffer_arg(
        &mut self,
        options: &mut ast::OrderedMap<ast::Expr>,
        seen: &mut Vec<String>,
        first: bool,
    ) -> Result<(Option<ast::Expr>, bool), ParseError> {
        // named option: IDENT "=" atom. `policy` is a keyword token elsewhere but
        // is also a valid option name here, so accept it too.
        if (self.at(Tok::Ident) || self.at(Tok::Policy)) && self.peek().kind == Tok::Eq {
            let key = self.cur().text.clone();
            self.bump();
            self.eat(Tok::Eq)?;
            let value = self.parse_atom()?;
            options.insert(&key, value);
            seen.push(key);
            return Ok((None, first));
        }
        let atom = self.parse_atom()?;
        if !first {
            return Err(ParseError::new(
                "only the leading size may be positional in a \
                 buffer intent; later arguments must be named",
                self.cur(),
            ));
        }
        Ok((Some(atom), false))
    }

    fn parse_args(&mut self) -> Result<Vec<ast::Expr>, ParseError> {
        let mut args: Vec<ast::Expr> = Vec::new();
        if !self.at(Tok::RParen) {
            args.push(self.parse_atom()?);
            while self.accept(Tok::Comma).is_some() {
                args.push(self.parse_atom()?);
            }
        }
        Ok(args)
    }

    fn parse_atom(&mut self) -> Result<ast::Expr, ParseError> {
        if self.at(Tok::Int) {
            let t = self.eat(Tok::Int)?;
            return Ok(ast::Expr::IntLit(ast::IntLit {
                value: int_value(&t)?,
                line: t.line,
            }));
        }
        let t = self.eat(Tok::Ident)?;
        Ok(ast::Expr::VarRef(ast::VarRef {
            name: t.text,
            line: t.line,
        }))
    }

    fn parse_release(&mut self) -> Result<ast::Release, ParseError> {
        let kw = self.eat(Tok::Release)?;
        let v = self.eat(Tok::Ident)?;
        self.eat(Tok::Semi)?;
        Ok(ast::Release {
            var: v.text,
            line: kw.line,
        })
    }

    fn parse_use(&mut self) -> Result<ast::Use, ParseError> {
        let kw = self.eat(Tok::Use)?;
        let v = self.eat(Tok::Ident)?;
        self.eat(Tok::Semi)?;
        Ok(ast::Use {
            var: v.text,
            line: kw.line,
        })
    }

    fn parse_overspan(&mut self) -> Result<ast::Overspan, ParseError> {
        let kw = self.eat(Tok::Overspan)?;
        let v = self.eat(Tok::Ident)?;
        self.eat(Tok::Semi)?;
        Ok(ast::Overspan {
            var: v.text,
            line: kw.line,
        })
    }

    fn parse_call(&mut self) -> Result<ast::Call, ParseError> {
        let nm = self.eat(Tok::Ident)?;
        self.eat(Tok::LParen)?;
        let args = self.parse_args()?;
        self.eat(Tok::RParen)?;
        self.eat(Tok::Semi)?;
        Ok(ast::Call {
            callee: nm.text,
            args,
            line: nm.line,
        })
    }

    fn parse_borrow(&mut self) -> Result<ast::BorrowBlock, ParseError> {
        let (kw, kind) = if self.at(Tok::BorrowMut) {
            (self.eat(Tok::BorrowMut)?, ast::BorrowKind::Mut)
        } else {
            (self.eat(Tok::Borrow)?, ast::BorrowKind::Shared)
        };
        let owner = self.eat(Tok::Ident)?.text;
        self.eat(Tok::As)?;
        let binding = self.eat(Tok::Ident)?.text;
        let body = self.parse_block()?;
        Ok(ast::BorrowBlock {
            owner,
            binding,
            kind,
            body,
            line: kw.line,
        })
    }

    /// The `( ... )` condition of `if`/`while`: opaque token-join text, with
    /// paren-depth tracking. Mirrors both Python loops (they differ only in
    /// the error message).
    fn parse_cond(&mut self, unterminated_msg: &str) -> Result<String, ParseError> {
        self.eat(Tok::LParen)?;
        let mut cond_parts: Vec<String> = Vec::new();
        let mut depth: u32 = 1;
        loop {
            if self.at(Tok::Eof) {
                return Err(ParseError::new(unterminated_msg, self.cur()));
            }
            if self.at(Tok::LParen) {
                depth = depth.saturating_add(1);
            } else if self.at(Tok::RParen) {
                depth = depth.saturating_sub(1);
                if depth == 0 {
                    self.eat(Tok::RParen)?;
                    break;
                }
            }
            cond_parts.push(self.cur().text.clone());
            self.bump();
        }
        Ok(cond_parts.join(" "))
    }

    fn parse_if(&mut self) -> Result<ast::If, ParseError> {
        let kw = self.eat(Tok::If)?;
        let cond_text = self.parse_cond("unterminated if-condition")?;
        let then_body = self.parse_block()?;
        let else_body: Vec<ast::Stmt> = if self.accept(Tok::Else).is_some() {
            self.parse_block()?
        } else {
            Vec::new()
        };
        Ok(ast::If {
            cond_text,
            then_body,
            else_body,
            line: kw.line,
        })
    }

    fn parse_while(&mut self) -> Result<ast::While, ParseError> {
        let kw = self.eat(Tok::While)?;
        let cond_text = self.parse_cond("unterminated while-condition")?;
        let body = self.parse_block()?;
        Ok(ast::While {
            cond_text,
            body,
            line: kw.line,
        })
    }

    fn parse_return(&mut self) -> Result<ast::Return, ParseError> {
        let kw = self.eat(Tok::Return)?;
        let var: Option<String> = if self.at(Tok::Ident) {
            Some(self.eat(Tok::Ident)?.text)
        } else {
            None
        };
        self.eat(Tok::Semi)?;
        Ok(ast::Return { var, line: kw.line })
    }
}

/// Parse a whole source text into a [`ast::Module`] — Python's
/// `parser.parse(src)`.
///
/// # Errors
/// [`SyntaxError::Lex`] or [`SyntaxError::Parse`], each displaying exactly
/// like the corresponding Python exception's `str()`.
pub fn parse(src: &str) -> Result<ast::Module, SyntaxError> {
    let toks = lex(src)?;
    Ok(Parser::new(toks).parse_module()?)
}

#[cfg(test)]
#[allow(clippy::panic, clippy::expect_used, clippy::unwrap_used)]
mod tests {
    //! Structure the parity digest can't see: Python-dict semantics of the
    //! option/setting maps, dup detection, emit-template last-wins, policy
    //! value typing, and the recorded u64 divergence. The cross-language
    //! accept/reject + error-text corpus lives in `tests/parity.rs`.

    use super::parse;
    use crate::ast;

    fn module(src: &str) -> ast::Module {
        parse(src).expect("test source must parse")
    }

    #[test]
    fn buffer_intent_options_keep_first_position_last_value() {
        let m = module(
            "module m fn f() { let x = Buffer.scratch(64, clear = true, policy = Fast, clear = false); }",
        );
        let f = m.functions.first().expect("one fn");
        let ast::Stmt::Let(let_stmt) = f.body.first().expect("one stmt") else {
            panic!("expected let");
        };
        let ast::Expr::BufferIntent(bi) = &let_stmt.rhs else {
            panic!("expected buffer intent");
        };
        assert_eq!(bi.ns, "Buffer");
        assert_eq!(bi.mode, "scratch");
        assert!(matches!(
            bi.size.as_deref(),
            Some(ast::Expr::IntLit(ast::IntLit { value: 64, .. }))
        ));
        // Python dict: duplicate key overwrites in place — first-appearance
        // order, last value; `seen` still records the duplicate.
        let keys: Vec<&str> = bi.options.iter().map(|(k, _)| k).collect();
        assert_eq!(keys, ["clear", "policy"]);
        assert!(matches!(
            bi.options.get("clear"),
            Some(ast::Expr::VarRef(v)) if v.name == "false"
        ));
        assert_eq!(bi.dups, ["clear"]);
    }

    #[test]
    fn policy_values_and_dups() {
        let m =
            module("module m policy P { a = 1; b = true; c = false; d = pool; b = false; a = 2; }");
        let p = m.policies.first().expect("one policy");
        assert_eq!(p.settings.get("a"), Some(&ast::PolicyValue::Int(2)));
        assert_eq!(p.settings.get("b"), Some(&ast::PolicyValue::Bool(false)));
        assert_eq!(p.settings.get("c"), Some(&ast::PolicyValue::Bool(false)));
        assert_eq!(
            p.settings.get("d"),
            Some(&ast::PolicyValue::Word("pool".to_owned()))
        );
        assert_eq!(p.dups, ["a", "b"]); // sorted, deduplicated
    }

    #[test]
    fn resource_emit_templates_last_wins_and_kind() {
        let m = module(
            "module m resource R { acquire open release close emit_type \"a\" emit_type \"b\" kind \"timer\" }",
        );
        let r = m.resources.first().expect("one resource");
        assert_eq!(r.emit_type.as_deref(), Some("b"));
        assert_eq!(r.emit_acquire, None);
        assert_eq!(r.kind.as_deref(), Some("timer"));
        assert_eq!(r.members.len(), 2);
        assert!(matches!(
            r.members.first(),
            Some(ast::ResourceMember {
                role: ast::MemberRole::Acquire,
                ..
            })
        ));
    }

    #[test]
    fn extern_effects_map_one_to_one() {
        let m = module("module m extern fn F(borrow A, borrow_mut B, consume C, int) -> &Buffer;");
        let e = m.externs.first().expect("one extern");
        let effects: Vec<ast::Effect> = e.params.iter().map(|p| p.effect).collect();
        assert_eq!(
            effects,
            [
                ast::Effect::Borrow,
                ast::Effect::BorrowMut,
                ast::Effect::Consume,
                ast::Effect::Plain
            ]
        );
        let ret = e.ret.as_ref().expect("return type");
        assert!(ret.borrowed && !ret.mutable);
    }

    #[test]
    fn int_literal_beyond_u64_errors_loudly_recorded_divergence() {
        // Python's bignum accepts this; the Rust port refuses instead of
        // truncating so the oracle would flag the divergence immediately.
        let err = parse("module m fn f() { let x = 99999999999999999999; }")
            .expect_err("must not truncate");
        assert!(err.to_string().contains("u64 parity envelope"));
    }
}
