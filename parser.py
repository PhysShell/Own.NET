"""
Recursive-descent parser for OwnLang.

Grammar (informal):

  module      := "module" IDENT item*
  item        := resource | extern | fn
  resource    := "resource" IDENT "{" rmember* "}"
  rmember     := ("acquire" | "release") IDENT
               | ("emit_type"|"emit_acquire"|"emit_release"|"emit_borrow") STRING
  extern      := "extern" "fn" IDENT "(" eparams? ")" ("->" type)? ";"
  eparams     := eparam ("," eparam)*
  eparam      := ("borrow" | "borrow_mut" | "consume")? IDENT      // IDENT = type name
  fn          := "fn" IDENT "(" params? ")" ("->" type)? block
  params      := param ("," param)*
  param       := IDENT ":" type
  type        := "&" "mut"? IDENT | IDENT
  block       := "{" stmt* "}"
  stmt        := let | release | use | call | borrow | if | return
  let         := "let" IDENT "=" rhs ";"
  rhs         := "acquire" IDENT "(" args? ")" | "move" IDENT | IDENT | INT
  release     := "release" IDENT ";"
  use         := "use" IDENT ";"
  call        := IDENT "(" args? ")" ";"
  borrow      := ("borrow" | "borrow_mut") IDENT "as" IDENT block
  if          := "if" "(" cond ")" block ("else" block)?
  return      := "return" IDENT? ";"
  args        := atom ("," atom)*
  atom        := INT | IDENT
"""

from __future__ import annotations

from .lexer import Tok, Token, lex
from . import ast_nodes as A


class ParseError(Exception):
    def __init__(self, msg: str, tok: Token):
        super().__init__(f"{tok.line}:{tok.col}: {msg} (got {tok.kind.name} {tok.text!r})")
        self.line = tok.line
        self.col = tok.col


_EFFECT_TOK = {
    Tok.BORROW: A.Effect.BORROW,
    Tok.BORROW_MUT: A.Effect.BORROW_MUT,
    Tok.CONSUME: A.Effect.CONSUME,
}

_EMIT_TOK = {
    Tok.EMIT_TYPE: "emit_type",
    Tok.EMIT_ACQUIRE: "emit_acquire",
    Tok.EMIT_RELEASE: "emit_release",
    Tok.EMIT_BORROW: "emit_borrow",
}


class Parser:
    def __init__(self, toks: list[Token]):
        self.toks = toks
        self.pos = 0

    # -- token helpers ------------------------------------------------------

    @property
    def cur(self) -> Token:
        return self.toks[self.pos]

    def at(self, kind: Tok) -> bool:
        return self.cur.kind == kind

    def peek(self, k: int = 1) -> Token:
        j = min(self.pos + k, len(self.toks) - 1)
        return self.toks[j]

    def eat(self, kind: Tok) -> Token:
        if self.cur.kind != kind:
            raise ParseError(f"expected {kind.name}", self.cur)
        t = self.cur
        self.pos += 1
        return t

    def accept(self, kind: Tok) -> Token | None:
        if self.cur.kind == kind:
            t = self.cur
            self.pos += 1
            return t
        return None

    def _reject_guard(self) -> None:
        if self.at(Tok.REJECTED):
            t = self.cur
            raise ParseError(
                f"'{t.text}' is out of scope for the MVP — loops and async are "
                f"deliberately unsupported (see README, 'Where it cheats')",
                t,
            )

    # -- entry --------------------------------------------------------------

    def parse_module(self) -> A.Module:
        self.eat(Tok.MODULE)
        name = self.eat(Tok.IDENT).text
        mod = A.Module(name=name)
        while not self.at(Tok.EOF):
            self._reject_guard()
            if self.at(Tok.RESOURCE):
                mod.resources.append(self.parse_resource())
            elif self.at(Tok.EXTERN):
                mod.externs.append(self.parse_extern())
            elif self.at(Tok.FN):
                mod.functions.append(self.parse_fn())
            else:
                raise ParseError("expected 'resource', 'extern' or 'fn'", self.cur)
        return mod

    # -- resources ----------------------------------------------------------

    def parse_resource(self) -> A.ResourceDecl:
        kw = self.eat(Tok.RESOURCE)
        name = self.eat(Tok.IDENT).text
        self.eat(Tok.LBRACE)
        members: list[A.ResourceMember] = []
        emit: dict[str, str] = {}
        while not self.at(Tok.RBRACE):
            if self.at(Tok.ACQUIRE):
                self.eat(Tok.ACQUIRE)
                m = self.eat(Tok.IDENT)
                members.append(A.ResourceMember("acquire", m.text, m.line))
            elif self.at(Tok.RELEASE):
                self.eat(Tok.RELEASE)
                m = self.eat(Tok.IDENT)
                members.append(A.ResourceMember("release", m.text, m.line))
            elif self.cur.kind in _EMIT_TOK:
                field = _EMIT_TOK[self.cur.kind]
                self.pos += 1
                val = self.eat(Tok.STRING).text
                emit[field] = val
            else:
                raise ParseError("expected 'acquire', 'release' or an emit_* template", self.cur)
        self.eat(Tok.RBRACE)
        return A.ResourceDecl(
            name=name, members=members, line=kw.line,
            emit_type=emit.get("emit_type"),
            emit_acquire=emit.get("emit_acquire"),
            emit_release=emit.get("emit_release"),
            emit_borrow=emit.get("emit_borrow"),
        )

    # -- externs ------------------------------------------------------------

    def parse_extern(self) -> A.ExternDecl:
        kw = self.eat(Tok.EXTERN)
        self.eat(Tok.FN)
        name = self.eat(Tok.IDENT).text
        self.eat(Tok.LPAREN)
        params: list[A.EffectParam] = []
        if not self.at(Tok.RPAREN):
            params.append(self.parse_eparam())
            while self.accept(Tok.COMMA):
                params.append(self.parse_eparam())
        self.eat(Tok.RPAREN)
        ret: A.TypeRef | None = None
        if self.accept(Tok.ARROW):
            ret = self.parse_type()
        self.eat(Tok.SEMI)
        return A.ExternDecl(name=name, params=params, ret=ret, line=kw.line)

    def parse_eparam(self) -> A.EffectParam:
        line = self.cur.line
        if self.cur.kind in _EFFECT_TOK:
            eff = _EFFECT_TOK[self.cur.kind]
            self.pos += 1
            tyname = self.eat(Tok.IDENT).text
            return A.EffectParam(effect=eff, type_name=tyname, line=line)
        # no effect keyword -> plain by-value (e.g. int)
        tyname = self.eat(Tok.IDENT).text
        return A.EffectParam(effect=A.Effect.PLAIN, type_name=tyname, line=line)

    # -- functions ----------------------------------------------------------

    def parse_fn(self) -> A.FnDecl:
        kw = self.eat(Tok.FN)
        name = self.eat(Tok.IDENT).text
        self.eat(Tok.LPAREN)
        params: list[A.Param] = []
        if not self.at(Tok.RPAREN):
            params.append(self.parse_param())
            while self.accept(Tok.COMMA):
                params.append(self.parse_param())
        self.eat(Tok.RPAREN)
        ret: A.TypeRef | None = None
        if self.accept(Tok.ARROW):
            ret = self.parse_type()
        body = self.parse_block()
        return A.FnDecl(name=name, params=params, ret=ret, body=body, line=kw.line)

    def parse_param(self) -> A.Param:
        nm = self.eat(Tok.IDENT)
        self.eat(Tok.COLON)
        ty = self.parse_type()
        return A.Param(name=nm.text, type=ty, line=nm.line)

    def parse_type(self) -> A.TypeRef:
        line = self.cur.line
        if self.accept(Tok.AMP):
            mutable = self.accept(Tok.MUT) is not None
            nm = self.eat(Tok.IDENT)
            return A.TypeRef(name=nm.text, borrowed=True, mutable=mutable, line=line)
        nm = self.eat(Tok.IDENT)
        return A.TypeRef(name=nm.text, borrowed=False, mutable=False, line=line)

    # -- statements ---------------------------------------------------------

    def parse_block(self) -> list[A.Stmt]:
        self.eat(Tok.LBRACE)
        stmts: list[A.Stmt] = []
        while not self.at(Tok.RBRACE):
            self._reject_guard()
            stmts.append(self.parse_stmt())
        self.eat(Tok.RBRACE)
        return stmts

    def parse_stmt(self) -> A.Stmt:
        self._reject_guard()
        if self.at(Tok.LET):
            return self.parse_let()
        if self.at(Tok.RELEASE):
            return self.parse_release()
        if self.at(Tok.USE):
            return self.parse_use()
        if self.at(Tok.BORROW) or self.at(Tok.BORROW_MUT):
            return self.parse_borrow()
        if self.at(Tok.IF):
            return self.parse_if()
        if self.at(Tok.RETURN):
            return self.parse_return()
        if self.at(Tok.IDENT) and self.peek().kind == Tok.LPAREN:
            return self.parse_call()
        raise ParseError("expected a statement", self.cur)

    def parse_let(self) -> A.Let:
        kw = self.eat(Tok.LET)
        nm = self.eat(Tok.IDENT)
        self.eat(Tok.EQ)
        rhs = self.parse_rhs()
        self.eat(Tok.SEMI)
        return A.Let(name=nm.text, rhs=rhs, line=kw.line)

    def parse_rhs(self) -> A.Expr:
        if self.at(Tok.ACQUIRE):
            kw = self.eat(Tok.ACQUIRE)
            res = self.eat(Tok.IDENT).text
            self.eat(Tok.LPAREN)
            args = self.parse_args()
            self.eat(Tok.RPAREN)
            return A.Acquire(resource=res, args=args, line=kw.line)
        if self.at(Tok.MOVE):
            kw = self.eat(Tok.MOVE)
            v = self.eat(Tok.IDENT)
            return A.Move(var=v.text, line=kw.line)
        return self.parse_atom()

    def parse_args(self) -> list[A.Expr]:
        args: list[A.Expr] = []
        if not self.at(Tok.RPAREN):
            args.append(self.parse_atom())
            while self.accept(Tok.COMMA):
                args.append(self.parse_atom())
        return args

    def parse_atom(self) -> A.Expr:
        if self.at(Tok.INT):
            t = self.eat(Tok.INT)
            return A.IntLit(value=int(t.text), line=t.line)
        t = self.eat(Tok.IDENT)
        return A.VarRef(name=t.text, line=t.line)

    def parse_release(self) -> A.Release:
        kw = self.eat(Tok.RELEASE)
        v = self.eat(Tok.IDENT)
        self.eat(Tok.SEMI)
        return A.Release(var=v.text, line=kw.line)

    def parse_use(self) -> A.Use:
        kw = self.eat(Tok.USE)
        v = self.eat(Tok.IDENT)
        self.eat(Tok.SEMI)
        return A.Use(var=v.text, line=kw.line)

    def parse_call(self) -> A.Call:
        nm = self.eat(Tok.IDENT)
        self.eat(Tok.LPAREN)
        args = self.parse_args()
        self.eat(Tok.RPAREN)
        self.eat(Tok.SEMI)
        return A.Call(callee=nm.text, args=args, line=nm.line)

    def parse_borrow(self) -> A.BorrowBlock:
        if self.at(Tok.BORROW_MUT):
            kw = self.eat(Tok.BORROW_MUT)
            kind = A.BorrowKind.MUT
        else:
            kw = self.eat(Tok.BORROW)
            kind = A.BorrowKind.SHARED
        owner = self.eat(Tok.IDENT).text
        self.eat(Tok.AS)
        binding = self.eat(Tok.IDENT).text
        body = self.parse_block()
        return A.BorrowBlock(owner=owner, binding=binding, kind=kind, body=body, line=kw.line)

    def parse_if(self) -> A.If:
        kw = self.eat(Tok.IF)
        self.eat(Tok.LPAREN)
        cond_parts: list[str] = []
        depth = 1
        while True:
            if self.at(Tok.EOF):
                raise ParseError("unterminated if-condition", self.cur)
            if self.at(Tok.LPAREN):
                depth += 1
            elif self.at(Tok.RPAREN):
                depth -= 1
                if depth == 0:
                    self.eat(Tok.RPAREN)
                    break
            cond_parts.append(self.cur.text)
            self.pos += 1
        then_body = self.parse_block()
        else_body: list[A.Stmt] = []
        if self.accept(Tok.ELSE):
            else_body = self.parse_block()
        return A.If(cond_text=" ".join(cond_parts), then_body=then_body,
                    else_body=else_body, line=kw.line)

    def parse_return(self) -> A.Return:
        kw = self.eat(Tok.RETURN)
        var: str | None = None
        if self.at(Tok.IDENT):
            var = self.eat(Tok.IDENT).text
        self.eat(Tok.SEMI)
        return A.Return(var=var, line=kw.line)


def parse(src: str) -> A.Module:
    return Parser(lex(src)).parse_module()
