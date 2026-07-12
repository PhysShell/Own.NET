//! Metamorphic properties for the ownership analysis (#214): transformations
//! that must not change the diagnostic meaning, checked without Python (steady-
//! state Rust tests invoke no Python).
//!
//! * renaming a local does not alter the `(line, code)` set;
//! * repeated analysis is identical (determinism / idempotence);
//! * adding unreachable code never removes an existing finding;
//! * a diagnostic survives a serde round-trip unchanged (result serialization).

#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use own_diagnostics::Diagnostic;

const PRELUDE: &str = "module M\n\
    resource Conn { acquire open release close }\n\
    extern fn Hash(borrow Conn);\n\
    extern fn Store(consume Conn);\n";

/// Analyze every function in `source`, returning the flat diagnostic list.
fn analyze_all(source: &str) -> Vec<Diagnostic> {
    let module = own_syntax::parse(source).expect("test source parses");
    let (cfgs, _d1) = own_cfg::build_module(&module);
    let mut out = Vec::new();
    for cfg in &cfgs {
        out.extend(own_analysis::analyze(cfg));
    }
    out
}

fn keys(diags: &[Diagnostic]) -> Vec<(u32, String)> {
    let mut v: Vec<(u32, String)> = diags.iter().map(|d| (d.line, d.code.clone())).collect();
    v.sort_by(|a, b| a.0.cmp(&b.0).then_with(|| a.1.cmp(&b.1)));
    v
}

#[test]
fn renaming_a_local_preserves_diagnostics() {
    // A use-after-release; the owned local is named `c` in one, `resourceHandle`
    // in the other. Same lines (rename is in-place), so `(line, code)` is equal.
    let a = format!(
        "{PRELUDE}fn f() {{\n    let c = acquire Conn(1);\n    release c;\n    Hash(c);\n    return;\n}}\n"
    );
    let b = format!(
        "{PRELUDE}fn f() {{\n    let resourceHandle = acquire Conn(1);\n    release resourceHandle;\n    Hash(resourceHandle);\n    return;\n}}\n"
    );
    let ka = keys(&analyze_all(&a));
    let kb = keys(&analyze_all(&b));
    assert_eq!(ka, kb, "a local rename must not change the diagnostic set");
    assert!(
        ka.iter().any(|(_, c)| c == "OWN002"),
        "sanity: the use-after-release is actually flagged"
    );
}

#[test]
fn repeated_analysis_is_identical() {
    let src = format!("{PRELUDE}fn f() {{\n    let c = acquire Conn(1);\n    return;\n}}\n");
    let first = keys(&analyze_all(&src));
    let second = keys(&analyze_all(&src));
    assert_eq!(first, second, "analysis must be deterministic / idempotent");
    assert!(
        first.iter().any(|(_, c)| c == "OWN001"),
        "sanity: the leak is flagged (once, deterministically): {first:?}"
    );
}

#[test]
fn adding_unreachable_code_never_removes_a_finding() {
    let base = format!("{PRELUDE}fn f() {{\n    let c = acquire Conn(1);\n    return;\n}}\n");
    let base_keys = keys(&analyze_all(&base));
    assert!(!base_keys.is_empty(), "base has a leak to preserve");

    // Append an entire additional (independently analyzed) function AND a
    // statement after a return. The original leak at line 4 must remain.
    let extended = format!(
        "{base}fn g() {{\n    let d = acquire Conn(2);\n    release d;\n    return;\n    Store(d);\n}}\n"
    );
    let ext_keys = keys(&analyze_all(&extended));
    for k in &base_keys {
        assert!(
            ext_keys.contains(k),
            "adding code removed the pre-existing finding {k:?}"
        );
    }
}

#[test]
fn diagnostics_survive_a_serde_round_trip() {
    let src = format!(
        "{PRELUDE}fn f() {{\n    let c = acquire Conn(1);\n    release c;\n    release c;\n    return;\n}}\n"
    );
    let diags = analyze_all(&src);
    assert!(!diags.is_empty());
    let json = serde_json::to_string(&diags).expect("diagnostics serialize");
    let back: Vec<Diagnostic> = serde_json::from_str(&json).expect("round-trip deserializes");
    assert_eq!(
        diags, back,
        "serialization round-trip must preserve results"
    );
}
