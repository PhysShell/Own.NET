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
//! **The coordinate boundary that used to live here is gone**, and it is worth
//! saying how rather than just that. The core's line domain is `u32` (a
//! parser-derived position); the reference's was every signed 64-bit integer,
//! so a fact coordinate could be one the core could not hold, and this module
//! refused the document — a declared, measured cp4 divergence family.
//!
//! #259's final acceptance closed it from the reference's side, not from
//! this one: `spec/OwnIR.md` §4.2 now bounds every line to `[0, 2147483647]`,
//! the int32 domain every consumer this project feeds actually has. So a
//! document that passes the strict door is inside `u32` by construction, and
//! the only remaining out-of-domain coordinate arrives through the TOLERANT
//! door — where the reference degrades it to `0` and [`core_line`] does the
//! same. Never "Rust holds `u32`, so the reference is wrong": the contract
//! moved because of what its consumers are, and the port follows it.

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

/// A fact coordinate as a core line: in the §4.2 domain, or degraded to `0`.
///
/// This is the reference's `_as_line` (`ownlang/ownir.py`), member for member:
/// a line outside `[0, 2147483647]` reads as `0` — "unknown / file-level", the
/// value an absent line already reads as — and everything inside it travels
/// unchanged.
///
/// **Degrade, never clamp.** `2147483648` does not become `2147483647` and
/// `-1` does not become `1`: a clamp moves the finding to a REAL line the
/// producer did not mean, which is worse than saying nothing. That is §4.1's
/// never-invent rule for columns, applied to lines by §4.2.
///
/// It is INFALLIBLE, and the signature says so. It used to return a
/// `BridgeError` naming the node, so every caller carried a `?` and the whole
/// AST build was fallible for a reason that no longer exists; keeping the
/// `Result` would leave a refusal path the ledger could no longer reach and
/// no test could ever exercise.
pub(crate) fn core_line(line: i64) -> u32 {
    match u32::try_from(line) {
        Ok(n) if n <= LINE_MAX => n,
        _ => 0,
    }
}

/// The top of the §4.2 line domain as the core holds it. Pinned as a literal
/// beside the `u32` conversion rather than imported: this is the number the
/// core's own type has to agree with, and a constant that moved with the
/// contract could not detect that it stopped.
const LINE_MAX: u32 = 2_147_483_647;

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

fn param(p: &Param) -> own_syntax::ast::Param {
    own_syntax::ast::Param {
        name: p.handle.clone(),
        ty: type_ref(&p.type_shape),
        line: core_line(p.line),
        lifetime: p.lifetime.clone(),
    }
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
            let line = core_line(*line);
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
            line: core_line(*line),
        }),
        Stmt::Use { handle, line } => AstStmt::Use(Use {
            var: handle.clone(),
            line: core_line(*line),
        }),
        Stmt::Overspan { handle, line } => AstStmt::Overspan(Overspan {
            var: handle.clone(),
            line: core_line(*line),
        }),
        Stmt::Return { handle, line } => AstStmt::Return(Return {
            var: handle.clone(),
            line: core_line(*line),
        }),
        Stmt::AliasJoin { handle, src, line } => AstStmt::AliasJoin(AliasJoin {
            name: handle.clone(),
            src: src.clone(),
            line: core_line(*line),
        }),
        Stmt::Call { callee, args, line } => {
            // Python: `VarRef(localmap.get(a, a), line)` — every argument is a
            // name reference carrying the CALL's line.
            let line = core_line(*line);
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
            line: core_line(*line),
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
            line: core_line(*line),
        }),
        Stmt::While { cond, body, line } => AstStmt::While(While {
            cond_text: cond.clone(),
            body: stmts(body)?,
            line: core_line(*line),
        }),
    })
}

fn function(f: &Function) -> Result<FnDecl, BridgeError> {
    Ok(FnDecl {
        name: f.name.clone(),
        params: f.params.iter().map(param).collect(),
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
/// [`BridgeError`] for a Layer 2 vocabulary value with no core twin
/// (unreachable for a document the lowering itself produced). A coordinate
/// outside the core's line domain is no longer among them — see [`core_line`]
/// and the module docs: §4.2 gave the reference the same domain, and both
/// tolerant doors now degrade rather than refuse.
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

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]
mod tests {
    use super::{core_line, LINE_MAX};

    /// [`core_line`]'s contract, pinned directly — and the reason it is pinned
    /// directly rather than through `check_facts` is worth stating, because a
    /// unit test on the function under test is normally the weak kind of
    /// evidence this project refuses.
    ///
    /// It cannot be reached from the outside any more. `lower` reads every
    /// fact coordinate through `as_line`, so the Layer 2 document this builds
    /// from is already inside the domain, and every out-of-domain value dies
    /// one layer earlier. That makes this a SECOND line of defence over an
    /// `i64` field wider than the domain — real (nothing in the type stops a
    /// future caller handing it one) and unobservable end to end. A mutation
    /// campaign proved exactly that: clamping here, or accepting the whole
    /// `u32` range again, changed no golden. So the honest control is this
    /// one, and the honest record is that it is not an end-to-end control.
    #[test]
    fn core_line_degrades_the_domain_and_never_clamps() {
        assert_eq!(
            core_line(0),
            0,
            "zero is the domain's bottom, not a degrade"
        );
        assert_eq!(core_line(1), 1);
        assert_eq!(core_line(i64::from(LINE_MAX)), LINE_MAX, "the top travels");
        // …and one step past each end degrades to ABSENT, not to the edge.
        assert_eq!(core_line(-1), 0);
        assert_eq!(
            core_line(i64::from(LINE_MAX) + 1),
            0,
            "never clamped to the top"
        );
        assert_eq!(
            core_line(i64::from(u32::MAX)),
            0,
            "the core's own u32 is not the domain"
        );
        assert_eq!(core_line(i64::MIN), 0);
        assert_eq!(core_line(i64::MAX), 0);
    }
}
