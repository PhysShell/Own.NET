"""AST for OwnLang. Plain dataclasses; every node carries a source line."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class BorrowKind(Enum):
    SHARED = auto()
    MUT = auto()


class Effect(Enum):
    """Ownership effect of an extern/fn parameter on its argument."""
    BORROW = auto()      # &T   : temporary shared loan for the call, noescape
    BORROW_MUT = auto()  # &mut : temporary exclusive loan for the call, noescape
    CONSUME = auto()     # takes ownership (the only way a value may escape)
    PLAIN = auto()       # by-value, non-resource (e.g. int)


# ---- types ----------------------------------------------------------------


@dataclass(frozen=True)
class TypeRef:
    name: str          # e.g. "Buffer", "int"
    borrowed: bool     # &T  or &mut T
    mutable: bool      # &mut T
    line: int = 0


# ---- expressions (RHS of a let, or argument) ------------------------------


@dataclass(frozen=True)
class IntLit:
    value: int
    line: int


@dataclass(frozen=True)
class VarRef:
    name: str
    line: int


@dataclass(frozen=True)
class Acquire:
    """acquire Resource(args) -> Owned<Resource>"""
    resource: str
    args: list[Expr]
    line: int


@dataclass(frozen=True)
class Move:
    """move x  -> transfers ownership, invalidates x"""
    var: str
    line: int


@dataclass(frozen=True)
class BufferIntent:
    """Buffer.<mode>(size, name = value, ...) -> Owned<Buffer> with a storage
    policy. `mode` is one of stack/scratch/pooled/native/inline. `size` is the
    single positional argument (an IntLit or VarRef), or None. `options` maps a
    named option (inline, max, fallback, clear, trace, counters, policy) to its
    value expression. `ns` is the namespace as written (must be "Buffer")."""
    mode: str
    size: Expr | None
    options: dict[str, Expr]
    line: int
    ns: str = "Buffer"
    col: int = 0
    dups: tuple[str, ...] = ()   # option names that appeared more than once


Expr = IntLit | VarRef | Acquire | Move | BufferIntent


# ---- statements -----------------------------------------------------------


@dataclass(frozen=True)
class Let:
    name: str
    rhs: Expr
    line: int


@dataclass(frozen=True)
class Release:
    """release x;  -> consumes x"""
    var: str
    line: int


@dataclass(frozen=True)
class Use:
    """use x;  -> reads x (owner or live borrow)"""
    var: str
    line: int


@dataclass(frozen=True)
class Call:
    """callee(args);  -> a call to a declared extern or local fn"""
    callee: str
    args: list[Expr]
    line: int


@dataclass(frozen=True)
class BorrowBlock:
    owner: str
    binding: str
    kind: BorrowKind
    body: list[Stmt]
    line: int


@dataclass(frozen=True)
class If:
    # condition is intentionally opaque: we model control flow, not values
    cond_text: str
    then_body: list[Stmt]
    else_body: list[Stmt]
    line: int


@dataclass(frozen=True)
class Return:
    var: str | None
    line: int


@dataclass(frozen=True)
class Subscribe:
    """`subscribe self to SOURCE;` — the current object (the function's scope,
    living at the function's lifetime) is strongly captured by `source`. If
    `source` outlives `self`, `self` is promoted to the longer lifetime (a
    region escape). The heart of the lifetime/region analysis."""
    source: str
    line: int


Stmt = Let | Release | Use | Call | BorrowBlock | If | Return | Subscribe


# ---- top level ------------------------------------------------------------


@dataclass(frozen=True)
class ResourceMember:
    role: str   # "acquire" | "release"
    name: str
    line: int


@dataclass(frozen=True)
class ResourceDecl:
    name: str
    members: list[ResourceMember]
    line: int
    # optional C# emission templates; when present, codegen lowers this
    # resource to real .NET instead of the schematic Resource.method() form.
    emit_type: str | None = None       # e.g. "byte[]"
    emit_acquire: str | None = None    # e.g. "ArrayPool<byte>.Shared.Rent({args})"
    emit_release: str | None = None    # e.g. "ArrayPool<byte>.Shared.Return({0})"
    emit_borrow: str | None = None     # e.g. "{0}.AsSpan()"
    # an optional human "kind" of resource (e.g. "subscription token", "timer"),
    # carried onto diagnostics as `[resource: <kind>]`. Domain-neutral metadata:
    # a later profile (e.g. WPF) reads it to give the generic OWN finding a
    # business-flavoured framing, without the core knowing about any domain.
    kind: str | None = None


@dataclass(frozen=True)
class EffectParam:
    """A positional parameter of an extern fn: an effect + a resource/plain type."""
    effect: Effect
    type_name: str
    line: int


@dataclass(frozen=True)
class ExternDecl:
    name: str
    params: list[EffectParam]
    ret: TypeRef | None
    line: int


@dataclass(frozen=True)
class Param:
    name: str
    type: TypeRef
    line: int
    # optional lifetime region this parameter (a service / source) lives at,
    # e.g. `bus: EventBus lifetime App`. None when unannotated.
    lifetime: str | None = None


@dataclass(frozen=True)
class FnDecl:
    name: str
    params: list[Param]
    ret: TypeRef | None
    body: list[Stmt]
    line: int
    # optional lifetime region of the object this function sets up (its scope),
    # e.g. `fn CustomerViewModel(...) lifetime ViewModel { ... }`. None when
    # unannotated (the lifetime analysis then skips this function).
    lifetime: str | None = None


@dataclass(frozen=True)
class LifetimeDecl:
    """`lifetime NAME;` or `lifetime NAME < LONGER;` — declares a region. The
    `< LONGER` form states NAME is strictly shorter-lived than LONGER (nested
    inside it). The relation is transitive; cycles are rejected."""
    name: str
    longer: str | None   # the region this one is strictly shorter than, if any
    line: int


@dataclass(frozen=True)
class PolicyDecl:
    """policy Name { key = value; ... } — a named bundle of buffer defaults
    (inline_bytes, max_bytes, mode, fallback, trace, counters, clear_on_release)."""
    name: str
    settings: dict[str, object]
    line: int
    dups: tuple[str, ...] = ()   # setting keys that appeared more than once


@dataclass(frozen=True)
class Module:
    name: str
    resources: list[ResourceDecl] = field(default_factory=list)
    externs: list[ExternDecl] = field(default_factory=list)
    functions: list[FnDecl] = field(default_factory=list)
    policies: list[PolicyDecl] = field(default_factory=list)
    lifetimes: list[LifetimeDecl] = field(default_factory=list)
