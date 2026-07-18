//! Architecture-fitness test (P-022 §"Architecture-fitness tooling"): the crate
//! graph IS the architecture, so lock the **allowed** workspace-internal edge
//! set with a `cargo metadata` parse. Cargo already makes a *cycle* a compile
//! error; this catches the subtler drift — a crate growing a dependency it is
//! architecturally forbidden from having (the #214 guardrail: "diagnostics never
//! depends on analysis; codegen untouched").
//!
//! The load-bearing invariants (P-022 §fitness):
//! * `own-ir` is the leaf — it depends on no workspace crate.
//! * `own-diagnostics` (the verdict/contract layer) depends only on the
//!   span/location leaf `own-ir`; **never** on `own-syntax` (the parser),
//!   `own-cfg`, or `own-analysis` (the solver). The arrow is
//!   `own-analysis → own-diagnostics`, not the reverse.
//! * `own-cfg` hangs off `own-syntax` (+ the leaf), nothing downstream.
//!
//! Encoded as `crate → allowed superset of workspace deps`; the test asserts the
//! *actual* edge set is a subset. Widening the map is a deliberate, reviewed act
//! — exactly the point (a future `own-codegen → own-analysis` edge, say, must be
//! added here on purpose, never slip in implicitly).

#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use serde_json::Value;
use std::collections::{BTreeSet, HashMap};
use std::process::Command;

/// `crate → the workspace crates it is ALLOWED to depend on`. Any workspace
/// member not listed is required to have **no** workspace-internal dependency.
fn allowed_edges() -> HashMap<&'static str, BTreeSet<&'static str>> {
    let mut m: HashMap<&'static str, BTreeSet<&'static str>> = HashMap::new();
    m.insert("own-ir", BTreeSet::new()); // leaf — depends on nothing
    m.insert("own-syntax", std::iter::once("own-ir").collect());
    m.insert("own-cfg", ["own-ir", "own-syntax"].into_iter().collect());
    // The invariant #214 is about: only the span leaf, never the solver/parser.
    m.insert("own-diagnostics", std::iter::once("own-ir").collect());
    // The Layer 2 parity surface (#259): a DATA leaf like own-diagnostics —
    // the typed model + canonical emitter of the normalized lowered
    // representation. It deliberately depends on NO workspace crate: the
    // future own-bridge will CONSTRUCT these types (own-bridge → own-lowered),
    // never the reverse, and the surface must stay implementable without the
    // lowering that fills it.
    m.insert("own-lowered", BTreeSet::new());
    // own-analysis CONSTRUCTS diagnostics and consumes the cfg lowering. It reads
    // the effect type through `own_cfg::Effect`, NOT the parser — so there is no
    // production own-syntax edge (own-syntax is a dev-only edge for its tests).
    m.insert(
        "own-analysis",
        ["own-ir", "own-cfg", "own-diagnostics"]
            .into_iter()
            .collect(),
    );
    m
}

fn workspace_edges() -> HashMap<String, BTreeSet<String>> {
    let manifest = concat!(env!("CARGO_MANIFEST_DIR"), "/Cargo.toml");
    let out = Command::new(env!("CARGO"))
        .args([
            "metadata",
            "--no-deps",
            "--format-version",
            "1",
            "--manifest-path",
            manifest,
        ])
        .output()
        .expect("cargo metadata runs");
    assert!(
        out.status.success(),
        "cargo metadata failed: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    let meta: Value = serde_json::from_slice(&out.stdout).expect("metadata JSON parses");
    let packages = meta
        .get("packages")
        .and_then(Value::as_array)
        .expect("packages");

    // With --no-deps, `packages` is exactly the workspace members.
    let members: BTreeSet<String> = packages
        .iter()
        .filter_map(|p| p.get("name").and_then(Value::as_str))
        .map(str::to_owned)
        .collect();

    let mut edges: HashMap<String, BTreeSet<String>> = HashMap::new();
    for pkg in packages {
        let name = pkg
            .get("name")
            .and_then(Value::as_str)
            .expect("pkg name")
            .to_owned();
        let deps: BTreeSet<String> = pkg
            .get("dependencies")
            .and_then(Value::as_array)
            .expect("dependencies array")
            .iter()
            // Only NORMAL (production) deps are architecture edges: cargo tags a
            // dev-dependency's `kind` as "dev" and a build-dep as "build"; a
            // normal dep has `kind: null`. Test-only edges (a crate using another
            // crate's parser in its *tests*) do not constrain the runtime DAG.
            .filter(|d| d.get("kind").map_or(true, Value::is_null))
            .filter_map(|d| d.get("name").and_then(Value::as_str))
            .filter(|d| members.contains(*d)) // only workspace-internal edges are architecture
            .map(str::to_owned)
            .collect();
        edges.insert(name, deps);
    }
    edges
}

#[test]
fn crate_graph_matches_the_allowed_dag() {
    let allowed = allowed_edges();
    let actual = workspace_edges();

    for (crate_name, deps) in &actual {
        let permitted = allowed.get(crate_name.as_str()).unwrap_or_else(|| {
            panic!(
                "workspace member {crate_name:?} is not in the allowed-edge map — add it to \
                 tests/dag.rs::allowed_edges with its intended (reviewed) dependency set"
            )
        });
        for dep in deps {
            assert!(
                permitted.contains(dep.as_str()),
                "FORBIDDEN EDGE: {crate_name} → {dep} is not in the allowed DAG. \
                 If this edge is intended, widen allowed_edges() deliberately (and justify it)."
            );
        }
    }
}

#[test]
fn own_diagnostics_never_depends_on_the_solver_or_parser() {
    // The single most important #214 invariant, asserted directly so a regression
    // names itself even if the map above is edited.
    let actual = workspace_edges();
    let deps = actual
        .get("own-diagnostics")
        .expect("own-diagnostics is a member");
    for forbidden in ["own-analysis", "own-syntax", "own-cfg"] {
        assert!(
            !deps.contains(forbidden),
            "own-diagnostics must not depend on {forbidden} \
             (verdict/contract layer stays independent of the solver and parser)"
        );
    }
}

#[test]
fn own_analysis_has_no_production_parser_edge() {
    // The domain analyses read the effect type through `own_cfg::Effect`; a
    // production dependency on the parser (`own-syntax`) must never return.
    // (own-syntax stays a dev-dependency for the parity/metamorphic tests.)
    let actual = workspace_edges();
    let deps = actual
        .get("own-analysis")
        .expect("own-analysis is a member");
    assert!(
        !deps.contains("own-syntax"),
        "own-analysis grew a PRODUCTION dependency on own-syntax; read the effect \
         type via own_cfg::Effect and keep own-syntax a dev-dependency"
    );
}

#[test]
fn own_ir_is_a_leaf() {
    let actual = workspace_edges();
    let deps = actual.get("own-ir").expect("own-ir is a member");
    assert!(
        deps.is_empty(),
        "own-ir is the leaf — it must depend on no workspace crate, got {deps:?}"
    );
}
