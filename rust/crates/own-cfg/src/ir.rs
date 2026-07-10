//! The CFG intermediate representation — the port of the `cfg.py` dataclasses
//! (`Symbol`, the `Instr` union, `Block`, `CFG`, `Signature`).
//!
//! Two Python-isms are re-expressed idiomatically:
//!
//! * Python keys symbol identity on `id(sym)`. Here every symbol is minted into
//!   a per-function arena and referenced by a newtype index [`SymId`], so the
//!   *identity structure* the CFG-JSON seam pins (a borrow binding is a distinct
//!   symbol from its owner; a `move` alias shares nothing with its source) is
//!   reproduced deterministically and portably.
//! * Blocks are likewise referenced by [`BlockId`] (their position in the arena)
//!   rather than by object reference, so the builder can mutate one block while
//!   creating another without fighting the borrow checker.

use own_syntax::ast::Effect;

use crate::buffers::BufferInfo;

/// A symbol's classification (`cfg.Kind`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    /// A linear resource: must be consumed exactly once.
    Owned,
    /// A borrow binding or a borrowed (`&T` / `&mut T`) parameter.
    Borrow,
    /// An int, or a copy of a borrow/int — not lifetime-tracked.
    Plain,
}

impl Kind {
    /// `Kind.<K>.name.lower()` — the CFG-JSON `kind` spelling.
    #[must_use]
    pub const fn py_name(self) -> &'static str {
        match self {
            Self::Owned => "owned",
            Self::Borrow => "borrow",
            Self::Plain => "plain",
        }
    }
}

/// Index of a [`Symbol`] in its function's arena ([`Cfg::symbols`]). Mirrors
/// Python's per-symbol object identity.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct SymId(pub u32);

impl SymId {
    pub(crate) const fn index(self) -> usize {
        self.0 as usize
    }
}

/// Index of a [`Block`] in [`Cfg::blocks`]. Equals the block's `id`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct BlockId(pub u32);

impl BlockId {
    pub(crate) const fn index(self) -> usize {
        self.0 as usize
    }
}

/// A name reference resolved to a unique symbol and classified (`cfg.Symbol`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Symbol {
    pub name: String,
    pub kind: Kind,
    pub def_line: u32,
    /// A borrowed parameter (live for the whole body); plain borrow-block
    /// bindings start not-live and are made live by `BorrowStart`.
    pub is_param_borrow: bool,
    /// For `Borrow` symbols: `Some(true)` mutable, `Some(false)` shared; `None`
    /// for non-borrow symbols.
    pub borrow_is_mut: Option<bool>,
    /// For owned buffer symbols: the resolved storage policy.
    pub buffer: Option<BufferInfo>,
    /// The declared/inferred type name; `None` when unknown.
    pub type_name: Option<String>,
    /// The resource's optional human "kind" (e.g. `"subscription token"`).
    pub resource_kind: Option<String>,
    /// A stable identity for the originating buffer/resource (`name#line`),
    /// inherited across `move`/alias.
    pub origin: Option<String>,
}

impl Symbol {
    const fn new(name: String, kind: Kind, def_line: u32) -> Self {
        Self {
            name,
            kind,
            def_line,
            is_param_borrow: false,
            borrow_is_mut: None,
            buffer: None,
            type_name: None,
            resource_kind: None,
            origin: None,
        }
    }
}

/// One CFG instruction (`cfg.Instr`). Symbol operands are [`SymId`] into the
/// function arena; a `None` operand is a literal / unresolved reference.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Instr {
    Acquire {
        sym: SymId,
        resource: String,
        line: u32,
    },
    AcquireBuffer {
        sym: SymId,
        info: BufferInfo,
        line: u32,
    },
    MoveInto {
        dst: SymId,
        src: SymId,
        line: u32,
    },
    Release {
        sym: SymId,
        line: u32,
    },
    Use {
        sym: SymId,
        line: u32,
    },
    Overspan {
        sym: SymId,
        line: u32,
    },
    Invoke {
        callee: String,
        args: Vec<(Option<SymId>, Effect)>,
        line: u32,
    },
    BorrowStart {
        owner: SymId,
        binding: SymId,
        is_mut: bool,
        line: u32,
    },
    BorrowEnd {
        owner: SymId,
        binding: SymId,
        is_mut: bool,
        line: u32,
    },
    AliasJoin {
        handle: SymId,
        src: SymId,
        line: u32,
    },
    Return {
        sym: Option<SymId>,
        line: u32,
    },
}

/// A basic block: a straight-line instruction list plus successor edges.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Block {
    pub id: BlockId,
    pub instrs: Vec<Instr>,
    pub succ: Vec<BlockId>,
    pub label: String,
}

/// One function's control-flow graph plus its symbol arena.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Cfg {
    pub fn_name: String,
    pub blocks: Vec<Block>,
    pub entry: BlockId,
    pub params: Vec<SymId>,
    pub has_return_type: bool,
    /// The per-function symbol arena; [`SymId`] indexes it. Referenced by
    /// [`crate::json`] to project the CFG-JSON symbol table.
    pub symbols: Vec<Symbol>,
}

impl Cfg {
    /// Borrow a symbol by id. Panic-free by construction: every [`SymId`] was
    /// minted by this arena's `push`.
    #[allow(clippy::indexing_slicing)] // id ∈ [0, symbols.len()) — minted here
    #[must_use]
    pub fn symbol(&self, id: SymId) -> &Symbol {
        &self.symbols[id.index()]
    }
}

/// A module-level signature: one [`Effect`] per positional parameter
/// (`cfg.Signature`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Signature {
    pub name: String,
    pub effects: Vec<Effect>,
}

/// The growable symbol arena the builder mints into. Kept here so [`SymId`]'s
/// minting invariant (`index < len`) lives next to its only mutator.
#[derive(Debug, Default)]
pub(crate) struct SymArena {
    syms: Vec<Symbol>,
}

impl SymArena {
    pub(crate) fn declare(&mut self, name: String, kind: Kind, def_line: u32) -> SymId {
        let id = SymId(u32::try_from(self.syms.len()).unwrap_or(u32::MAX));
        self.syms.push(Symbol::new(name, kind, def_line));
        id
    }

    #[allow(clippy::indexing_slicing)] // id was minted by this arena
    pub(crate) fn get_mut(&mut self, id: SymId) -> &mut Symbol {
        &mut self.syms[id.index()]
    }

    #[allow(clippy::indexing_slicing)] // id was minted by this arena
    pub(crate) fn get(&self, id: SymId) -> &Symbol {
        &self.syms[id.index()]
    }

    pub(crate) fn into_vec(self) -> Vec<Symbol> {
        self.syms
    }
}
