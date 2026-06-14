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


@dataclass
class IntLit:
    value: int
    line: int


@dataclass
class VarRef:
    name: str
    line: int


@dataclass
class Acquire:
    """acquire Resource(args) -> Owned<Resource>"""
    resource: str
    args: list["Expr"]
    line: int


@dataclass
class Move:
    """move x  -> transfers ownership, invalidates x"""
    var: str
    line: int


@dataclass
class BufferIntent:
    """Buffer.<mode>(size, name = value, ...) -> Owned<Buffer> with a storage
    policy. `mode` is one of stack/scratch/pooled/native/inline. `size` is the
    single positional argument (an IntLit or VarRef), or None. `options` maps a
    named option (inline, max, fallback, clear, trace, counters, policy) to its
    value expression. `ns` is the namespace as written (must be "Buffer")."""
    mode: str
    size: "Expr | None"
    options: dict[str, "Expr"]
    line: int
    ns: str = "Buffer"
    col: int = 0


Expr = IntLit | VarRef | Acquire | Move | BufferIntent


# ---- statements -----------------------------------------------------------


@dataclass
class Let:
    name: str
    rhs: Expr
    line: int


@dataclass
class Release:
    """release x;  -> consumes x"""
    var: str
    line: int


@dataclass
class Use:
    """use x;  -> reads x (owner or live borrow)"""
    var: str
    line: int


@dataclass
class Call:
    """callee(args);  -> a call to a declared extern or local fn"""
    callee: str
    args: list["Expr"]
    line: int


@dataclass
class BorrowBlock:
    owner: str
    binding: str
    kind: BorrowKind
    body: list["Stmt"]
    line: int


@dataclass
class If:
    # condition is intentionally opaque: we model control flow, not values
    cond_text: str
    then_body: list["Stmt"]
    else_body: list["Stmt"]
    line: int


@dataclass
class Return:
    var: str | None
    line: int


Stmt = Let | Release | Use | Call | BorrowBlock | If | Return


# ---- top level ------------------------------------------------------------


@dataclass
class ResourceMember:
    role: str   # "acquire" | "release"
    name: str
    line: int


@dataclass
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


@dataclass
class EffectParam:
    """A positional parameter of an extern fn: an effect + a resource/plain type."""
    effect: Effect
    type_name: str
    line: int


@dataclass
class ExternDecl:
    name: str
    params: list[EffectParam]
    ret: TypeRef | None
    line: int


@dataclass
class Param:
    name: str
    type: TypeRef
    line: int


@dataclass
class FnDecl:
    name: str
    params: list[Param]
    ret: TypeRef | None
    body: list[Stmt]
    line: int


@dataclass
class PolicyDecl:
    """policy Name { key = value; ... } — a named bundle of buffer defaults
    (inline_bytes, max_bytes, mode, fallback, trace, counters, clear_on_release)."""
    name: str
    settings: dict[str, object]
    line: int


@dataclass
class Module:
    name: str
    resources: list[ResourceDecl] = field(default_factory=list)
    externs: list[ExternDecl] = field(default_factory=list)
    functions: list[FnDecl] = field(default_factory=list)
    policies: list[PolicyDecl] = field(default_factory=list)
