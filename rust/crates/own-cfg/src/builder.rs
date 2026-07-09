//! The scope resolver + AST → CFG lowering — an exact port of `cfg._Builder`
//! and the module-level `collect_*` helpers.
//!
//! Control flow follows Python line-for-line. The one structural change is
//! mechanical: Python threads live `Block` objects through the recursion and
//! returns `Block | None`; here blocks live in an arena and the recursion
//! threads [`BlockId`] / `Option<BlockId>`, so a block can be extended while a
//! sibling is created without aliasing a `&mut`.
//!
//! Diagnostics carry code + line only — see the crate docs for why the human
//! message text is deferred to the verdict/SARIF step.

use std::collections::{HashMap, HashSet};

use own_syntax::ast::{
    AliasJoin, BorrowBlock, BorrowKind, BufferIntent, Call, Effect, Expr, FnDecl, If, Let, Module,
    Return, Stmt, While,
};

use crate::buffers::{resolve, BufferMode, Policies, Policy};
use crate::ir::{Block, BlockId, Cfg, Kind, Signature, SymArena, SymId};
use crate::Diag;

/// Resource names declared in a module — the `{r.name for r in mod.resources}`
/// set `build_cfg` consumes.
#[must_use]
pub fn collect_resource_names(module: &Module) -> HashSet<String> {
    module.resources.iter().map(|r| r.name.clone()).collect()
}

/// One [`Signature`] per extern/local function (`cfg.collect_signatures`).
#[must_use]
pub fn collect_signatures(module: &Module) -> HashMap<String, Signature> {
    let mut sigs: HashMap<String, Signature> = HashMap::new();
    for e in &module.externs {
        sigs.insert(
            e.name.clone(),
            Signature {
                name: e.name.clone(),
                effects: e.params.iter().map(|p| p.effect).collect(),
            },
        );
    }
    let rnames: HashSet<&str> = module.resources.iter().map(|r| r.name.as_str()).collect();
    for f in &module.functions {
        let effects = f
            .params
            .iter()
            .map(|p| {
                if p.ty.borrowed && p.ty.mutable {
                    Effect::BorrowMut
                } else if p.ty.borrowed {
                    Effect::Borrow
                } else if rnames.contains(p.ty.name.as_str()) {
                    Effect::Consume
                } else {
                    Effect::Plain
                }
            })
            .collect();
        sigs.insert(
            f.name.clone(),
            Signature {
                name: f.name.clone(),
                effects,
            },
        );
    }
    sigs
}

/// The module's `policy` blocks keyed by name (`cfg.collect_policies`).
#[must_use]
pub fn collect_policies(module: &Module) -> Policies {
    module
        .policies
        .iter()
        .map(|p| {
            (
                p.name.clone(),
                Policy {
                    name: p.name.clone(),
                    settings: p
                        .settings
                        .iter()
                        .map(|(k, v)| (k.to_owned(), v.clone()))
                        .collect(),
                    line: p.line,
                    dups: p.dups.clone(),
                },
            )
        })
        .collect()
}

/// `resource name -> its declared non-empty `kind` string`
/// (`cfg.collect_kinds`).
#[must_use]
pub fn collect_kinds(module: &Module) -> HashMap<String, String> {
    module
        .resources
        .iter()
        .filter_map(|r| {
            let k = r.kind.as_ref()?;
            if k.is_empty() {
                None
            } else {
                Some((r.name.clone(), k.clone()))
            }
        })
        .collect()
}

/// Lower one function to its CFG plus the resolver's flow-insensitive
/// diagnostics (`cfg.build_cfg`).
// The maps use the std hasher; generalizing over `S` would only add noise to an
// internal-shaped API whose keys are short identifier strings.
#[allow(clippy::implicit_hasher)]
#[must_use]
pub fn build_cfg<'a>(
    fn_decl: &'a FnDecl,
    resource_names: &'a HashSet<String>,
    signatures: &'a HashMap<String, Signature>,
    policies: &'a Policies,
    resource_kinds: &'a HashMap<String, String>,
) -> (Cfg, Vec<Diag>) {
    Builder {
        fn_decl,
        resource_names,
        signatures,
        policies,
        resource_kinds,
        diags: Vec::new(),
        blocks: Vec::new(),
        scopes: Vec::new(),
        params: Vec::new(),
        arena: SymArena::default(),
    }
    .build()
}

struct Builder<'a> {
    fn_decl: &'a FnDecl,
    resource_names: &'a HashSet<String>,
    signatures: &'a HashMap<String, Signature>,
    policies: &'a Policies,
    resource_kinds: &'a HashMap<String, String>,
    diags: Vec<Diag>,
    blocks: Vec<Block>,
    scopes: Vec<HashMap<String, SymId>>,
    params: Vec<SymId>,
    arena: SymArena,
}

impl<'a> Builder<'a> {
    // -- scope helpers ------------------------------------------------------

    fn push_scope(&mut self) {
        self.scopes.push(HashMap::new());
    }

    fn pop_scope(&mut self) {
        self.scopes.pop();
    }

    fn declare(
        &mut self,
        name: &str,
        kind: Kind,
        line: u32,
        is_param_borrow: bool,
        borrow_is_mut: Option<bool>,
    ) -> SymId {
        // Shadowing across ANY enclosing scope (including the current one) is
        // OWN031 — but the symbol is still declared.
        if self.scopes.iter().any(|sc| sc.contains_key(name)) {
            self.diag("OWN031", line);
        }
        let id = self.arena.declare(name.to_owned(), kind, line);
        {
            let s = self.arena.get_mut(id);
            s.is_param_borrow = is_param_borrow;
            s.borrow_is_mut = borrow_is_mut;
        }
        if let Some(sc) = self.scopes.last_mut() {
            sc.insert(name.to_owned(), id);
        }
        id
    }

    fn lookup(&mut self, name: &str, line: u32) -> Option<SymId> {
        for sc in self.scopes.iter().rev() {
            if let Some(id) = sc.get(name) {
                return Some(*id);
            }
        }
        self.diag("OWN030", line);
        None
    }

    // -- blocks -------------------------------------------------------------

    fn new_block(&mut self, label: &str) -> BlockId {
        let id = BlockId(u32::try_from(self.blocks.len()).unwrap_or(u32::MAX));
        self.blocks.push(Block {
            id,
            instrs: Vec::new(),
            succ: Vec::new(),
            label: label.to_owned(),
        });
        id
    }

    #[allow(clippy::indexing_slicing)] // id was minted by new_block
    fn block_mut(&mut self, id: BlockId) -> &mut Block {
        &mut self.blocks[id.index()]
    }

    fn push_instr(&mut self, block: BlockId, ins: crate::ir::Instr) {
        self.block_mut(block).instrs.push(ins);
    }

    fn set_succ(&mut self, block: BlockId, succ: Vec<BlockId>) {
        self.block_mut(block).succ = succ;
    }

    fn diag(&mut self, code: &'static str, line: u32) {
        self.diags.push(Diag::new(code, line));
    }

    fn kind_of(&self, sym: SymId) -> Kind {
        self.arena.get(sym).kind
    }

    // -- build --------------------------------------------------------------

    fn build(mut self) -> (Cfg, Vec<Diag>) {
        self.push_scope();
        let fd = self.fn_decl;
        let rnames = self.resource_names;
        let rkinds = self.resource_kinds;
        for p in &fd.params {
            let sym = if p.ty.borrowed {
                self.declare(&p.name, Kind::Borrow, p.line, true, Some(p.ty.mutable))
            } else if rnames.contains(&p.ty.name) {
                self.declare(&p.name, Kind::Owned, p.line, false, None)
            } else {
                self.declare(&p.name, Kind::Plain, p.line, false, None)
            };
            {
                let s = self.arena.get_mut(sym);
                s.type_name = Some(p.ty.name.clone());
                s.resource_kind = rkinds.get(&p.ty.name).cloned();
                s.origin = Some(format!("{}#{}", p.name, p.line));
            }
            self.params.push(sym);
        }

        let entry = self.new_block("entry");
        let exit_block = self.lower_seq(&fd.body, entry);
        if fd.ret.is_some() && exit_block.is_some() {
            self.diag("OWN033", fd.line);
        }
        self.pop_scope();

        let cfg = Cfg {
            fn_name: fd.name.clone(),
            blocks: self.blocks,
            entry,
            params: self.params,
            has_return_type: fd.ret.is_some(),
            symbols: self.arena.into_vec(),
        };
        (cfg, self.diags)
    }

    fn lower_seq(&mut self, stmts: &'a [Stmt], cur: BlockId) -> Option<BlockId> {
        let mut node = Some(cur);
        for st in stmts {
            match node {
                None => return None,
                Some(n) => node = self.lower_stmt(st, n),
            }
        }
        node
    }

    fn lower_stmt(&mut self, st: &'a Stmt, cur: BlockId) -> Option<BlockId> {
        match st {
            Stmt::Let(l) => Some(self.lower_let(l, cur)),
            Stmt::Release(r) => {
                if let Some(sym) = self.lookup(&r.var, r.line) {
                    if self.kind_of(sym) == Kind::Owned {
                        self.push_instr(cur, crate::ir::Instr::Release { sym, line: r.line });
                    } else {
                        self.diag("OWN034", r.line);
                    }
                }
                Some(cur)
            }
            Stmt::Use(u) => {
                if let Some(sym) = self.lookup(&u.var, u.line) {
                    self.push_instr(cur, crate::ir::Instr::Use { sym, line: u.line });
                }
                Some(cur)
            }
            Stmt::Overspan(o) => {
                if let Some(sym) = self.lookup(&o.var, o.line) {
                    if self.kind_of(sym) == Kind::Owned {
                        self.push_instr(cur, crate::ir::Instr::Overspan { sym, line: o.line });
                    } else {
                        self.diag("OWN034", o.line);
                    }
                }
                Some(cur)
            }
            Stmt::Call(c) => Some(self.lower_call(c, cur)),
            Stmt::AliasJoin(a) => Some(self.lower_alias_join(a, cur)),
            Stmt::BorrowBlock(b) => self.lower_borrow(b, cur),
            Stmt::If(i) => self.lower_if(i, cur),
            Stmt::While(w) => Some(self.lower_while(w, cur)),
            Stmt::Return(r) => {
                self.lower_return(r, cur);
                None
            }
            // `subscribe self to X` is a lifetime-region fact handled elsewhere;
            // a no-op for the loans/permissions flow.
            Stmt::Subscribe(_) => Some(cur),
        }
    }

    fn lower_let(&mut self, st: &'a Let, cur: BlockId) -> BlockId {
        match &st.rhs {
            Expr::Acquire(rhs) => {
                if !self.resource_names.contains(&rhs.resource) {
                    self.diag("OWN030", rhs.line);
                }
                let sym = self.declare(&st.name, Kind::Owned, st.line, false, None);
                {
                    let s = self.arena.get_mut(sym);
                    s.type_name = Some(rhs.resource.clone());
                    s.resource_kind = self.resource_kinds.get(&rhs.resource).cloned();
                    s.origin = Some(format!("{}#{}", st.name, rhs.line));
                }
                self.push_instr(
                    cur,
                    crate::ir::Instr::Acquire {
                        sym,
                        resource: rhs.resource.clone(),
                        line: st.line,
                    },
                );
                cur
            }
            Expr::BufferIntent(rhs) => self.lower_buffer(st, rhs, cur),
            Expr::Move(rhs) => {
                let mut src = self.lookup(&rhs.var, rhs.line);
                if let Some(s) = src {
                    if self.kind_of(s) != Kind::Owned {
                        self.diag("OWN034", rhs.line);
                        src = None;
                    }
                }
                let dst = self.declare(&st.name, Kind::Owned, st.line, false, None);
                if let Some(s) = src {
                    // A moved buffer keeps its storage policy AND identity.
                    let (buffer, origin, type_name, resource_kind) = {
                        let ss = self.arena.get(s);
                        (
                            ss.buffer.clone(),
                            ss.origin.clone(),
                            ss.type_name.clone(),
                            ss.resource_kind.clone(),
                        )
                    };
                    {
                        let d = self.arena.get_mut(dst);
                        d.buffer = buffer;
                        d.origin = origin;
                        d.type_name = type_name;
                        d.resource_kind = resource_kind;
                    }
                    self.push_instr(
                        cur,
                        crate::ir::Instr::MoveInto {
                            dst,
                            src: s,
                            line: st.line,
                        },
                    );
                }
                cur
            }
            Expr::VarRef(rhs) => {
                let src = self.lookup(&rhs.name, rhs.line);
                if let Some(s) = src {
                    if self.kind_of(s) == Kind::Owned {
                        self.diag("OWN032", st.line);
                    }
                }
                let dst = self.declare(&st.name, Kind::Plain, st.line, false, None);
                if let Some(s) = src {
                    if self.kind_of(s) == Kind::Plain {
                        let tn = self.arena.get(s).type_name.clone();
                        self.arena.get_mut(dst).type_name = tn;
                    }
                }
                cur
            }
            Expr::IntLit(_) => {
                let dst = self.declare(&st.name, Kind::Plain, st.line, false, None);
                self.arena.get_mut(dst).type_name = Some("int".to_owned());
                cur
            }
        }
    }

    fn lower_alias_join(&mut self, st: &'a AliasJoin, cur: BlockId) -> BlockId {
        let mut src = self.lookup(&st.src, st.line);
        if let Some(s) = src {
            if self.kind_of(s) != Kind::Owned {
                self.diag("OWN034", st.line);
                src = None;
            }
        }
        let handle = self.declare(&st.name, Kind::Owned, st.line, false, None);
        if let Some(s) = src {
            let (origin, type_name, resource_kind, buffer) = {
                let ss = self.arena.get(s);
                (
                    ss.origin.clone(),
                    ss.type_name.clone(),
                    ss.resource_kind.clone(),
                    ss.buffer.clone(),
                )
            };
            {
                let h = self.arena.get_mut(handle);
                h.origin = origin;
                h.type_name = type_name;
                h.resource_kind = resource_kind;
                h.buffer = buffer;
            }
            self.push_instr(
                cur,
                crate::ir::Instr::AliasJoin {
                    handle,
                    src: s,
                    line: st.line,
                },
            );
        }
        cur
    }

    fn lower_buffer(&mut self, st: &'a Let, rhs: &'a BufferIntent, cur: BlockId) -> BlockId {
        if rhs.ns != "Buffer" {
            self.diag("OWN030", rhs.line);
            self.declare(&st.name, Kind::Owned, st.line, false, None);
            return cur;
        }
        let Some(mode) = BufferMode::from_value(&rhs.mode) else {
            self.diag("OWN030", rhs.line);
            self.declare(&st.name, Kind::Owned, st.line, false, None);
            return cur;
        };
        // The size must resolve to an integer.
        match &rhs.size {
            None => self.diag("OWN018", rhs.line),
            Some(sz) => {
                if let Expr::VarRef(v) = sz.as_ref() {
                    if let Some(ssym) = self.lookup(&v.name, v.line) {
                        // Python emits two distinct OWN018 messages here (wrong
                        // kind vs wrong type); both are OWN018 at the same line,
                        // which is all the CFG-JSON seam observes.
                        if self.kind_of(ssym) != Kind::Plain
                            || self.arena.get(ssym).type_name.as_deref() != Some("int")
                        {
                            self.diag("OWN018", v.line);
                        }
                    }
                }
            }
        }
        let (info, bdiags) = resolve(rhs, mode, self.policies);
        self.diags.extend(bdiags);
        let sym = self.declare(&st.name, Kind::Owned, st.line, false, None);
        {
            let s = self.arena.get_mut(sym);
            s.buffer = Some(info.clone());
            s.origin = Some(format!("{}#{}:{}", st.name, rhs.line, rhs.col));
        }
        self.push_instr(
            cur,
            crate::ir::Instr::AcquireBuffer {
                sym,
                info,
                line: st.line,
            },
        );
        cur
    }

    fn lower_call(&mut self, st: &'a Call, cur: BlockId) -> BlockId {
        let sigs = self.signatures;
        let Some(sig) = sigs.get(&st.callee) else {
            self.diag("OWN040", st.line);
            // still resolve args for name errors, but emit no Invoke
            for a in &st.args {
                if let Expr::VarRef(v) = a {
                    self.lookup(&v.name, v.line);
                }
            }
            return cur;
        };
        if st.args.len() != sig.effects.len() {
            self.diag("OWN041", st.line);
            for a in &st.args {
                if let Expr::VarRef(v) = a {
                    self.lookup(&v.name, v.line);
                }
            }
            return cur;
        }
        let mut resolved: Vec<(Option<SymId>, Effect)> = Vec::new();
        for (i, a) in st.args.iter().enumerate() {
            let eff = sig.effects.get(i).copied().unwrap_or(Effect::Plain);
            match a {
                Expr::VarRef(v) => {
                    let s = self.lookup(&v.name, v.line);
                    resolved.push((s, eff));
                }
                _ => resolved.push((None, eff)),
            }
        }
        self.push_instr(
            cur,
            crate::ir::Instr::Invoke {
                callee: st.callee.clone(),
                args: resolved,
                line: st.line,
            },
        );
        cur
    }

    fn lower_borrow(&mut self, st: &'a BorrowBlock, cur: BlockId) -> Option<BlockId> {
        let Some(owner) = self.lookup(&st.owner, st.line) else {
            return Some(cur);
        };
        if self.kind_of(owner) != Kind::Owned {
            self.diag("OWN034", st.line);
            return Some(cur);
        }
        let is_mut = st.kind == BorrowKind::Mut;
        self.push_scope();
        let binding = self.declare(&st.binding, Kind::Borrow, st.line, false, Some(is_mut));
        self.push_instr(
            cur,
            crate::ir::Instr::BorrowStart {
                owner,
                binding,
                is_mut,
                line: st.line,
            },
        );
        let after = self.lower_seq(&st.body, cur);
        self.pop_scope();
        let after = after?;
        self.push_instr(
            after,
            crate::ir::Instr::BorrowEnd {
                owner,
                binding,
                is_mut,
                line: st.line,
            },
        );
        Some(after)
    }

    fn lower_if(&mut self, st: &'a If, cur: BlockId) -> Option<BlockId> {
        let then_entry = self.new_block("then");
        let else_entry = self.new_block("else");
        self.set_succ(cur, vec![then_entry, else_entry]);

        self.push_scope();
        let then_exit = self.lower_seq(&st.then_body, then_entry);
        self.pop_scope();

        self.push_scope();
        let else_exit = self.lower_seq(&st.else_body, else_entry);
        self.pop_scope();

        if then_exit.is_none() && else_exit.is_none() {
            return None;
        }

        let merge = self.new_block("merge");
        if let Some(te) = then_exit {
            self.set_succ(te, vec![merge]);
        }
        if let Some(ee) = else_exit {
            self.set_succ(ee, vec![merge]);
        }
        Some(merge)
    }

    // `while` always yields its after-block (Python returns a Block, never
    // `None`); the dispatcher wraps it in `Some`.
    fn lower_while(&mut self, st: &'a While, cur: BlockId) -> BlockId {
        let header = self.new_block("while.header");
        self.set_succ(cur, vec![header]);
        let body_entry = self.new_block("while.body");
        let after = self.new_block("while.after");
        self.set_succ(header, vec![body_entry, after]);
        self.push_scope();
        let body_exit = self.lower_seq(&st.body, body_entry);
        self.pop_scope();
        if let Some(be) = body_exit {
            self.set_succ(be, vec![header]); // back-edge: end of body -> re-test
        }
        after
    }

    fn lower_return(&mut self, st: &'a Return, cur: BlockId) {
        let ret_opt = self.fn_decl.ret.as_ref();
        let rnames = self.resource_names;
        let mut sym: Option<SymId> = None;
        match &st.var {
            None => {
                // `return;` with no value — only valid in a function with no
                // return type.
                if ret_opt.is_some() {
                    self.diag("OWN035", st.line);
                }
            }
            Some(var) => {
                sym = self.lookup(var, st.line);
                match ret_opt {
                    None => {
                        // returning a value from a function with no return type.
                        if sym.is_some() {
                            self.diag("OWN035", st.line);
                        }
                        sym = None;
                    }
                    Some(ret) => {
                        if matches!(sym, Some(s) if self.kind_of(s) == Kind::Borrow) {
                            self.diag("OWN004", st.line);
                            sym = None;
                        } else if let Some(s) = sym {
                            let k = self.kind_of(s);
                            let buf_none = self.arena.get(s).buffer.is_none();
                            let type_name = self.arena.get(s).type_name.clone();
                            let type_mismatch =
                                k != Kind::Owned || type_name.as_deref() != Some(ret.name.as_str());
                            if !ret.borrowed
                                && rnames.contains(&ret.name)
                                && buf_none
                                && type_mismatch
                            {
                                // a plain value: nothing escapes; a wrong-typed
                                // owned resource is kept (so it is marked escaped,
                                // not leaked) — the type mismatch is the error.
                                if k != Kind::Owned {
                                    sym = None;
                                }
                                self.diag("OWN035", st.line);
                            } else if k == Kind::Plain {
                                sym = None;
                            }
                        }
                    }
                }
            }
        }
        self.push_instr(cur, crate::ir::Instr::Return { sym, line: st.line });
        self.set_succ(cur, Vec::new());
    }
}
