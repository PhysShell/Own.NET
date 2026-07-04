//! AST — a node-for-node port of `ownlang/ast_nodes.py`.
//!
//! Python's nodes are shallow-frozen dataclasses; Rust gets real immutability
//! for free (owned values, no `&mut` handed out by the parser). Field names,
//! defaults and the `Expr`/`Stmt` unions map 1:1 so a later serializer can
//! reproduce Python's dump byte-for-byte.
//!
//! Two representation choices worth recording:
//!
//! * `IntLit.value` is `u64` where Python has an arbitrary-precision `int`.
//!   The lexer only produces unsigned digit runs; a literal above `u64::MAX`
//!   is a **recorded divergence** (the parser rejects it loudly instead of
//!   silently truncating — the oracle would flag the acceptance difference
//!   immediately). The corpus and fixtures stay far below the limit.
//! * Python's `dict[str, ...]` for buffer options / policy settings is an
//!   insertion-ordered map with last-value-wins on duplicate keys (the parser
//!   tracks the duplicates separately in `dups`). [`OrderedMap`] mirrors
//!   exactly that; N is tiny (option names), so a linear scan beats hashing.

/// Insertion-ordered string-keyed map with Python-`dict` update semantics:
/// inserting an existing key overwrites the value **in place** (first
/// appearance keeps its position), a new key appends.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct OrderedMap<V>(Vec<(String, V)>);

impl<V> OrderedMap<V> {
    #[must_use]
    pub const fn new() -> Self {
        Self(Vec::new())
    }

    pub fn insert(&mut self, key: &str, value: V) {
        if let Some(slot) = self.0.iter_mut().find(|(k, _)| k == key) {
            slot.1 = value;
        } else {
            self.0.push((key.to_owned(), value));
        }
    }

    #[must_use]
    pub fn get(&self, key: &str) -> Option<&V> {
        self.0.iter().find(|(k, _)| k == key).map(|(_, v)| v)
    }

    #[must_use]
    pub fn len(&self) -> usize {
        self.0.len()
    }

    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    pub fn iter(&self) -> impl Iterator<Item = (&str, &V)> {
        self.0.iter().map(|(k, v)| (k.as_str(), v))
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BorrowKind {
    Shared,
    Mut,
}

/// Ownership effect of an extern/fn parameter on its argument.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Effect {
    /// `&T`: temporary shared loan for the call, noescape.
    Borrow,
    /// `&mut`: temporary exclusive loan for the call, noescape.
    BorrowMut,
    /// Takes ownership (the only way a value may escape).
    Consume,
    /// By-value, non-resource (e.g. int).
    Plain,
}

// ---- types -----------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TypeRef {
    /// e.g. `"Buffer"`, `"int"`.
    pub name: String,
    /// `&T` or `&mut T`.
    pub borrowed: bool,
    /// `&mut T`.
    pub mutable: bool,
    pub line: u32,
}

// ---- expressions (RHS of a let, or argument) --------------------------------

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Expr {
    IntLit(IntLit),
    VarRef(VarRef),
    Acquire(Acquire),
    Move(Move),
    BufferIntent(BufferIntent),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IntLit {
    pub value: u64,
    pub line: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VarRef {
    pub name: String,
    pub line: u32,
}

/// `acquire Resource(args)` → `Owned<Resource>`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Acquire {
    pub resource: String,
    pub args: Vec<Expr>,
    pub line: u32,
}

/// `move x` → transfers ownership, invalidates `x`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Move {
    pub var: String,
    pub line: u32,
}

/// `Buffer.<mode>(size, name = value, ...)` → `Owned<Buffer>` with a storage policy.
///
/// `mode` is one of stack/scratch/pooled/native/inline. `size` is the
/// single positional argument (an `IntLit` or `VarRef`), or `None`. `options`
/// maps a named option (inline, max, fallback, clear, trace, counters, policy)
/// to its value expression. `ns` is the namespace as written (must be
/// `"Buffer"`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BufferIntent {
    pub mode: String,
    pub size: Option<Box<Expr>>,
    pub options: OrderedMap<Expr>,
    pub line: u32,
    pub ns: String,
    pub col: u32,
    /// Option names that appeared more than once (sorted, deduplicated).
    pub dups: Vec<String>,
}

// ---- statements --------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Stmt {
    Let(Let),
    Release(Release),
    Use(Use),
    Overspan(Overspan),
    Call(Call),
    AliasJoin(AliasJoin),
    BorrowBlock(BorrowBlock),
    If(If),
    While(While),
    Return(Return),
    Subscribe(Subscribe),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Let {
    pub name: String,
    pub rhs: Expr,
    pub line: u32,
}

/// `release x;` → consumes `x`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Release {
    pub var: String,
    pub line: u32,
}

/// `use x;` → reads `x` (owner or live borrow).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Use {
    pub var: String,
    pub line: u32,
}

/// `overspan x;` — a full-length pooled view (POOL005).
///
/// A view (`Span`/`Memory`) is taken over the whole pooled buffer `x`,
/// reaching past the logical length it was rented for; the fix is a bounded
/// view `buf.AsSpan(0, n)`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Overspan {
    pub var: String,
    pub line: u32,
}

/// `callee(args);` → a call to a declared extern or local fn.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Call {
    pub callee: String,
    pub args: Vec<Expr>,
    pub line: u32,
}

/// `name` is a *new owning handle* on the SAME resource obligation as `src`.
///
/// A resource-alias (RLC's `@MustCallAlias`); unlike `move`, `src` stays
/// owning. Not produced by the grammar today — carried for parity with
/// `ast_nodes.AliasJoin` (constructed programmatically by later passes).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AliasJoin {
    /// The new owning handle that joins the alias set.
    pub name: String,
    /// An existing handle whose resource obligation `name` shares.
    pub src: String,
    pub line: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BorrowBlock {
    pub owner: String,
    pub binding: String,
    pub kind: BorrowKind,
    pub body: Vec<Stmt>,
    pub line: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct If {
    /// Intentionally opaque: we model control flow, not values.
    pub cond_text: String,
    pub then_body: Vec<Stmt>,
    pub else_body: Vec<Stmt>,
    pub line: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct While {
    /// Opaque like [`If::cond_text`]; the analysis reaches a fixpoint over
    /// the loop's back-edge.
    pub cond_text: String,
    pub body: Vec<Stmt>,
    pub line: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Return {
    pub var: Option<String>,
    pub line: u32,
}

/// `subscribe self to SOURCE;` — the current object is strongly captured by
/// `source`; if `source` outlives `self`, `self` is promoted to the longer
/// lifetime (a region escape).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Subscribe {
    pub source: String,
    pub line: u32,
}

// ---- top level ----------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MemberRole {
    Acquire,
    Release,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResourceMember {
    pub role: MemberRole,
    pub name: String,
    pub line: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResourceDecl {
    pub name: String,
    pub members: Vec<ResourceMember>,
    pub line: u32,
    /// Optional C# emission templates; when present, codegen lowers this
    /// resource to real .NET instead of the schematic `Resource.method()` form.
    pub emit_type: Option<String>,
    pub emit_acquire: Option<String>,
    pub emit_release: Option<String>,
    pub emit_borrow: Option<String>,
    /// Optional human "kind" of resource (e.g. "subscription token"), carried
    /// onto diagnostics as `[resource: <kind>]`.
    pub kind: Option<String>,
}

/// A positional parameter of an extern fn: an effect + a resource/plain type.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EffectParam {
    pub effect: Effect,
    pub type_name: String,
    pub line: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExternDecl {
    pub name: String,
    pub params: Vec<EffectParam>,
    pub ret: Option<TypeRef>,
    pub line: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Param {
    pub name: String,
    pub ty: TypeRef,
    pub line: u32,
    /// Optional lifetime region this parameter lives at, e.g.
    /// `bus: EventBus lifetime App`. `None` when unannotated.
    pub lifetime: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FnDecl {
    pub name: String,
    pub params: Vec<Param>,
    pub ret: Option<TypeRef>,
    pub body: Vec<Stmt>,
    pub line: u32,
    /// Optional lifetime region of the object this function sets up, e.g.
    /// `fn CustomerViewModel(...) lifetime ViewModel { ... }`.
    pub lifetime: Option<String>,
}

/// `lifetime NAME;` or `lifetime NAME < LONGER;` — declares a region; the
/// `< LONGER` form states NAME is strictly shorter-lived than LONGER.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LifetimeDecl {
    pub name: String,
    pub longer: Option<String>,
    pub line: u32,
}

/// A policy setting value: an int, or an identifier interpreted as a bool
/// (`true`/`false`) or a bare keyword string (`pool`/`forbidden`/`debug`/...).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PolicyValue {
    Int(u64),
    Bool(bool),
    Word(String),
}

/// `policy Name { key = value; ... }` — a named bundle of buffer defaults.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PolicyDecl {
    pub name: String,
    pub settings: OrderedMap<PolicyValue>,
    pub line: u32,
    /// Setting keys that appeared more than once (sorted, deduplicated).
    pub dups: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Module {
    pub name: String,
    pub resources: Vec<ResourceDecl>,
    pub externs: Vec<ExternDecl>,
    pub functions: Vec<FnDecl>,
    pub policies: Vec<PolicyDecl>,
    pub lifetimes: Vec<LifetimeDecl>,
}
