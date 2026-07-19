//! Mechanism-focused tests (#259 slice 3): where a byte-exact replay alone
//! does not PROVE the mechanism, pin it with a metamorphic or negative case —
//! reordering input changes minting predictably, kill-on-rebind really kills,
//! the precise overload channel does not unmap while the merged-may kill site
//! does, each hoisting negative gate blocks the hoist, and an unknown flow op
//! fails loud with Python's exact rejection text.

#![allow(clippy::panic, clippy::expect_used)]

use own_lowered::{Function, LoweredDocument, Stmt};

fn lower(text: &str) -> LoweredDocument {
    let facts = own_ir::OwnIr::from_json(text).expect("facts parse");
    own_bridge::lower(&facts).expect("lowering succeeds")
}

fn fun<'a>(doc: &'a LoweredDocument, name: &str) -> &'a Function {
    doc.functions
        .iter()
        .find(|f| f.name == name)
        .unwrap_or_else(|| panic!("no function {name:?} in the lowered document"))
}

/// Two components, one static capture each. In [A, B] order A mints `cap_0`;
/// permuting the records to [B, A] hands `cap_0` to B — the global counter
/// follows document order (BR-L2/BR-D4: input order is semantic).
#[test]
fn record_order_changes_global_mint_order_predictably() {
    let comp = |name: &str| {
        format!(
            r#"{{"name": "{name}", "file": "{name}.cs", "subscriptions": [
                 {{"event": "SystemEvents.E", "handler": "H", "line": 3,
                   "resource": "capture", "source": "static"}}]}}"#
        )
    };
    let doc_ab = lower(&format!(
        r#"{{"ownir_version": 0, "module": "M", "components": [{}, {}]}}"#,
        comp("A"),
        comp("B")
    ));
    let doc_ba = lower(&format!(
        r#"{{"ownir_version": 0, "module": "M", "components": [{}, {}]}}"#,
        comp("B"),
        comp("A")
    ));
    let owner_of = |doc: &LoweredDocument, handle: &str| -> String {
        doc.handles
            .iter()
            .find(|h| h.handle == handle)
            .and_then(|h| h.component.clone())
            .unwrap_or_else(|| panic!("no handle {handle:?}"))
    };
    assert_eq!(owner_of(&doc_ab, "cap_0"), "A");
    assert_eq!(owner_of(&doc_ab, "cap_1"), "B");
    assert_eq!(owner_of(&doc_ba, "cap_0"), "B");
    assert_eq!(owner_of(&doc_ba, "cap_1"), "A");
}

/// A call-result overwrite of a tracked local KILLS its binding: the later
/// `release x` resolves to nothing (the original obligation leaks instead of
/// being silently discharged through a dead handle).
#[test]
fn kill_on_rebind_removes_the_old_mapping() {
    let doc = lower(
        r#"{"ownir_version": 0, "module": "M", "functions": [
             {"name": "F", "file": "F.cs", "body": [
               {"op": "acquire", "var": "x", "line": 2},
               {"op": "call", "callee": "Unknown.Make", "args": [], "result": "x", "line": 3},
               {"op": "release", "var": "x", "line": 4}]}]}"#,
    );
    let body = &fun(&doc, "F").body;
    assert!(
        matches!(body.as_slice(), [Stmt::Acquire { .. }]),
        "after the rebind the release must NOT resolve to the dead handle; \
         body: {body:?}"
    );
}

/// A sig-carrying call to an overloaded name applies its OWN overload's
/// contract through the channel ($consume for a consume overload) and does
/// NOT unmap the argument — a later `use` still resolves to the same handle.
#[test]
fn precise_overload_channel_does_not_unmap() {
    let doc = lower(
        r#"{"ownir_version": 0, "module": "M", "functions": [
             {"name": "Take", "file": "F.cs", "sig": "System.IO.Stream",
              "params": [{"name": "p", "line": 1, "effect": "consume"}], "body": []},
             {"name": "Take", "file": "F.cs", "sig": "System.String",
              "params": [{"name": "p", "line": 2, "effect": "borrow"}], "body": []},
             {"name": "M", "file": "F.cs", "body": [
               {"op": "acquire", "var": "c", "line": 12},
               {"op": "call", "callee": "Take", "sig": "System.IO.Stream",
                "args": ["c"], "line": 13},
               {"op": "use", "var": "c", "line": 14}]}]}"#,
    );
    let body = &fun(&doc, "M").body;
    assert!(
        matches!(
            body.as_slice(),
            [
                Stmt::Acquire { handle: h1, .. },
                Stmt::Call { callee, args, .. },
                Stmt::Use { handle: h2, .. },
            ] if callee == "$consume" && args == std::slice::from_ref(h1) && h1 == h2
        ),
        "expected acquire → $consume channel → use on the SAME still-mapped \
         handle; body: {body:?}"
    );
}

/// A sig-LESS call to the same overloaded name resolves the conservative
/// merged contract (`may`), which is a top-level kill site: the obligation is
/// discharged with `$consume` AT the call and the name unmapped — the later
/// `release` stays silent.
#[test]
fn merged_may_consume_applies_the_kill_site_unmap() {
    let doc = lower(
        r#"{"ownir_version": 0, "module": "M", "functions": [
             {"name": "Take", "file": "F.cs", "sig": "System.IO.Stream",
              "params": [{"name": "p", "line": 1, "effect": "consume"}], "body": []},
             {"name": "Take", "file": "F.cs", "sig": "System.String",
              "params": [{"name": "p", "line": 2, "effect": "borrow"}], "body": []},
             {"name": "M", "file": "F.cs", "body": [
               {"op": "acquire", "var": "c", "line": 12},
               {"op": "call", "callee": "Take", "args": ["c"], "line": 13},
               {"op": "release", "var": "c", "line": 14}]}]}"#,
    );
    let body = &fun(&doc, "M").body;
    assert!(
        matches!(
            body.as_slice(),
            [
                Stmt::Acquire { handle: h1, .. },
                Stmt::Call { callee, args, .. },
            ] if callee == "$consume" && args == std::slice::from_ref(h1)
        ),
        "expected acquire → kill-site $consume and a SILENT later release \
         (name unmapped); body: {body:?}"
    );
}

/// Hoisting negative gates: each condition alone must block the hoist.
mod hoist_gates {
    use super::{fun, lower, Stmt};

    /// Positive control: an if-branch acquire referenced at depth 0 hoists —
    /// one outer-scope acquire, empty branches, the release resolves to it.
    #[test]
    fn positive_control_hoists() {
        let doc = lower(
            r#"{"ownir_version": 0, "module": "M", "functions": [
                 {"name": "F", "file": "F.cs", "body": [
                   {"op": "if", "line": 2,
                    "then": [{"op": "acquire", "var": "r", "line": 3}],
                    "else": [{"op": "acquire", "var": "r", "line": 5}]},
                   {"op": "release", "var": "r", "line": 7}]}]}"#,
        );
        let body = &fun(&doc, "F").body;
        assert!(
            matches!(
                body.as_slice(),
                [
                    Stmt::Acquire { handle: h1, line: 3, .. },
                    Stmt::If { then, r#else, .. },
                    Stmt::Release { handle: h2, .. },
                ] if then.is_empty() && r#else.is_empty() && h1 == h2
            ),
            "expected a single hoisted outer acquire with empty branches; \
             body: {body:?}"
        );
    }

    /// A depth-2 acquire whose shallowest reference is depth 1 is NOT hoisted
    /// (function top is not the common dominator).
    #[test]
    fn nested_depth_reference_blocks_the_hoist() {
        let doc = lower(
            r#"{"ownir_version": 0, "module": "M", "functions": [
                 {"name": "F", "file": "F.cs", "body": [
                   {"op": "if", "line": 2, "then": [
                      {"op": "if", "line": 3,
                       "then": [{"op": "acquire", "var": "r", "line": 4}],
                       "else": []},
                      {"op": "release", "var": "r", "line": 6}],
                    "else": []}]}]}"#,
        );
        let body = &fun(&doc, "F").body;
        assert!(
            matches!(body.as_slice(), [Stmt::If { .. }]),
            "no hoisted outer acquire may appear; body: {body:?}"
        );
    }

    /// A `while`-body acquire is never hoisted (iterations are cumulative).
    #[test]
    fn while_body_acquire_blocks_the_hoist() {
        let doc = lower(
            r#"{"ownir_version": 0, "module": "M", "functions": [
                 {"name": "F", "file": "F.cs", "body": [
                   {"op": "while", "line": 2,
                    "body": [{"op": "acquire", "var": "r", "line": 3}]},
                   {"op": "release", "var": "r", "line": 5}]}]}"#,
        );
        let body = &fun(&doc, "F").body;
        assert!(
            matches!(body.first(), Some(Stmt::While { body: b, .. })
                     if matches!(b.as_slice(), [Stmt::Acquire { .. }])),
            "the acquire must stay inside the loop; body: {body:?}"
        );
    }

    /// An early `return` on a non-acquiring path blocks the hoist (the
    /// unconditional hoisted acquire would fabricate a leak on that path).
    #[test]
    fn early_return_blocks_the_hoist() {
        let doc = lower(
            r#"{"ownir_version": 0, "module": "M", "functions": [
                 {"name": "F", "file": "F.cs", "body": [
                   {"op": "if", "line": 2,
                    "then": [{"op": "acquire", "var": "r", "line": 3}],
                    "else": [{"op": "return", "line": 5}]},
                   {"op": "release", "var": "r", "line": 7}]}]}"#,
        );
        let body = &fun(&doc, "F").body;
        assert!(
            matches!(body.first(), Some(Stmt::If { then, .. })
                     if matches!(then.as_slice(), [Stmt::Acquire { .. }])),
            "the acquire must stay inside the branch; body: {body:?}"
        );
    }
}

/// An unknown flow op is vocabulary skew: fail loud with Python's exact
/// rejection text, never drop the op (which would silently lose the
/// acquire/release facts nested inside it).
#[test]
fn unknown_flow_op_fails_loud_with_python_text() {
    let facts = own_ir::OwnIr::from_json(
        r#"{"ownir_version": 0, "module": "M", "functions": [
             {"name": "F", "file": "X.cs", "body": [{"op": "goto", "line": 7}]}]}"#,
    )
    .expect("facts parse");
    let err = own_bridge::lower(&facts).expect_err("an unknown flow op must be rejected");
    assert_eq!(
        err.to_string(),
        "unknown OwnIR flow op 'goto' (X.cs:7) — extractor/core vocabulary \
         skew; a new op must bump OWNIR_VERSION (see spec/OwnIR.md)"
    );
}
