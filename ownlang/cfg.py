"""
Two things live here:

1. A scope resolver that assigns every name reference a unique Symbol and
   classifies it (OWNED resource / BORROW / PLAIN). It reports flow-INsensitive
   errors: undefined names, shadowing, releasing/moving/borrowing a non-owned
   value, copying an owned resource without `move`, returning a borrow (escape),
   and — new in this revision — calls to undeclared functions and arity
   mismatches. Unknown calls are a hard error: every call must resolve to a
   declared `extern fn` or local `fn`, so the checker cannot be tunnelled
   through an opaque C# call.

2. A control-flow graph: real basic blocks with successor edges, branches at
   `if`, merge nodes, and terminal blocks at `return`. Borrow scopes lower to
   explicit BORROW_START / BORROW_END instructions; calls lower to an Invoke
   instruction carrying the resolved per-argument ownership effect. A `while`
   lowers to a header block (the test) with a back-edge from the body exit, so
   the CFG may contain cycles; the analysis converges over them with a worklist
   fixpoint (analysis.py) instead of a single topological pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import assert_never

from . import ast_nodes as A
from .ast_nodes import Effect
from .buffers import MODE_NAMES, BufferInfo, Policy
from .buffers import resolve as resolve_buffer
from .diagnostics import Diagnostic

# ---------------------------------------------------------------------------
# Symbols & kinds
# ---------------------------------------------------------------------------


class Kind(Enum):
    OWNED = auto()    # a linear resource: must be consumed exactly once
    BORROW = auto()   # a borrow binding or a borrowed (&T / &mut T) parameter
    PLAIN = auto()    # int, or a copy of a borrow/int — not lifetime-tracked


@dataclass(eq=False)
class Symbol:
    name: str
    kind: Kind
    def_line: int
    # for BORROW symbols that are borrowed parameters, this is True (live for
    # the whole function body); plain borrow-block bindings start not-live and
    # are turned live by BORROW_START.
    is_param_borrow: bool = False
    # for BORROW symbols: True if it is a mutable borrow (&mut / borrow_mut),
    # False if shared (&T / borrow). None for non-borrow symbols.
    borrow_is_mut: bool | None = None
    # for OWNED buffer symbols: the resolved storage policy. None for ordinary
    # `acquire`d resources. A stack-backed buffer (info.stack_backed) must not
    # escape the function.
    buffer: BufferInfo | None = None
    # the declared/inferred type name (e.g. "int", "bool", a resource name), so a
    # buffer size can be required to be an integer. None when unknown.
    type_name: str | None = None
    # the resource's optional human "kind" (e.g. "subscription token"), copied
    # from its ResourceDecl at acquire / on an owned parameter. Surfaced on
    # diagnostics as `[resource: <kind>]`; None for plain values and untagged
    # resources.
    resource_kind: str | None = None
    # a stable identity for the originating buffer (name#line). Set when a buffer
    # is acquired and inherited across `move`, so a diagnostic about any alias can
    # be attributed to the right buffer in the report (distinct from a same-named
    # buffer in a sibling scope).
    origin: str | None = None

    def __repr__(self) -> str:
        return f"<{self.name}:{self.kind.name}>"


# ---------------------------------------------------------------------------
# CFG instructions
# ---------------------------------------------------------------------------


@dataclass
class Acquire:
    sym: Symbol
    resource: str
    line: int


@dataclass
class AcquireBuffer:
    """Acquire an owned buffer with an explicit storage policy. Carries the
    resolved BufferInfo so analysis can apply escape rules and codegen can emit
    the right backend (stackalloc / ArrayPool / NativeMemory) plus its logging."""
    sym: Symbol
    info: BufferInfo
    line: int


@dataclass
class MoveInto:
    dst: Symbol
    src: Symbol
    line: int


@dataclass
class Release:
    sym: Symbol
    line: int


@dataclass
class Use:
    sym: Symbol
    line: int


@dataclass
class Invoke:
    """A resolved call. `args` pairs each argument's resolved Symbol (or None
    for a literal / unresolved) with the ownership Effect the callee applies."""
    callee: str
    args: list[tuple[Symbol | None, Effect]]
    line: int


@dataclass
class BorrowStart:
    owner: Symbol
    binding: Symbol
    mut: bool
    line: int


@dataclass
class BorrowEnd:
    owner: Symbol
    binding: Symbol
    mut: bool
    line: int


@dataclass
class Return:
    sym: Symbol | None
    line: int


Instr = (Acquire | AcquireBuffer | MoveInto | Release | Use | Invoke
         | BorrowStart | BorrowEnd | Return)


# ---------------------------------------------------------------------------
# Basic blocks
# ---------------------------------------------------------------------------


@dataclass
class Block:
    id: int
    instrs: list[Instr] = field(default_factory=list)
    succ: list[int] = field(default_factory=list)
    label: str = ""


@dataclass
class CFG:
    fn_name: str
    blocks: list[Block]
    entry: int
    params: list[Symbol]
    has_return_type: bool

    def preds(self) -> dict[int, list[int]]:
        p: dict[int, list[int]] = {b.id: [] for b in self.blocks}
        for b in self.blocks:
            for s in b.succ:
                p[s].append(b.id)
        return p


# ---------------------------------------------------------------------------
# Module-level signature table
# ---------------------------------------------------------------------------


@dataclass
class Signature:
    name: str
    effects: list[Effect]   # one Effect per positional parameter


def collect_signatures(mod: A.Module) -> dict[str, Signature]:
    sigs: dict[str, Signature] = {}
    for e in mod.externs:
        sigs[e.name] = Signature(e.name, [p.effect for p in e.params])
    for fn in mod.functions:
        effects: list[Effect] = []
        for p in fn.params:
            if p.type.borrowed and p.type.mutable:
                effects.append(Effect.BORROW_MUT)
            elif p.type.borrowed:
                effects.append(Effect.BORROW)
            elif p.type.name in {r.name for r in mod.resources}:
                effects.append(Effect.CONSUME)
            else:
                effects.append(Effect.PLAIN)
        sigs[fn.name] = Signature(fn.name, effects)
    return sigs


# ---------------------------------------------------------------------------
# Resolver + lowering (single pass over the structured AST)
# ---------------------------------------------------------------------------


class _Builder:
    def __init__(self, fn: A.FnDecl, resource_names: set[str],
                 signatures: dict[str, Signature],
                 policies: dict[str, Policy] | None = None,
                 resource_kinds: dict[str, str] | None = None):
        self.fn = fn
        self.resource_names = resource_names
        self.signatures = signatures
        self.policies = policies or {}
        self.resource_kinds = resource_kinds or {}
        self.diags: list[Diagnostic] = []
        self.blocks: list[Block] = []
        self.scopes: list[dict[str, Symbol]] = []
        self.params: list[Symbol] = []

    # -- scope helpers ------------------------------------------------------

    def push_scope(self) -> None:
        self.scopes.append({})

    def pop_scope(self) -> None:
        self.scopes.pop()

    def declare(self, name: str, kind: Kind, line: int, *,
                is_param_borrow: bool = False,
                borrow_is_mut: bool | None = None) -> Symbol:
        for sc in self.scopes:
            if name in sc:
                self.diags.append(Diagnostic(
                    "OWN031", f"'{name}' is already defined in an enclosing scope", line))
                break
        sym = Symbol(name, kind, line, is_param_borrow=is_param_borrow,
                     borrow_is_mut=borrow_is_mut)
        self.scopes[-1][name] = sym
        return sym

    def lookup(self, name: str, line: int) -> Symbol | None:
        for sc in reversed(self.scopes):
            if name in sc:
                return sc[name]
        self.diags.append(Diagnostic("OWN030", f"undefined name '{name}'", line))
        return None

    # -- blocks -------------------------------------------------------------

    def new_block(self, label: str = "") -> Block:
        b = Block(id=len(self.blocks), label=label)
        self.blocks.append(b)
        return b

    # -- build --------------------------------------------------------------

    def build(self) -> CFG:
        self.push_scope()
        for p in self.fn.params:
            if p.type.borrowed:
                sym = self.declare(p.name, Kind.BORROW, p.line,
                                   is_param_borrow=True, borrow_is_mut=p.type.mutable)
            elif p.type.name in self.resource_names:
                sym = self.declare(p.name, Kind.OWNED, p.line)
            else:
                sym = self.declare(p.name, Kind.PLAIN, p.line)
            sym.type_name = p.type.name
            sym.resource_kind = self.resource_kinds.get(p.type.name)
            self.params.append(sym)

        entry = self.new_block("entry")
        exit_block = self.lower_seq(self.fn.body, entry)
        if self.fn.ret is not None and exit_block is not None:
            self.diags.append(Diagnostic(
                "OWN033",
                f"function '{self.fn.name}' has return type "
                f"'{self.fn.ret.name}' but can reach the end without returning",
                self.fn.line))
        self.pop_scope()
        return CFG(
            fn_name=self.fn.name,
            blocks=self.blocks,
            entry=entry.id,
            params=self.params,
            has_return_type=self.fn.ret is not None,
        )

    def lower_seq(self, stmts: list[A.Stmt], cur: Block) -> Block | None:
        node: Block | None = cur
        for st in stmts:
            if node is None:
                return None
            node = self.lower_stmt(st, node)
        return node

    def lower_stmt(self, st: A.Stmt, cur: Block) -> Block | None:
        if isinstance(st, A.Let):
            return self.lower_let(st, cur)
        if isinstance(st, A.Release):
            sym = self.lookup(st.var, st.line)
            if sym is not None:
                if sym.kind != Kind.OWNED:
                    self.diags.append(Diagnostic(
                        "OWN034",
                        f"cannot release '{st.var}': it is not an owned resource "
                        f"({sym.kind.name.lower()})", st.line))
                else:
                    cur.instrs.append(Release(sym, st.line))
            return cur
        if isinstance(st, A.Use):
            sym = self.lookup(st.var, st.line)
            if sym is not None:
                cur.instrs.append(Use(sym, st.line))
            return cur
        if isinstance(st, A.Call):
            return self.lower_call(st, cur)
        if isinstance(st, A.BorrowBlock):
            return self.lower_borrow(st, cur)
        if isinstance(st, A.If):
            return self.lower_if(st, cur)
        if isinstance(st, A.While):
            return self.lower_while(st, cur)
        if isinstance(st, A.Return):
            return self.lower_return(st, cur)
        if isinstance(st, A.Subscribe):
            # a `subscribe self to X` is a lifetime-region fact, handled by the
            # separate lifetime analysis (ownlang.lifetimes); it does not move,
            # release, or borrow anything, so it is a no-op for the loans/
            # permissions flow.
            return cur
        assert_never(st)

    def lower_let(self, st: A.Let, cur: Block) -> Block:
        rhs = st.rhs
        if isinstance(rhs, A.Acquire):
            if rhs.resource not in self.resource_names:
                self.diags.append(Diagnostic(
                    "OWN030", f"undefined resource '{rhs.resource}'", rhs.line))
            sym = self.declare(st.name, Kind.OWNED, st.line)
            sym.type_name = rhs.resource
            sym.resource_kind = self.resource_kinds.get(rhs.resource)
            # a stable identity (name#line) so a diagnostic about this resource
            # can be attributed structurally — by Diagnostic.subject — instead of
            # by scraping the name out of the human message. The OwnIR bridge keys
            # its C#-location map off exactly this (see ownir.check_facts).
            sym.origin = f"{st.name}#{rhs.line}"
            cur.instrs.append(Acquire(sym, rhs.resource, st.line))
            return cur
        if isinstance(rhs, A.BufferIntent):
            return self.lower_buffer(st, rhs, cur)
        if isinstance(rhs, A.Move):
            src = self.lookup(rhs.var, rhs.line)
            if src is not None and src.kind != Kind.OWNED:
                self.diags.append(Diagnostic(
                    "OWN034",
                    f"cannot move '{rhs.var}': it is not an owned resource", rhs.line))
                src = None
            dst = self.declare(st.name, Kind.OWNED, st.line)
            if src is not None:
                # a moved buffer keeps its storage policy AND its origin identity:
                # a stack-backed buffer is still stack-backed after `move` (escape
                # rules carry over), and diagnostics on the alias attribute to the
                # original buffer in the report.
                dst.buffer = src.buffer
                dst.origin = src.origin
                dst.type_name = src.type_name   # the moved value keeps its type
                dst.resource_kind = src.resource_kind  # ...and its kind tag
                cur.instrs.append(MoveInto(dst, src, st.line))
            return cur
        if isinstance(rhs, A.VarRef):
            src = self.lookup(rhs.name, rhs.line)
            if src is not None and src.kind == Kind.OWNED:
                self.diags.append(Diagnostic(
                    "OWN032",
                    f"cannot copy owned resource '{src.name}' into '{st.name}'; "
                    f"use 'move {src.name}' to transfer ownership", st.line))
            dst = self.declare(st.name, Kind.PLAIN, st.line)
            if src is not None and src.kind == Kind.PLAIN:
                dst.type_name = src.type_name  # a copy keeps the value's type
            return cur
        if isinstance(rhs, A.IntLit):
            dst = self.declare(st.name, Kind.PLAIN, st.line)
            dst.type_name = "int"
            return cur
        assert_never(rhs)

    def lower_buffer(self, st: A.Let, rhs: A.BufferIntent, cur: Block) -> Block:
        if rhs.ns != "Buffer":
            self.diags.append(Diagnostic(
                "OWN030",
                f"unknown buffer namespace '{rhs.ns}'; buffer intents are "
                f"written 'Buffer.<mode>(...)'", rhs.line))
            self.declare(st.name, Kind.OWNED, st.line)
            return cur
        if rhs.mode not in MODE_NAMES:
            self.diags.append(Diagnostic(
                "OWN030",
                f"unknown buffer mode '{rhs.mode}'; expected one of "
                f"{', '.join(sorted(MODE_NAMES))}", rhs.line))
            self.declare(st.name, Kind.OWNED, st.line)
            return cur
        # the size must resolve to an integer: an IntLit, or a plain `int` value.
        # A bool/other plain, a borrow, or an owned resource as the size would
        # lower to uncompilable C# (Rent(flag) / AsSpan(0, flag)).
        if rhs.size is None:
            self.diags.append(Diagnostic(
                "OWN018", f"buffer '{st.name}' requires a size", rhs.line))
        elif isinstance(rhs.size, A.VarRef):
            ssym = self.lookup(rhs.size.name, rhs.size.line)
            if ssym is not None and ssym.kind != Kind.PLAIN:
                self.diags.append(Diagnostic(
                    "OWN018",
                    f"buffer size '{rhs.size.name}' must be an integer, not "
                    f"{ssym.kind.name.lower()}", rhs.size.line))
            elif ssym is not None and ssym.type_name != "int":
                # an unknown-typed plain (e.g. a copy of a borrow) is NOT an int;
                # accepting it would lower to Rent(span)/AsSpan(0, span).
                what = (f"it is '{ssym.type_name}'" if ssym.type_name
                        else "its type cannot be determined")
                self.diags.append(Diagnostic(
                    "OWN018",
                    f"buffer size '{rhs.size.name}' must be an integer "
                    f"({what})", rhs.size.line))
        info, bdiags = resolve_buffer(rhs, self.policies)
        self.diags.extend(bdiags)
        sym = self.declare(st.name, Kind.OWNED, st.line)
        sym.buffer = info
        sym.origin = f"{st.name}#{rhs.line}:{rhs.col}"
        cur.instrs.append(AcquireBuffer(sym, info, st.line))
        return cur

    def lower_call(self, st: A.Call, cur: Block) -> Block:
        sig = self.signatures.get(st.callee)
        if sig is None:
            self.diags.append(Diagnostic(
                "OWN040",
                f"call to undeclared function '{st.callee}'; declare it with "
                f"'extern fn' (or define it) so its ownership effects are known",
                st.line))
            # still resolve args for name errors, but emit no Invoke
            for a in st.args:
                if isinstance(a, A.VarRef):
                    self.lookup(a.name, a.line)
            return cur
        if len(st.args) != len(sig.effects):
            self.diags.append(Diagnostic(
                "OWN041",
                f"'{st.callee}' expects {len(sig.effects)} argument(s) but got "
                f"{len(st.args)}", st.line))
            # resolve names for undefined-name errors, but skip effect checks:
            # an arity mismatch would make per-argument effects meaningless noise.
            for a in st.args:
                if isinstance(a, A.VarRef):
                    self.lookup(a.name, a.line)
            return cur
        resolved: list[tuple[Symbol | None, Effect]] = []
        for i, a in enumerate(st.args):
            eff = sig.effects[i] if i < len(sig.effects) else Effect.PLAIN
            if isinstance(a, A.VarRef):
                resolved.append((self.lookup(a.name, a.line), eff))
            else:
                resolved.append((None, eff))  # int literal
        cur.instrs.append(Invoke(st.callee, resolved, st.line))
        return cur

    def lower_borrow(self, st: A.BorrowBlock, cur: Block) -> Block | None:
        owner = self.lookup(st.owner, st.line)
        if owner is None:
            return cur
        if owner.kind != Kind.OWNED:
            self.diags.append(Diagnostic(
                "OWN034",
                f"cannot borrow '{st.owner}': it is not an owned resource", st.line))
            return cur
        mut = st.kind == A.BorrowKind.MUT
        self.push_scope()
        binding = self.declare(st.binding, Kind.BORROW, st.line, borrow_is_mut=mut)
        cur.instrs.append(BorrowStart(owner, binding, mut, st.line))
        after = self.lower_seq(st.body, cur)
        self.pop_scope()
        if after is None:
            return None
        after.instrs.append(BorrowEnd(owner, binding, mut, st.line))
        return after

    def lower_if(self, st: A.If, cur: Block) -> Block | None:
        then_entry = self.new_block("then")
        else_entry = self.new_block("else")
        cur.succ = [then_entry.id, else_entry.id]

        self.push_scope()
        then_exit = self.lower_seq(st.then_body, then_entry)
        self.pop_scope()

        self.push_scope()
        else_exit = self.lower_seq(st.else_body, else_entry)
        self.pop_scope()

        if then_exit is None and else_exit is None:
            return None

        merge = self.new_block("merge")
        if then_exit is not None:
            then_exit.succ = [merge.id]
        if else_exit is not None:
            else_exit.succ = [merge.id]
        return merge

    def lower_while(self, st: A.While, cur: Block) -> Block | None:
        # while (cond) { body }: a header block tests the (opaque) condition with
        # two successors — the body and the after-block. The body's exit loops back
        # to the header (the back-edge), so the header is a merge of the entry edge
        # and the back-edge. The analysis reaches a fixpoint over that back-edge
        # (analysis.py worklist); a borrow opened in the body closes within the same
        # iteration, so the loan set is identical on both header predecessors.
        header = self.new_block("while.header")
        cur.succ = [header.id]
        body_entry = self.new_block("while.body")
        after = self.new_block("while.after")
        header.succ = [body_entry.id, after.id]
        self.push_scope()
        body_exit = self.lower_seq(st.body, body_entry)
        self.pop_scope()
        if body_exit is not None:
            body_exit.succ = [header.id]   # back-edge: end of body -> re-test
        return after

    def lower_return(self, st: A.Return, cur: Block) -> Block | None:
        ret = self.fn.ret
        sym: Symbol | None = None
        if st.var is None:
            # `return;` with no value — only valid in a function with no return
            # type. Otherwise the analyzer would treat the function as a valid
            # terminal and codegen would emit `return;` from a non-void method.
            if ret is not None:
                self.diags.append(Diagnostic(
                    "OWN035",
                    f"'{self.fn.name}' returns '{ret.name}' but this 'return' "
                    f"provides no value", st.line))
        else:
            sym = self.lookup(st.var, st.line)
            if ret is None:
                # returning a value from a function with no declared return type
                # lowers to `return x;` inside a `void` method — uncompilable.
                if sym is not None:
                    self.diags.append(Diagnostic(
                        "OWN035",
                        f"'{self.fn.name}' has no return type but returns "
                        f"'{st.var}'", st.line))
                sym = None
            elif sym is not None and sym.kind == Kind.BORROW:
                self.diags.append(Diagnostic(
                    "OWN004",
                    f"'{st.var}' is a borrow and cannot be returned (it would "
                    f"outlive the resource it borrows)", st.line))
                sym = None
            elif (not ret.borrowed and ret.name in self.resource_names
                  and sym is not None and sym.buffer is None
                  and (sym.kind != Kind.OWNED or sym.type_name != ret.name)):
                # the return type is an owned resource; the returned value must be
                # an owned resource OF THE SAME type. Both a plain (`return n;`)
                # and a different resource (`return c;` where c is a Conn but the
                # function returns Buffer) lower to an uncompilable method, and
                # the analyzer would otherwise pass them. (Buffers have their own
                # escape rules -- OWN015/016/017 -- so they are left to the
                # analyzer rather than reported here.)
                if sym.kind != Kind.OWNED:
                    what = "not an owned resource"
                    sym = None        # a plain value: nothing escapes
                else:
                    # a real (but wrong-typed) owned resource still leaves the
                    # function; keep it so it is marked escaped, not leaked --
                    # the type mismatch is the error, an extra OWN001 is noise.
                    what = f"an owned '{sym.type_name}'"
                self.diags.append(Diagnostic(
                    "OWN035",
                    f"'{self.fn.name}' returns '{ret.name}' but '{st.var}' is "
                    f"{what}", st.line))
            elif sym is not None and sym.kind == Kind.PLAIN:
                sym = None
        cur.instrs.append(Return(sym, st.line))
        cur.succ = []
        return None


def collect_policies(mod: A.Module) -> dict[str, Policy]:
    return {p.name: Policy(p.name, dict(p.settings), p.line, p.dups)
            for p in mod.policies}


def build_cfg(fn: A.FnDecl, resource_names: set[str],
              signatures: dict[str, Signature],
              policies: dict[str, Policy] | None = None,
              resource_kinds: dict[str, str] | None = None
              ) -> tuple[CFG, list[Diagnostic]]:
    b = _Builder(fn, resource_names, signatures, policies, resource_kinds)
    cfg = b.build()
    return cfg, b.diags


def collect_kinds(mod: A.Module) -> dict[str, str]:
    """resource name -> its declared `kind` string (only those that set one)."""
    return {r.name: r.kind for r in mod.resources if r.kind}
