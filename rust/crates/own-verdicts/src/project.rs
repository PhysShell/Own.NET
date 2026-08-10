//! Layer 2 → analysis AST: the pure projection
//! [`LoweredDocument`] → [`own_cfg::ast::Module`].
//!
//! # What this is the inverse of
//!
//! `ownlang/lowered.py::project_lowered` serializes the `Module` that
//! `to_module` built. This walks that projection backwards. It is *not* a
//! second lowering: nothing here reads `OwnIR`, invents a routing decision, or
//! consults the handle map — the whole function is a shape change over data
//! the bridge already decided.
//!
//! # Why it is total, and where the elided coordinates come from
//!
//! Layer 2 is a lossy view of `Module`, so the inverse has to supply what the
//! forward direction dropped. Every one of those values is a **constant in the
//! reference bridge**, not a default this module chose:
//!
//! | dropped by `lowered.py` | reference construction |
//! |---|---|
//! | `ResourceDecl.line`, `ResourceMember.line` | `_prelude_resources()` — literal `0` |
//! | `ExternDecl.line`, `EffectParam.line` | `_OWNERSHIP_SINK_EXTERNS` — literal `0` |
//! | `LifetimeDecl.line` | `_CAPTURE_LIFETIMES` — literal `0` |
//! | `FnDecl.line` | `FnDecl(…, 0, …)` at both construction sites |
//! | `TypeRef.line` | never passed; `ast_nodes.TypeRef.line` defaults to `0` |
//! | `ResourceDecl.emit_*` | never passed — and `_resource` fails loud on a non-`None` |
//! | `Module.policies` | never built — and `project_lowered` fails loud on a non-empty |
//! | `Acquire.args` | always `[]` — and `_stmt` fails loud on a non-empty |
//! | `ExternDecl.ret` | always `None` — and `_extern` fails loud on a non-`None` |
//!
//! The bottom four rows are the load-bearing ones: the forward projection does
//! not *silently* drop them, it **refuses** any document where they carry
//! information. So reconstructing them as empty/`None` restores the original
//! value rather than guessing at one, and the emptiness is the forward
//! direction's own invariant rather than this module's assumption.
//!
//! A `VarRef` call argument is the same story one level down: Layer 2 keeps
//! only the name because every argument the bridge mints carries the enclosing
//! statement's line (`VarRef(…, line)` at all three call sites), so re-attaching
//! that line is exact.
//!
//! # Where it is NOT total
//!
//! Two Layer 2 fields are **text** where the AST has a **closed enum**:
//! `ResourceMember.role` and `ExternParam.effect`. A value outside the
//! vocabulary is unrepresentable, not merely unusual, so it fails loud.
//!
//! That is the only rejection here, and it is deliberately not extended.
//! `LoweredDocument` is already a proven surface — `deny_unknown_fields`
//! everywhere, a closed `Stmt` discriminator, a `lowered_version` gate in
//! [`own_lowered::parse_document`], and a byte-exact replay against the Python
//! goldens. Re-checking any of that here would invent a second validation
//! contract whose only effect is to disagree with the first one eventually.
//! Handle references in particular are **not** resolved: `Module` has no handle
//! map (`to_module` returns it *alongside* the AST, and Layer 3 is what reads
//! it), so an unresolvable `handle` is not a fact this layer can even state.
//!
//! The rejection is reachable in practice despite the bridge never producing
//! it: a `LoweredDocument` can also arrive by deserializing a Layer 2 document,
//! and the schema types both fields as free strings.

use own_cfg::ast;
use own_ir::span::SourceLine;
use own_lowered::{Extern, Function, Lifetime, LoweredDocument, Param, Resource, Stmt, TypeShape};

use crate::VerdictError;

/// The line every coordinate Layer 2 elides carries in the reference bridge.
///
/// Named rather than written as a bare `0` at fourteen call sites so the claim
/// is auditable in one place: this is *the reference's literal*, not a
/// placeholder standing in for a line nobody knows.
const ELIDED: SourceLine = SourceLine(0);

/// Project one Layer 2 document into the analysis AST.
///
/// Pure and allocation-only: no facts, no analysis, no handle resolution. The
/// result is the `Module` `ownlang.ownir::to_module` built, reconstructed from
/// its serialized view.
///
/// # Errors
/// [`VerdictError`] when a resource member role or an extern parameter effect
/// falls outside the AST's closed vocabulary — the one thing Layer 2 can state
/// that the AST cannot represent.
pub fn project(doc: &LoweredDocument) -> Result<ast::Module, VerdictError> {
    let mut resources = Vec::with_capacity(doc.resources.len());
    for r in &doc.resources {
        resources.push(resource(r)?);
    }
    let mut externs = Vec::with_capacity(doc.externs.len());
    for e in &doc.externs {
        externs.push(extern_decl(e)?);
    }
    Ok(ast::Module {
        name: doc.module.clone(),
        resources,
        externs,
        functions: doc.functions.iter().map(function).collect(),
        // The bridge never emits a policy declaration, and `project_lowered`
        // refuses to serialize a module that has one — so an empty vector is
        // the recovered value, not a stand-in for an unknown one.
        policies: Vec::new(),
        lifetimes: doc.lifetimes.iter().map(lifetime).collect(),
    })
}

fn resource(r: &Resource) -> Result<ast::ResourceDecl, VerdictError> {
    let mut members = Vec::with_capacity(r.members.len());
    for m in &r.members {
        members.push(ast::ResourceMember {
            role: member_role(&m.role, &r.name)?,
            name: m.name.clone(),
            line: ELIDED,
        });
    }
    Ok(ast::ResourceDecl {
        name: r.name.clone(),
        members,
        line: ELIDED,
        // Emission templates are codegen state the prelude never carries; the
        // forward projection rejects a resource that has any.
        emit_type: None,
        emit_acquire: None,
        emit_release: None,
        emit_borrow: None,
        kind: r.kind.clone(),
    })
}

/// `"acquire"` / `"release"` — `ast_nodes.ResourceMember.role` is a `str`, and
/// the forward projection copies it verbatim, so the vocabulary is exactly the
/// two literals `_prelude_resources()` writes.
fn member_role(role: &str, resource_name: &str) -> Result<ast::MemberRole, VerdictError> {
    match role {
        "acquire" => Ok(ast::MemberRole::Acquire),
        "release" => Ok(ast::MemberRole::Release),
        other => Err(VerdictError(format!(
            "unprojectable member role '{other}' on resource '{resource_name}' — \
             Layer 2 carries the role as text and the AST's MemberRole is closed \
             at acquire/release"
        ))),
    }
}

fn extern_decl(e: &Extern) -> Result<ast::ExternDecl, VerdictError> {
    let mut params = Vec::with_capacity(e.params.len());
    for p in &e.params {
        params.push(ast::EffectParam {
            effect: effect(&p.effect, &e.name)?,
            type_name: p.type_name.clone(),
            line: ELIDED,
        });
    }
    Ok(ast::ExternDecl {
        name: e.name.clone(),
        params,
        // The sink externs are void; the forward projection rejects a return
        // type rather than dropping one.
        ret: None,
        line: ELIDED,
    })
}

/// The four `ast_nodes.Effect` members, lowercased — the forward projection
/// writes `p.effect.name.lower()`, so the vocabulary is the enum's, not the
/// bridge's. `plain` is included because it is a member: the sink externs never
/// use it, and the projection is not the place to encode which subset one
/// producer happens to reach.
fn effect(name: &str, extern_name: &str) -> Result<ast::Effect, VerdictError> {
    match name {
        "borrow" => Ok(ast::Effect::Borrow),
        "borrow_mut" => Ok(ast::Effect::BorrowMut),
        "consume" => Ok(ast::Effect::Consume),
        "plain" => Ok(ast::Effect::Plain),
        other => Err(VerdictError(format!(
            "unprojectable parameter effect '{other}' on extern '{extern_name}' — \
             Layer 2 carries the effect as text and the AST's Effect is closed at \
             borrow/borrow_mut/consume/plain"
        ))),
    }
}

fn lifetime(lt: &Lifetime) -> ast::LifetimeDecl {
    ast::LifetimeDecl {
        name: lt.name.clone(),
        longer: lt.longer.clone(),
        line: ELIDED,
    }
}

fn function(fun: &Function) -> ast::FnDecl {
    ast::FnDecl {
        name: fun.name.clone(),
        params: fun.params.iter().map(param).collect(),
        ret: fun.ret.as_ref().map(type_ref),
        body: fun.body.iter().map(stmt).collect(),
        line: ELIDED,
        lifetime: fun.lifetime.clone(),
    }
}

/// The one carried coordinate on this path: `Param.line` is `i64` in Layer 2
/// and [`SourceLine`] is `i64`, so the whole signed band crosses exactly — no
/// `try_from`, no clamp, no sentinel. The param's *type* keeps the elided line,
/// because `TypeRef.line` is never passed by the bridge.
fn param(p: &Param) -> ast::Param {
    ast::Param {
        name: p.handle.clone(),
        ty: type_ref(&p.type_shape),
        line: SourceLine(p.line),
        lifetime: p.lifetime.clone(),
    }
}

fn type_ref(t: &TypeShape) -> ast::TypeRef {
    ast::TypeRef {
        name: t.name.clone(),
        borrowed: t.borrowed,
        mutable: t.mutable,
        line: ELIDED,
    }
}

/// Layer 2's closed statement vocabulary → the AST's. Total by construction:
/// both enums are closed, and every Layer 2 variant names exactly one AST node
/// the bridge emits.
fn stmt(s: &Stmt) -> ast::Stmt {
    match s {
        // `Let(handle, Acquire(resource, [], line), line)` — one line, both
        // nodes, at all four construction sites in the reference.
        Stmt::Acquire {
            handle,
            resource,
            line,
        } => ast::Stmt::Let(ast::Let {
            name: handle.clone(),
            rhs: ast::Expr::Acquire(ast::Acquire {
                resource: resource.clone(),
                args: Vec::new(),
                line: SourceLine(*line),
            }),
            line: SourceLine(*line),
        }),
        Stmt::Release { handle, line } => ast::Stmt::Release(ast::Release {
            var: handle.clone(),
            line: SourceLine(*line),
        }),
        Stmt::Use { handle, line } => ast::Stmt::Use(ast::Use {
            var: handle.clone(),
            line: SourceLine(*line),
        }),
        Stmt::Overspan { handle, line } => ast::Stmt::Overspan(ast::Overspan {
            var: handle.clone(),
            line: SourceLine(*line),
        }),
        Stmt::Return { handle, line } => ast::Stmt::Return(ast::Return {
            var: handle.clone(),
            line: SourceLine(*line),
        }),
        Stmt::AliasJoin { handle, src, line } => ast::Stmt::AliasJoin(ast::AliasJoin {
            name: handle.clone(),
            src: src.clone(),
            line: SourceLine(*line),
        }),
        Stmt::Call { callee, args, line } => ast::Stmt::Call(ast::Call {
            callee: callee.clone(),
            args: args
                .iter()
                .map(|a| {
                    ast::Expr::VarRef(ast::VarRef {
                        name: a.clone(),
                        line: SourceLine(*line),
                    })
                })
                .collect(),
            line: SourceLine(*line),
        }),
        Stmt::Subscribe { source, line } => ast::Stmt::Subscribe(ast::Subscribe {
            source: source.clone(),
            line: SourceLine(*line),
        }),
        Stmt::If {
            cond,
            then,
            r#else,
            line,
        } => ast::Stmt::If(ast::If {
            cond_text: cond.clone(),
            then_body: then.iter().map(stmt).collect(),
            else_body: r#else.iter().map(stmt).collect(),
            line: SourceLine(*line),
        }),
        Stmt::While { cond, body, line } => ast::Stmt::While(ast::While {
            cond_text: cond.clone(),
            body: body.iter().map(stmt).collect(),
            line: SourceLine(*line),
        }),
    }
}
