//! Acceptance for the Layer 2 → analysis AST projection
//! (`own_verdicts::project`).
//!
//! The projection has no golden of its own and cannot get one: `Module` is an
//! in-memory type with no serialized form, and the only committed artifact on
//! this seam — `tests/fixtures/lowered/*.golden.json` — is the *input*. So the
//! acceptance is **demonstrated**: the expected AST is written out here, value
//! by value, from the reference bridge's construction (`ownlang/ownir.py`), and
//! compared against what the projection produces from the committed Layer 2
//! document.
//!
//! That direction matters. An assertion phrased over the projected value —
//! "the param's line equals the document's line" — restates the implementation
//! and passes for any consistent mapping, including a wrong one. Every
//! assertion below names the value it expects.
//!
//! Six groups:
//!
//! 1. the whole shape at once, against one committed golden;
//! 2. the statement vocabulary, one variant at a time, plus nesting;
//! 3. the elided coordinates — every line Layer 2 drops;
//! 4. the signed band — the carried coordinates, across the range the strict
//!    door accepts;
//! 5. the closed-vocabulary rejections, and the boundary they do NOT extend to;
//! 6. the corpus sweep — totality and structural conservation over every
//!    shared Layer 2 case.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing
)]

use own_cfg::ast;
use own_ir::span::SourceLine;
use own_lowered::{parse_document, LoweredDocument, Manifest, Surface};
use own_verdicts::project;

const FIXDIR: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/lowered"
);

fn read(name: &str) -> String {
    let path = format!("{FIXDIR}/{name}");
    std::fs::read_to_string(&path).unwrap_or_else(|e| {
        panic!(
            "cannot read {path}: {e} — regenerate: python tests/test_lowered_fixtures.py --write"
        )
    })
}

fn lowered(text: &str) -> LoweredDocument {
    match parse_document(text) {
        Ok(Surface::Lowered(doc)) => doc,
        Ok(Surface::Rejected(r)) => panic!("expected a lowered document, got a rejection: {r:?}"),
        Err(e) => panic!("Layer 2 text does not parse: {e}"),
    }
}

/// A minimal Layer 2 document carrying one function with the given body.
///
/// The envelope is deliberately empty (no prelude, no externs, no handles):
/// these groups are about statements and coordinates, and a document does not
/// have to be one the bridge would emit for the projection to be defined on it.
fn with_body(body: &str) -> LoweredDocument {
    lowered(&format!(
        r#"{{"lowered_version": 1, "module": "T", "resources": [], "externs": [],
            "lifetimes": [], "functions": [{{"name": "F", "lifetime": null,
            "params": [], "ret": null, "body": [{body}]}}], "handles": []}}"#
    ))
}

/// Project a one-statement body and hand back that statement.
fn one_stmt(body: &str) -> ast::Stmt {
    let module = project(&with_body(body)).expect("a closed statement projects");
    assert_eq!(
        module.functions.len(),
        1,
        "the envelope declares exactly one function"
    );
    assert_eq!(
        module.functions[0].body.len(),
        1,
        "one Layer 2 statement must become exactly one AST statement"
    );
    module.functions[0].body[0].clone()
}

// ---------------------------------------------------------------------------
// Group 1 — the whole shape, against a committed golden
// ---------------------------------------------------------------------------

/// `routing_r5_di_capture` is the widest single case in the ledger: module
/// identity, all four prelude resources with both member roles, all three sink
/// externs with three distinct effects, a four-node lifetime graph, and a
/// function carrying a lifetime, a typed param with a region, a void return and
/// two statement kinds.
///
/// The expected `Module` is transcribed from `ownlang/ownir.py` — the prelude
/// literals (`_prelude_resources`, `_OWNERSHIP_SINK_EXTERNS`,
/// `_CAPTURE_LIFETIMES`) and the `to_module` construction that reads
/// `TypeRef("EventSource", False, False, 0)` and `FnDecl(…, 0, …)`.
// The length IS the test: an expected `Module` written out node by node is the
// only form in which "the whole shape at once" is a checkable claim. Splitting
// it into per-section helpers would restore exactly the piecemeal comparison
// the other groups already do.
#[allow(clippy::too_many_lines)]
#[test]
fn projects_a_committed_golden_to_the_module_the_reference_builds() {
    let doc = lowered(&read("routing_r5_di_capture.golden.json"));

    let expected = ast::Module {
        name: "R5".to_owned(),
        resources: vec![
            ast::ResourceDecl {
                name: "Subscription".to_owned(),
                members: vec![
                    ast::ResourceMember {
                        role: ast::MemberRole::Acquire,
                        name: "Subscribe".to_owned(),
                        line: SourceLine(0),
                    },
                    ast::ResourceMember {
                        role: ast::MemberRole::Release,
                        name: "Dispose".to_owned(),
                        line: SourceLine(0),
                    },
                ],
                line: SourceLine(0),
                emit_type: None,
                emit_acquire: None,
                emit_release: None,
                emit_borrow: None,
                kind: Some("subscription token".to_owned()),
            },
            ast::ResourceDecl {
                name: "Timer".to_owned(),
                members: vec![
                    ast::ResourceMember {
                        role: ast::MemberRole::Acquire,
                        name: "Start".to_owned(),
                        line: SourceLine(0),
                    },
                    ast::ResourceMember {
                        role: ast::MemberRole::Release,
                        name: "Stop".to_owned(),
                        line: SourceLine(0),
                    },
                ],
                line: SourceLine(0),
                emit_type: None,
                emit_acquire: None,
                emit_release: None,
                emit_borrow: None,
                kind: Some("timer".to_owned()),
            },
            ast::ResourceDecl {
                name: "Disposable".to_owned(),
                members: vec![
                    ast::ResourceMember {
                        role: ast::MemberRole::Acquire,
                        name: "New".to_owned(),
                        line: SourceLine(0),
                    },
                    ast::ResourceMember {
                        role: ast::MemberRole::Release,
                        name: "Dispose".to_owned(),
                        line: SourceLine(0),
                    },
                ],
                line: SourceLine(0),
                emit_type: None,
                emit_acquire: None,
                emit_release: None,
                emit_borrow: None,
                kind: Some("disposable field".to_owned()),
            },
            ast::ResourceDecl {
                name: "PooledBuffer".to_owned(),
                members: vec![
                    ast::ResourceMember {
                        role: ast::MemberRole::Acquire,
                        name: "Rent".to_owned(),
                        line: SourceLine(0),
                    },
                    ast::ResourceMember {
                        role: ast::MemberRole::Release,
                        name: "Return".to_owned(),
                        line: SourceLine(0),
                    },
                ],
                line: SourceLine(0),
                emit_type: None,
                emit_acquire: None,
                emit_release: None,
                emit_borrow: None,
                kind: Some("pooled buffer".to_owned()),
            },
        ],
        externs: vec![
            ast::ExternDecl {
                name: "$consume".to_owned(),
                params: vec![ast::EffectParam {
                    effect: ast::Effect::Consume,
                    type_name: "Disposable".to_owned(),
                    line: SourceLine(0),
                }],
                ret: None,
                line: SourceLine(0),
            },
            ast::ExternDecl {
                name: "$borrow".to_owned(),
                params: vec![ast::EffectParam {
                    effect: ast::Effect::Borrow,
                    type_name: "Disposable".to_owned(),
                    line: SourceLine(0),
                }],
                ret: None,
                line: SourceLine(0),
            },
            ast::ExternDecl {
                name: "$borrow_mut".to_owned(),
                params: vec![ast::EffectParam {
                    effect: ast::Effect::BorrowMut,
                    type_name: "Disposable".to_owned(),
                    line: SourceLine(0),
                }],
                ret: None,
                line: SourceLine(0),
            },
        ],
        functions: vec![ast::FnDecl {
            name: "VM".to_owned(),
            params: vec![ast::Param {
                name: "cap_0".to_owned(),
                ty: ast::TypeRef {
                    name: "EventSource".to_owned(),
                    borrowed: false,
                    mutable: false,
                    line: SourceLine(0),
                },
                line: SourceLine(0),
                lifetime: Some("Process".to_owned()),
            }],
            ret: None,
            body: vec![
                ast::Stmt::Subscribe(ast::Subscribe {
                    source: "cap_0".to_owned(),
                    line: SourceLine(10),
                }),
                ast::Stmt::Let(ast::Let {
                    name: "sub_1".to_owned(),
                    rhs: ast::Expr::Acquire(ast::Acquire {
                        resource: "Subscription".to_owned(),
                        args: Vec::new(),
                        line: SourceLine(11),
                    }),
                    line: SourceLine(11),
                }),
            ],
            line: SourceLine(0),
            lifetime: Some("scoped".to_owned()),
        }],
        policies: Vec::new(),
        lifetimes: vec![
            ast::LifetimeDecl {
                name: "Process".to_owned(),
                longer: None,
                line: SourceLine(0),
            },
            ast::LifetimeDecl {
                name: "scoped".to_owned(),
                longer: Some("Process".to_owned()),
                line: SourceLine(0),
            },
            ast::LifetimeDecl {
                name: "transient".to_owned(),
                longer: Some("scoped".to_owned()),
                line: SourceLine(0),
            },
            ast::LifetimeDecl {
                name: "Subscriber".to_owned(),
                longer: Some("Process".to_owned()),
                line: SourceLine(0),
            },
        ],
    };

    assert_eq!(project(&doc).expect("a shared golden projects"), expected);
}

/// An owned return type is the second `ret` state, and `flow_unmapped_refs` is
/// the case that has one — together with the bare `return` that makes the
/// `Option<String>` handle meaningful.
#[test]
fn projects_an_owned_return_type_and_a_bare_return() {
    let doc = lowered(&read("flow_unmapped_refs.golden.json"));
    let module = project(&doc).expect("a shared golden projects");

    assert_eq!(module.functions.len(), 1, "the case declares one function");
    assert_eq!(
        module.functions[0].ret,
        Some(ast::TypeRef {
            name: "Disposable".to_owned(),
            borrowed: false,
            mutable: false,
            line: SourceLine(0),
        }),
        "a value-returning body gets the owned `Disposable` return type"
    );
    assert_eq!(
        module.functions[0].body,
        vec![ast::Stmt::Return(ast::Return {
            var: None,
            line: SourceLine(5),
        })],
        "a bare return carries no variable"
    );
}

/// A param's type SHAPE is its ownership contract, not decoration:
/// `own_cfg::collect_signatures` reads `borrowed`/`mutable`/`name` off
/// `Param.ty` to decide `BorrowMut` / `Borrow` / `Consume` / `Plain` for every
/// argument at every call site. A projection that dropped either flag would
/// silently turn a loan into a transfer — visible only as a wrong verdict, two
/// layers away.
///
/// `fn_params_ordering` is the case that carries all four `_PARAM_EFFECT_TYPE`
/// shapes, in one function, in the order the reference mints them.
#[test]
fn param_type_shapes_carry_the_ownership_contract() {
    let doc = lowered(&read("fn_params_ordering.golden.json"));
    let module = project(&doc).expect("a shared golden projects");

    let disposable = |borrowed: bool, mutable: bool| ast::TypeRef {
        name: "Disposable".to_owned(),
        borrowed,
        mutable,
        line: SourceLine(0),
    };
    assert_eq!(
        module.functions[0].params,
        vec![
            // consume: an owned resource type
            ast::Param {
                name: "parg_0".to_owned(),
                ty: disposable(false, false),
                line: SourceLine(1),
                lifetime: None,
            },
            // borrow: `&T`
            ast::Param {
                name: "parg_1".to_owned(),
                ty: disposable(true, false),
                line: SourceLine(1),
                lifetime: None,
            },
            // borrow_mut: `&mut T`
            ast::Param {
                name: "parg_2".to_owned(),
                ty: disposable(true, true),
                line: SourceLine(1),
                lifetime: None,
            },
            // plain: a non-resource type
            ast::Param {
                name: "parg_3".to_owned(),
                ty: ast::TypeRef {
                    name: "int".to_owned(),
                    borrowed: false,
                    mutable: false,
                    line: SourceLine(0),
                },
                line: SourceLine(1),
                lifetime: None,
            },
        ],
        "the four param shapes, in mint order"
    );
}

/// The bridge never builds a policy declaration, and the forward projection
/// refuses to serialize a module that has one — so the empty vector is a
/// recovered value, and a projection that started inventing policies would be
/// producing a module the reference cannot.
#[test]
fn a_projected_module_never_carries_policies() {
    let doc = lowered(&read("hoist_pool_kind.golden.json"));
    assert_eq!(
        project(&doc).expect("a shared golden projects").policies,
        Vec::new(),
        "Layer 2 has no policy channel and the reference emits none"
    );
}

// ---------------------------------------------------------------------------
// Group 2 — the statement vocabulary
// ---------------------------------------------------------------------------

#[test]
fn acquire_becomes_a_let_of_an_argument_free_acquire() {
    assert_eq!(
        one_stmt(r#"{"stmt": "acquire", "handle": "h", "resource": "Timer", "line": 7}"#),
        ast::Stmt::Let(ast::Let {
            name: "h".to_owned(),
            rhs: ast::Expr::Acquire(ast::Acquire {
                resource: "Timer".to_owned(),
                args: Vec::new(),
                line: SourceLine(7),
            }),
            // `Let(handle, Acquire(resource, [], line), line)` — the reference
            // passes ONE line to both nodes.
            line: SourceLine(7),
        })
    );
}

#[test]
fn release_use_and_overspan_become_their_single_variable_nodes() {
    assert_eq!(
        one_stmt(r#"{"stmt": "release", "handle": "h", "line": 2}"#),
        ast::Stmt::Release(ast::Release {
            var: "h".to_owned(),
            line: SourceLine(2),
        })
    );
    assert_eq!(
        one_stmt(r#"{"stmt": "use", "handle": "h", "line": 3}"#),
        ast::Stmt::Use(ast::Use {
            var: "h".to_owned(),
            line: SourceLine(3),
        })
    );
    assert_eq!(
        one_stmt(r#"{"stmt": "overspan", "handle": "h", "line": 4}"#),
        ast::Stmt::Overspan(ast::Overspan {
            var: "h".to_owned(),
            line: SourceLine(4),
        })
    );
}

#[test]
fn return_carries_the_handle_when_there_is_one() {
    assert_eq!(
        one_stmt(r#"{"stmt": "return", "handle": "h", "line": 9}"#),
        ast::Stmt::Return(ast::Return {
            var: Some("h".to_owned()),
            line: SourceLine(9),
        })
    );
}

#[test]
fn alias_join_keeps_the_new_handle_and_its_source_apart() {
    assert_eq!(
        one_stmt(r#"{"stmt": "alias_join", "handle": "new", "src": "old", "line": 5}"#),
        ast::Stmt::AliasJoin(ast::AliasJoin {
            // The two fields are same-typed and adjacent: swapping them is a
            // silent alias inversion, so they are asserted with distinct values.
            name: "new".to_owned(),
            src: "old".to_owned(),
            line: SourceLine(5),
        })
    );
}

#[test]
fn call_arguments_become_var_refs_at_the_call_line() {
    assert_eq!(
        one_stmt(r#"{"stmt": "call", "callee": "Sink", "args": ["a", "b"], "line": 12}"#),
        ast::Stmt::Call(ast::Call {
            callee: "Sink".to_owned(),
            // Layer 2 keeps only the name; the reference mints every argument
            // as `VarRef(name, line)` with the CALL's line.
            args: vec![
                ast::Expr::VarRef(ast::VarRef {
                    name: "a".to_owned(),
                    line: SourceLine(12),
                }),
                ast::Expr::VarRef(ast::VarRef {
                    name: "b".to_owned(),
                    line: SourceLine(12),
                }),
            ],
            line: SourceLine(12),
        })
    );
}

/// The callee routes the call: `own_cfg::lower_call` resolves it against the
/// signature table, where a first-party name and a `$consume`/`$borrow`/
/// `$borrow_mut` channel land in different places. Two distinct callees in one
/// body, so no single hard-coded name can satisfy the assertion.
#[test]
fn distinct_callees_are_carried_verbatim() {
    let doc = with_body(
        r#"{"stmt": "call", "callee": "Alpha", "args": [], "line": 1},
           {"stmt": "call", "callee": "$borrow_mut", "args": [], "line": 2}"#,
    );
    let module = project(&doc).expect("the document projects");
    assert_eq!(
        module.functions[0].body,
        vec![
            ast::Stmt::Call(ast::Call {
                callee: "Alpha".to_owned(),
                args: Vec::new(),
                line: SourceLine(1),
            }),
            ast::Stmt::Call(ast::Call {
                callee: "$borrow_mut".to_owned(),
                args: Vec::new(),
                line: SourceLine(2),
            }),
        ]
    );
}

#[test]
fn subscribe_becomes_the_region_escape_node() {
    assert_eq!(
        one_stmt(r#"{"stmt": "subscribe", "source": "cap_0", "line": 10}"#),
        ast::Stmt::Subscribe(ast::Subscribe {
            source: "cap_0".to_owned(),
            line: SourceLine(10),
        })
    );
}

/// `if` with both arms populated and a statement nested two levels down. A
/// projection that recursed into `then` only, or that flattened the arms, would
/// still satisfy a one-armed case.
#[test]
fn if_projects_both_arms_recursively() {
    assert_eq!(
        one_stmt(
            r#"{"stmt": "if", "cond": "?",
                "then": [{"stmt": "if", "cond": "??",
                          "then": [{"stmt": "use", "handle": "deep", "line": 4}],
                          "else": [], "line": 3}],
                "else": [{"stmt": "release", "handle": "e", "line": 6}],
                "line": 2}"#
        ),
        ast::Stmt::If(ast::If {
            cond_text: "?".to_owned(),
            then_body: vec![ast::Stmt::If(ast::If {
                cond_text: "??".to_owned(),
                then_body: vec![ast::Stmt::Use(ast::Use {
                    var: "deep".to_owned(),
                    line: SourceLine(4),
                })],
                else_body: Vec::new(),
                line: SourceLine(3),
            })],
            else_body: vec![ast::Stmt::Release(ast::Release {
                var: "e".to_owned(),
                line: SourceLine(6),
            })],
            line: SourceLine(2),
        })
    );
}

#[test]
fn while_projects_its_body_recursively() {
    assert_eq!(
        one_stmt(
            r#"{"stmt": "while", "cond": "?",
                "body": [{"stmt": "while", "cond": "??",
                          "body": [{"stmt": "use", "handle": "deep", "line": 4}],
                          "line": 3}],
                "line": 2}"#
        ),
        ast::Stmt::While(ast::While {
            cond_text: "?".to_owned(),
            body: vec![ast::Stmt::While(ast::While {
                cond_text: "??".to_owned(),
                body: vec![ast::Stmt::Use(ast::Use {
                    var: "deep".to_owned(),
                    line: SourceLine(4),
                })],
                line: SourceLine(3),
            })],
            line: SourceLine(2),
        })
    );
}

/// The condition is carried verbatim, not re-synthesized. The bridge always
/// emits the opaque `"?"`, so a projection that hard-coded it would pass every
/// corpus case; this states the contract instead.
#[test]
fn conditions_are_carried_verbatim() {
    let ast::Stmt::While(w) =
        one_stmt(r#"{"stmt": "while", "cond": "x != null && i < n", "body": [], "line": 1}"#)
    else {
        panic!("a Layer 2 `while` must project to an AST `While`");
    };
    assert_eq!(w.cond_text, "x != null && i < n");
}

// ---------------------------------------------------------------------------
// Group 3 — the elided coordinates
// ---------------------------------------------------------------------------

/// Every coordinate Layer 2 drops is a literal `0` in the reference. The
/// document below carries a *non-zero* line on every channel that does survive
/// (param `41`, statement `41`), so a projection that back-filled an elided
/// line from the nearest carried one is distinguishable from one that uses the
/// reference's constant.
#[test]
fn every_elided_coordinate_is_the_reference_zero() {
    let doc = lowered(
        r#"{"lowered_version": 1, "module": "M",
            "resources": [{"name": "R", "kind": "k",
                           "members": [{"role": "acquire", "name": "A"}]}],
            "externs": [{"name": "$consume",
                         "params": [{"effect": "consume", "type": "Disposable"}]}],
            "lifetimes": [{"name": "L", "longer": null}],
            "functions": [{"name": "F", "lifetime": null,
                           "params": [{"handle": "p",
                                       "type": {"name": "T", "borrowed": true,
                                                "mutable": true},
                                       "line": 41, "lifetime": null}],
                           "ret": {"name": "Disposable", "borrowed": false,
                                   "mutable": false},
                           "body": [{"stmt": "use", "handle": "p", "line": 41}]}],
            "handles": []}"#,
    );
    let m = project(&doc).expect("the document projects");

    assert_eq!(m.resources[0].line, SourceLine(0), "ResourceDecl.line");
    assert_eq!(
        m.resources[0].members[0].line,
        SourceLine(0),
        "ResourceMember.line"
    );
    assert_eq!(m.externs[0].line, SourceLine(0), "ExternDecl.line");
    assert_eq!(
        m.externs[0].params[0].line,
        SourceLine(0),
        "EffectParam.line"
    );
    assert_eq!(m.lifetimes[0].line, SourceLine(0), "LifetimeDecl.line");
    assert_eq!(m.functions[0].line, SourceLine(0), "FnDecl.line");
    assert_eq!(
        m.functions[0].params[0].ty.line,
        SourceLine(0),
        "the param TYPE's line — the param's own line is 41"
    );
    assert_eq!(
        m.functions[0].ret.as_ref().expect("a return type").line,
        SourceLine(0),
        "the return TYPE's line"
    );
}

/// The emission templates are the one elided group that is not a coordinate.
/// The forward projection *refuses* a resource carrying any of them, so `None`
/// is the recovered value rather than a lossy default.
#[test]
fn a_projected_resource_carries_no_emission_templates() {
    let doc = lowered(
        r#"{"lowered_version": 1, "module": "M",
            "resources": [{"name": "R", "kind": null, "members": []}],
            "externs": [], "lifetimes": [], "functions": [], "handles": []}"#,
    );
    let r = &project(&doc).expect("the document projects").resources[0];
    assert_eq!(r.emit_type, None);
    assert_eq!(r.emit_acquire, None);
    assert_eq!(r.emit_release, None);
    assert_eq!(r.emit_borrow, None);
    assert_eq!(
        r.kind, None,
        "a null `kind` is absence, not the string \"null\""
    );
}

// ---------------------------------------------------------------------------
// Group 4 — the signed band
// ---------------------------------------------------------------------------

/// The range `spec/OwnIR.md` §4.2 makes legal for a validated coordinate, and
/// therefore the range Layer 2 can hand this projection.
const BAND: [i64; 7] = [
    i64::MIN,
    -1,
    0,
    1,
    4_294_967_295, // u32::MAX
    4_294_967_296, // u32::MAX + 1 — the first value a u32 cannot hold
    i64::MAX,
];

/// `Param.line` is the one coordinate that crosses this seam carrying data.
/// Both sides are `i64`, so the crossing is exact — the inventory's whole point
/// was that a `u32` here would be the defect.
#[test]
fn a_param_line_crosses_the_whole_signed_band() {
    for line in BAND {
        let doc = lowered(&format!(
            r#"{{"lowered_version": 1, "module": "M", "resources": [], "externs": [],
                "lifetimes": [],
                "functions": [{{"name": "F", "lifetime": null,
                                "params": [{{"handle": "p",
                                             "type": {{"name": "T", "borrowed": false,
                                                       "mutable": false}},
                                             "line": {line}, "lifetime": null}}],
                                "ret": null, "body": []}}],
                "handles": []}}"#
        ));
        let m = project(&doc).unwrap_or_else(|e| panic!("param line {line} must project: {e}"));
        assert_eq!(
            m.functions[0].params[0].line,
            SourceLine(line),
            "param line {line} must arrive verbatim — no clamp, no sentinel"
        );
    }
}

/// Every statement carries a line, and each variant carries it through its own
/// constructor. Exercising one variant would leave a narrowing in any of the
/// other nine invisible.
#[test]
fn every_statement_line_crosses_the_whole_signed_band() {
    for line in BAND {
        let bodies = [
            format!(r#"{{"stmt": "acquire", "handle": "h", "resource": "R", "line": {line}}}"#),
            format!(r#"{{"stmt": "release", "handle": "h", "line": {line}}}"#),
            format!(r#"{{"stmt": "use", "handle": "h", "line": {line}}}"#),
            format!(r#"{{"stmt": "overspan", "handle": "h", "line": {line}}}"#),
            format!(r#"{{"stmt": "return", "handle": null, "line": {line}}}"#),
            format!(r#"{{"stmt": "alias_join", "handle": "n", "src": "s", "line": {line}}}"#),
            format!(r#"{{"stmt": "call", "callee": "C", "args": ["a"], "line": {line}}}"#),
            format!(r#"{{"stmt": "subscribe", "source": "s", "line": {line}}}"#),
            format!(r#"{{"stmt": "if", "cond": "?", "then": [], "else": [], "line": {line}}}"#),
            format!(r#"{{"stmt": "while", "cond": "?", "body": [], "line": {line}}}"#),
        ];
        assert_eq!(
            bodies.len(),
            10,
            "the Layer 2 statement vocabulary has ten variants — a new one must be swept too"
        );
        for body in &bodies {
            assert_eq!(
                stmt_line(&one_stmt(body)),
                SourceLine(line),
                "line {line} in {body}"
            );
        }
    }
}

/// A `call`'s arguments are minted at the call's line, so they must cross the
/// band too — a narrowing hidden in argument construction alone would survive
/// the statement-level sweep.
#[test]
fn call_argument_lines_cross_the_whole_signed_band() {
    for line in BAND {
        let ast::Stmt::Call(c) = one_stmt(&format!(
            r#"{{"stmt": "call", "callee": "C", "args": ["a"], "line": {line}}}"#
        )) else {
            panic!("a Layer 2 `call` must project to an AST `Call`");
        };
        assert_eq!(
            c.args,
            vec![ast::Expr::VarRef(ast::VarRef {
                name: "a".to_owned(),
                line: SourceLine(line),
            })],
            "argument minted at the call line {line}"
        );
    }
}

/// An `acquire` writes its line into TWO nodes (the `Let` and the `Acquire`);
/// the sweep above only reads the `Let`.
#[test]
fn an_acquire_expression_line_crosses_the_whole_signed_band() {
    for line in BAND {
        let ast::Stmt::Let(l) = one_stmt(&format!(
            r#"{{"stmt": "acquire", "handle": "h", "resource": "R", "line": {line}}}"#
        )) else {
            panic!("a Layer 2 `acquire` must project to an AST `Let`");
        };
        let ast::Expr::Acquire(a) = &l.rhs else {
            panic!("the `Let` rhs must be an `Acquire`");
        };
        assert_eq!(a.line, SourceLine(line), "the Acquire node's own line");
    }
}

/// The line of an AST statement, whichever variant it is.
const fn stmt_line(s: &ast::Stmt) -> SourceLine {
    match s {
        ast::Stmt::Let(x) => x.line,
        ast::Stmt::Release(x) => x.line,
        ast::Stmt::Use(x) => x.line,
        ast::Stmt::Overspan(x) => x.line,
        ast::Stmt::Call(x) => x.line,
        ast::Stmt::AliasJoin(x) => x.line,
        ast::Stmt::BorrowBlock(x) => x.line,
        ast::Stmt::If(x) => x.line,
        ast::Stmt::While(x) => x.line,
        ast::Stmt::Return(x) => x.line,
        ast::Stmt::Subscribe(x) => x.line,
    }
}

// ---------------------------------------------------------------------------
// Group 5 — the closed vocabularies, and the boundary they do not extend to
// ---------------------------------------------------------------------------

#[test]
fn an_unknown_member_role_is_unrepresentable_and_fails_loud() {
    let doc = lowered(
        r#"{"lowered_version": 1, "module": "M",
            "resources": [{"name": "R", "kind": null,
                           "members": [{"role": "borrow", "name": "A"}]}],
            "externs": [], "lifetimes": [], "functions": [], "handles": []}"#,
    );
    let err = project(&doc).expect_err("an out-of-vocabulary role must be rejected");
    assert!(
        err.0.contains("borrow") && err.0.contains('R'),
        "the rejection must name the offending role and its resource: {err}"
    );
}

#[test]
fn an_unknown_parameter_effect_is_unrepresentable_and_fails_loud() {
    let doc = lowered(
        r#"{"lowered_version": 1, "module": "M", "resources": [],
            "externs": [{"name": "$sink",
                         "params": [{"effect": "steal", "type": "Disposable"}]}],
            "lifetimes": [], "functions": [], "handles": []}"#,
    );
    let err = project(&doc).expect_err("an out-of-vocabulary effect must be rejected");
    assert!(
        err.0.contains("steal") && err.0.contains("$sink"),
        "the rejection must name the offending effect and its extern: {err}"
    );
}

/// All four `ast_nodes.Effect` members are accepted, including `plain` — which
/// the three sink externs never use, so the whole shared corpus is silent about
/// it. The vocabulary belongs to the enum, not to the one producer that
/// currently reaches a subset of it.
#[test]
fn the_effect_vocabulary_is_the_enums_not_the_corpus() {
    let doc = lowered(
        r#"{"lowered_version": 1, "module": "M", "resources": [],
            "externs": [{"name": "$e", "params": [
                {"effect": "borrow", "type": "Disposable"},
                {"effect": "borrow_mut", "type": "Disposable"},
                {"effect": "consume", "type": "Disposable"},
                {"effect": "plain", "type": "int"}]}],
            "lifetimes": [], "functions": [], "handles": []}"#,
    );
    let effects: Vec<ast::Effect> = project(&doc).expect("every member projects").externs[0]
        .params
        .iter()
        .map(|p| p.effect)
        .collect();
    assert_eq!(
        effects,
        vec![
            ast::Effect::Borrow,
            ast::Effect::BorrowMut,
            ast::Effect::Consume,
            ast::Effect::Plain,
        ]
    );
}

/// The boundary the rejections deliberately stop at.
///
/// `Module` has no handle map — `to_module` returns it *alongside* the AST, and
/// Layer 3 is what reads it — so an unresolvable handle is not a fact this
/// layer can state. The same goes for a resource name with no declaration:
/// resolving names against declarations is `own-cfg`'s job and produces a
/// *verdict*, not a projection error. A projection that rejected either would
/// be a second validation contract with nothing to validate against.
#[test]
fn dangling_names_are_carried_not_rejected() {
    let doc = lowered(
        r#"{"lowered_version": 1, "module": "M", "resources": [], "externs": [],
            "lifetimes": [],
            "functions": [{"name": "F", "lifetime": "NoSuchRegion", "params": [],
                           "ret": null,
                           "body": [{"stmt": "acquire", "handle": "h",
                                     "resource": "NoSuchResource", "line": 1},
                                    {"stmt": "release", "handle": "never_acquired",
                                     "line": 2}]}],
            "handles": []}"#,
    );
    let m = project(&doc).expect("unresolved names are carried, not rejected");

    assert_eq!(
        m.functions[0].lifetime,
        Some("NoSuchRegion".to_owned()),
        "an undeclared region is carried verbatim"
    );
    assert_eq!(
        m.functions[0].body[0],
        ast::Stmt::Let(ast::Let {
            name: "h".to_owned(),
            rhs: ast::Expr::Acquire(ast::Acquire {
                resource: "NoSuchResource".to_owned(),
                args: Vec::new(),
                line: SourceLine(1),
            }),
            line: SourceLine(1),
        }),
        "an undeclared resource name is carried verbatim"
    );
    assert_eq!(
        m.functions[0].body[1],
        ast::Stmt::Release(ast::Release {
            var: "never_acquired".to_owned(),
            line: SourceLine(2),
        }),
        "a release of a never-acquired handle is carried verbatim"
    );
}

/// The handle map is Layer 3's input, not the AST's: a document with handle
/// entries and one with none project to the same `Module`.
#[test]
fn the_handle_map_does_not_reach_the_ast() {
    let envelope = |handles: &str| {
        lowered(&format!(
            r#"{{"lowered_version": 1, "module": "M", "resources": [], "externs": [],
                "lifetimes": [],
                "functions": [{{"name": "F", "lifetime": null, "params": [],
                                "ret": null,
                                "body": [{{"stmt": "use", "handle": "h", "line": 1}}]}}],
                "handles": [{handles}]}}"#
        ))
    };
    assert_eq!(
        project(&envelope("")).expect("projects"),
        project(&envelope(
            r#"{"handle": "h", "component": "C", "file": "C.cs", "line": 9}"#
        ))
        .expect("projects"),
        "handle metadata is Layer 3 state and must not change the AST"
    );
}

// ---------------------------------------------------------------------------
// Group 6 — the corpus sweep
// ---------------------------------------------------------------------------

/// Count the statements in a Layer 2 body, recursing into both `if` arms and a
/// `while` body.
fn count_lowered(body: &[own_lowered::Stmt]) -> usize {
    body.iter()
        .map(|s| match s {
            own_lowered::Stmt::If { then, r#else, .. } => count_lowered(then)
                .saturating_add(count_lowered(r#else))
                .saturating_add(1),
            own_lowered::Stmt::While { body, .. } => count_lowered(body).saturating_add(1),
            _ => 1,
        })
        .sum()
}

/// The same count over the projected AST.
fn count_ast(body: &[ast::Stmt]) -> usize {
    body.iter()
        .map(|s| match s {
            ast::Stmt::If(x) => count_ast(&x.then_body)
                .saturating_add(count_ast(&x.else_body))
                .saturating_add(1),
            ast::Stmt::While(x) => count_ast(&x.body).saturating_add(1),
            ast::Stmt::BorrowBlock(x) => count_ast(&x.body).saturating_add(1),
            _ => 1,
        })
        .sum()
}

/// Totality and structural conservation over every shared Layer 2 case.
///
/// The counts are computed independently on each side, so a projection that
/// dropped a nested branch, duplicated a statement, or lost a function is
/// visible here even though no golden of the AST exists.
#[test]
fn projects_every_shared_layer_2_case_without_loss() {
    let manifest: Manifest =
        serde_json::from_str(&read("manifest.json")).expect("manifest.json parses (typed, strict)");

    let mut projected = 0_usize;
    let mut rejections = 0_usize;
    for case in &manifest.cases {
        if !case.rust_replay {
            continue;
        }
        let name = &case.name;
        match parse_document(&read(&format!("{name}.golden.json"))) {
            Ok(Surface::Lowered(doc)) => {
                let module = project(&doc)
                    .unwrap_or_else(|e| panic!("{name}: a shared golden must project: {e}"));
                assert_eq!(
                    module.name, doc.module,
                    "{name}: module identity must survive"
                );
                assert_eq!(
                    module.resources.len(),
                    doc.resources.len(),
                    "{name}: resource count"
                );
                assert_eq!(
                    module.externs.len(),
                    doc.externs.len(),
                    "{name}: extern count"
                );
                assert_eq!(
                    module.lifetimes.len(),
                    doc.lifetimes.len(),
                    "{name}: lifetime count"
                );
                assert_eq!(
                    module.functions.len(),
                    doc.functions.len(),
                    "{name}: function count"
                );
                for (fun, lowered_fn) in module.functions.iter().zip(&doc.functions) {
                    assert_eq!(
                        fun.params.len(),
                        lowered_fn.params.len(),
                        "{name}/{}: param count",
                        fun.name
                    );
                    assert_eq!(
                        count_ast(&fun.body),
                        count_lowered(&lowered_fn.body),
                        "{name}/{}: statement count, nesting included",
                        fun.name
                    );
                }
                assert_eq!(
                    project(&doc).expect("projects"),
                    module,
                    "{name}: projection must be deterministic"
                );
                projected = projected.saturating_add(1);
            }
            // A fail-loud lowering has no Module to project — it is the
            // bridge's rejection, and cp4 replays it at the bridge, not here.
            Ok(Surface::Rejected(_)) => rejections = rejections.saturating_add(1),
            Err(e) => panic!("{name}: golden does not parse as Layer 2: {e}"),
        }
    }

    assert!(
        projected >= 20,
        "the ledger should still carry the whole shared corpus, saw {projected} \
         lowered cases (+{rejections} rejections)"
    );
}
