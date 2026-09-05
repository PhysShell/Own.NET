//! The verdict **subject** contract (#259 cp4): every diagnostic the Python
//! analysis stamps with `subject=sym.origin` carries the same `name#line`
//! identity here, and the ones Python leaves subject-less stay subject-less.
//!
//! Asserted through the production `check_module` surface (not a private
//! emitter), because the `OwnIR` bridge maps a core verdict back to a fact
//! handle by exactly this field (BR-V3 map-or-raise) — a subject that is
//! present but wrong, or missing where Python has one, is a bridge rejection
//! or a mis-anchored finding, never a cosmetic difference.

#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use own_analysis::check_module;

const PRELUDE: &str = "module M\n\
    resource Conn { acquire open release close }\n\
    extern fn Hash(borrow Conn);\n\
    extern fn Store(consume Conn);\n";

/// `(line, code, subject)` for every diagnostic of `body` (appended after the
/// 4-line prelude, so body line 1 is source line 5).
fn subjects(body: &str) -> Vec<(u32, String, Option<String>)> {
    let module = own_syntax::parse(&format!("{PRELUDE}{body}")).expect("parses");
    check_module(&module)
        .into_iter()
        .map(|d| (d.line, d.code, d.subject))
        .collect()
}

/// The expected-subject spelling: the `Option` IS the assertion shape (a
/// diagnostic's subject is optional), so wrapping here is the point.
#[allow(clippy::unnecessary_wraps)]
fn s(x: &str) -> Option<String> {
    Some(x.to_owned())
}

#[test]
fn leak_carries_the_acquire_origin() {
    // `let c = acquire Conn(1);` on line 6 → origin `c#6` (the acquire's line).
    let got = subjects("fn f() {\n  let c = acquire Conn(1);\n}\n");
    assert_eq!(got, vec![(6, "OWN001".to_owned(), s("c#6"))]);
}

#[test]
fn param_leak_carries_the_param_origin() {
    // An owned parameter is minted at the fn line (5): origin `p#5`. The leak
    // itself anchors at line 0 — an empty body has no instruction to borrow a
    // line from, the same anchor Python reports (`(line, code)` parity).
    let got = subjects("fn f(p: Conn) {\n}\n");
    assert_eq!(got, vec![(0, "OWN001".to_owned(), s("p#5"))]);
}

#[test]
fn use_after_release_and_double_release_carry_the_origin() {
    let got =
        subjects("fn f() {\n  let c = acquire Conn(1);\n  release c;\n  use c;\n  release c;\n}\n");
    assert_eq!(
        got,
        vec![
            (8, "OWN002".to_owned(), s("c#6")),
            (9, "OWN003".to_owned(), s("c#6")),
        ]
    );
}

#[test]
fn return_after_release_carries_the_origin() {
    let got =
        subjects("fn f() -> Conn {\n  let c = acquire Conn(1);\n  release c;\n  return c;\n}\n");
    assert_eq!(got, vec![(8, "OWN002".to_owned(), s("c#6"))]);
}

#[test]
fn origin_is_inherited_across_a_move() {
    // `let d = move c;` keeps c's origin on d (Python `dst.origin = src.origin`):
    // the use-after-move names `c#6`, and the leak of `d` is attributed to `c#6`
    // too. `check_module` sorts by (line, code), so OWN001 precedes OWN005.
    let got = subjects("fn f() {\n  let c = acquire Conn(1);\n  let d = move c;\n  use c;\n}\n");
    assert_eq!(
        got,
        vec![
            (8, "OWN001".to_owned(), s("c#6")),
            (8, "OWN005".to_owned(), s("c#6")),
        ]
    );
}

#[test]
fn loan_permission_codes_stay_subject_less_like_python() {
    // `borrow b as r { borrow_mut b as m { } }`: a mutable borrow while a shared
    // one is live is OWN006 — Python's `err(...)` passes no subject there.
    let got = subjects(
        "fn f() {\n  let b = acquire Conn(1);\n  borrow b as r {\n    borrow_mut b as m {\n    }\n  }\n  release b;\n}\n",
    );
    assert_eq!(got, vec![(8, "OWN006".to_owned(), None)]);
}

#[test]
fn overspan_carries_the_buffer_origin_with_its_column() {
    // A buffer intent's origin is `name#line:col` (the bridge's flow-local
    // pooled buffers go through `acquire`, not this path — pinned for the .own
    // surface, which own-cli will need).
    let got = subjects("fn f() {\n  let b = Buffer.pooled(4);\n  overspan b;\n  release b;\n}\n");
    assert_eq!(got, vec![(7, "OWN025".to_owned(), s("b#6:11"))]);
}

#[test]
fn region_escape_carries_the_source_identity() {
    // OWN014's subject is `source#line` — the captured-by source, not `self`.
    let src = "module M\n\
        lifetime App;\n\
        lifetime ViewModel < App;\n\
        fn VM(bus: EventSource lifetime App) lifetime ViewModel {\n\
            subscribe self to bus;\n\
        }\n";
    let module = own_syntax::parse(src).expect("parses");
    let got: Vec<(u32, String, Option<String>)> = check_module(&module)
        .into_iter()
        .map(|d| (d.line, d.code, d.subject))
        .collect();
    assert_eq!(got, vec![(5, "OWN014".to_owned(), s("bus#5"))]);
}
