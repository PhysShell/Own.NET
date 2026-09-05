//! Layer 2 → the core AST: the `own_syntax::ast::Module` that Python's
//! `to_module` hands `check_module`, rebuilt from the normalized lowered
//! document (#259 cp4).
//!
//! The Layer 2 projection (`ownlang/lowered.py`) is lossless for everything
//! the analyses read: every node line the bridge carries is serialized, and
//! the lines it drops are the ones `to_module` fixes at `0` — resource,
//! extern, lifetime and function declarations, capture params, and every
//! `TypeRef`. So building the AST from the proven Layer 2 document (27/27
//! byte-exact against the reference) rather than from the facts a second time
//! composes the checkpoint-2 evidence instead of re-deriving it: a lowering
//! bug is visible at the Layer 2 seam before it can hide behind a verdict.
//!
//! **The one representability boundary lives here.** The core's line domain
//! is `u32` (a parser-derived position), while a fact coordinate on the
//! tolerant door is any integer the reference's `_as_int` passes through, and
//! even the strict door admits every signed 64-bit value (`spec/OwnIR.md`
//! §4.2). A coordinate outside `0..=u32::MAX` on a lowered node is therefore
//! refused loudly — a Rust-only rejection of a document the reference
//! analyzes, declared and measured as a cp4 divergence family (the verdict
//! fixture ledger pins it), never clamped or silently dropped.

// `redundant_pub_crate` (nursery) conflicts with the workspace's DENY of
// `unreachable_pub` for items in private modules; pub(crate) is the honest
// visibility here (same stance as `mos.rs`).
#![allow(clippy::redundant_pub_crate)]

use crate::BridgeError;
use own_lowered::{Function, LoweredDocument, Param, Stmt, TypeShape};
use own_syntax::ast::{
    Acquire, AliasJoin, Call, Effect, EffectParam, Expr, ExternDecl, FnDecl, If, Let, LifetimeDecl,
    MemberRole, Module, Overspan, Release, ResourceDecl, ResourceMember, Return, Stmt as AstStmt,
    Subscribe, TypeRef, Use, VarRef, While,
};

/// `u32` or refuse: the declared coordinate boundary (see the module docs).
pub(crate) fn core_line(line: i64, what: &str) -> Result<u32, BridgeError> {
    u32::try_from(line).map_err(|_| {
        BridgeError(format!(
            "source line {line} on {what} is outside the core's line domain \
             (0..=4294967295): the reference analyzes this coordinate, this core \
             cannot represent it — a declared #259 cp4 divergence family, not a \
             silent clamp (spec/OwnIR.md §4.2 bounds coordinates to signed 64 bits)"
        ))
    })
}

fn type_ref(t: &TypeShape) -> TypeRef {
    TypeRef {
        name: t.name.clone(),
        borrowed: t.borrowed,
        mutable: t.mutable,
        line: 0,
    }
}

fn effect(name: &str) -> Result<Effect, BridgeError> {
    match name {
        "consume" => Ok(Effect::Consume),
        "borrow" => Ok(Effect::Borrow),
        "borrow_mut" => Ok(Effect::BorrowMut),
        "plain" => Ok(Effect::Plain),
        other => Err(BridgeError(format!(
            "Layer 2 extern effect {other:?} has no core Effect — the lowering emits \
             only consume/borrow/borrow_mut/plain"
        ))),
    }
}

fn member_role(role: &str) -> Result<MemberRole, BridgeError> {
    match role {
        "acquire" => Ok(MemberRole::Acquire),
        "release" => Ok(MemberRole::Release),
        other => Err(BridgeError(format!(
            "Layer 2 resource member role {other:?} has no core MemberRole"
        ))),
    }
}

fn param(p: &Param) -> Result<own_syntax::ast::Param, BridgeError> {
    Ok(own_syntax::ast::Param {
        name: p.handle.clone(),
        ty: type_ref(&p.type_shape),
        line: core_line(p.line, &format!("param '{}'", p.handle))?,
        lifetime: p.lifetime.clone(),
    })
}

fn stmts(body: &[Stmt]) -> Result<Vec<AstStmt>, BridgeError> {
    body.iter().map(stmt).collect()
}

fn stmt(s: &Stmt) -> Result<AstStmt, BridgeError> {
    Ok(match s {
        Stmt::Acquire {
            handle,
            resource,
            line,
        } => {
            let line = core_line(*line, &format!("acquire of '{handle}'"))?;
            AstStmt::Let(Let {
                name: handle.clone(),
                rhs: Expr::Acquire(Acquire {
                    resource: resource.clone(),
                    args: Vec::new(),
                    line,
                }),
                line,
            })
        }
        Stmt::Release { handle, line } => AstStmt::Release(Release {
            var: handle.clone(),
            line: core_line(*line, &format!("release of '{handle}'"))?,
        }),
        Stmt::Use { handle, line } => AstStmt::Use(Use {
            var: handle.clone(),
            line: core_line(*line, &format!("use of '{handle}'"))?,
        }),
        Stmt::Overspan { handle, line } => AstStmt::Overspan(Overspan {
            var: handle.clone(),
            line: core_line(*line, &format!("overspan of '{handle}'"))?,
        }),
        Stmt::Return { handle, line } => AstStmt::Return(Return {
            var: handle.clone(),
            line: core_line(*line, "return")?,
        }),
        Stmt::AliasJoin { handle, src, line } => AstStmt::AliasJoin(AliasJoin {
            name: handle.clone(),
            src: src.clone(),
            line: core_line(*line, &format!("alias_join of '{handle}'"))?,
        }),
        Stmt::Call { callee, args, line } => {
            // Python: `VarRef(localmap.get(a, a), line)` — every argument is a
            // name reference carrying the CALL's line.
            let line = core_line(*line, &format!("call to '{callee}'"))?;
            AstStmt::Call(Call {
                callee: callee.clone(),
                args: args
                    .iter()
                    .map(|a| {
                        Expr::VarRef(VarRef {
                            name: a.clone(),
                            line,
                        })
                    })
                    .collect(),
                line,
            })
        }
        Stmt::Subscribe { source, line } => AstStmt::Subscribe(Subscribe {
            source: source.clone(),
            line: core_line(*line, &format!("subscribe to '{source}'"))?,
        }),
        Stmt::If {
            cond,
            then,
            r#else,
            line,
        } => AstStmt::If(If {
            cond_text: cond.clone(),
            then_body: stmts(then)?,
            else_body: stmts(r#else)?,
            line: core_line(*line, "if")?,
        }),
        Stmt::While { cond, body, line } => AstStmt::While(While {
            cond_text: cond.clone(),
            body: stmts(body)?,
            line: core_line(*line, "while")?,
        }),
    })
}

fn function(f: &Function) -> Result<FnDecl, BridgeError> {
    Ok(FnDecl {
        name: f.name.clone(),
        params: f.params.iter().map(param).collect::<Result<_, _>>()?,
        ret: f.ret.as_ref().map(type_ref),
        body: stmts(&f.body)?,
        line: 0,
        lifetime: f.lifetime.clone(),
    })
}

/// Rebuild the core `Module` from a Layer 2 document — the AST `to_module`
/// returns, node for node (declaration lines fixed at `0`, exactly as the
/// reference constructs them).
///
/// # Errors
/// [`BridgeError`] for a coordinate outside the core's `u32` line domain (the
/// declared boundary above), or a Layer 2 vocabulary value with no core twin
/// (unreachable for a document the lowering itself produced).
pub(crate) fn to_module(doc: &LoweredDocument) -> Result<Module, BridgeError> {
    let resources = doc
        .resources
        .iter()
        .map(|r| {
            Ok(ResourceDecl {
                name: r.name.clone(),
                members: r
                    .members
                    .iter()
                    .map(|m| {
                        Ok(ResourceMember {
                            role: member_role(&m.role)?,
                            name: m.name.clone(),
                            line: 0,
                        })
                    })
                    .collect::<Result<_, BridgeError>>()?,
                line: 0,
                emit_type: None,
                emit_acquire: None,
                emit_release: None,
                emit_borrow: None,
                kind: r.kind.clone(),
            })
        })
        .collect::<Result<Vec<_>, BridgeError>>()?;
    let externs = doc
        .externs
        .iter()
        .map(|e| {
            Ok(ExternDecl {
                name: e.name.clone(),
                params: e
                    .params
                    .iter()
                    .map(|p| {
                        Ok(EffectParam {
                            effect: effect(&p.effect)?,
                            type_name: p.type_name.clone(),
                            line: 0,
                        })
                    })
                    .collect::<Result<_, BridgeError>>()?,
                ret: None,
                line: 0,
            })
        })
        .collect::<Result<Vec<_>, BridgeError>>()?;
    let lifetimes = doc
        .lifetimes
        .iter()
        .map(|lt| LifetimeDecl {
            name: lt.name.clone(),
            longer: lt.longer.clone(),
            line: 0,
        })
        .collect();
    Ok(Module {
        name: doc.module.clone(),
        resources,
        externs,
        functions: doc
            .functions
            .iter()
            .map(function)
            .collect::<Result<_, _>>()?,
        policies: Vec::new(),
        lifetimes,
    })
}
