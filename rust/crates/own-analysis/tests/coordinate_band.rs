//! Acceptance groups 1 and 2 for `SourceLine`: carrier preservation through
//! the fact-driven analyses, and the DI site sentinel.
//!
//! The frozen parity fixtures cannot do this job. Every line they carry is a
//! small positive integer, so they are satisfied by a build that still
//! narrows to `u32` — they proved the widening broke nothing, which is a
//! different claim from proving it works.
//!
//! Each group deliberately exercises **more than one constructor**. A single
//! path that happens to be correct would otherwise cover a narrowing in a
//! sibling channel, which is the shape of every parity defect on this track.

#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use own_analysis::di::{di_verdicts, Lifetime, Service};
use own_analysis::effect::{effect_verdicts, Binding, Effect};
use own_ir::span::SourceLine;

/// The range the strict door accepts for a validated coordinate
/// (`spec/OwnIR.md` §4.2), and therefore the range a verdict must carry.
const BAND: [i64; 7] = [
    i64::MIN,
    -1,
    0,
    1,
    4_294_967_295, // u32::MAX
    4_294_967_296, // u32::MAX + 1 — the first value a u32 cannot hold
    i64::MAX,
];

/// A singleton depending on a scoped service: DI001, anchored at the
/// singleton's registration line.
fn captive(reg_line: i64) -> Vec<Service> {
    let mut sing = Service::new("Sing", Lifetime::Singleton, "S.cs", SourceLine(reg_line));
    sing.deps = vec!["Scop".to_owned()];
    vec![
        sing,
        Service::new("Scop", Lifetime::Scoped, "S.cs", SourceLine(2)),
    ]
}

/// A singleton root-resolving a disposable transient: DI004, whose primary
/// anchor is the root-resolution CALL SITE — with the registration site as the
/// fallback when that site is not `>= 1`.
fn di004(site_line: i64) -> Vec<Service> {
    let mut app = Service::new("App", Lifetime::Singleton, "reg.cs", SourceLine(5));
    app.root_resolves = vec!["Conn".to_owned()];
    app.root_resolve_sites = vec![(
        "Conn".to_owned(),
        "call.cs".to_owned(),
        SourceLine(site_line),
    )];
    let mut conn = Service::new("Conn", Lifetime::Transient, "reg.cs", SourceLine(6));
    conn.disposable = true;
    vec![app, conn]
}

/// An effect whose IO re-fires on a freshly-constructed dependency: EFF001,
/// anchored at the effect's own line.
fn storm(line: i64) -> Vec<Effect> {
    vec![Effect {
        component: "A".to_owned(),
        deps: vec!["opts".to_owned()],
        io: true,
        bindings: vec![Binding {
            name: "opts".to_owned(),
            init: "object".to_owned(),
            refs: Vec::new(),
            line: SourceLine(1),
        }],
        file: "A.tsx".to_owned(),
        line: SourceLine(line),
    }]
}

// ---------------------------------------------------------------------------
// Group 1 — carrier preservation
// ---------------------------------------------------------------------------

#[test]
fn a_di_verdict_carries_every_line_the_door_accepts() {
    for line in BAND {
        let verdicts = di_verdicts(&captive(line));
        let (_, got, code) = verdicts
            .first()
            .unwrap_or_else(|| panic!("DI001 expected at registration line {line}"));
        assert_eq!(*code, "DI001", "line {line} changed the verdict");
        assert_eq!(
            got.get(),
            line,
            "the DI verdict narrowed the registration line: expected {line}, \
             got {got} — a coordinate the strict door accepts must survive to \
             the verdict surface"
        );
    }
}

#[test]
fn an_effect_verdict_carries_every_line_the_door_accepts() {
    // A second, independent channel. `di` and `effects` reach a verdict by
    // different routes, so a correct DI constructor says nothing about this
    // one.
    for line in BAND {
        let verdicts = effect_verdicts(&storm(line));
        let (_, got, code) = verdicts
            .first()
            .unwrap_or_else(|| panic!("EFF001 expected at effect line {line}"));
        assert_eq!(*code, "EFF001", "line {line} changed the verdict");
        assert_eq!(
            got.get(),
            line,
            "the effect verdict narrowed the effect line: expected {line}, got {got}"
        );
    }
}

// ---------------------------------------------------------------------------
// Group 2 — the DI004/DI005 site sentinel
// ---------------------------------------------------------------------------

/// `line >= 1` chooses the call/store site; anything else falls back to the
/// registration site. The predicate is the reference's, written the same way,
/// and this is the first time the tree has a witness that can tell it apart
/// from `!= 0`.
#[test]
fn a_non_positive_site_takes_the_registration_fallback() {
    // Asserted as an EXACT anchor, not as "did not use the site". The weaker
    // form catches the `>= 1` -> `!= 0` refactor and would still pass if the
    // fallback landed on some third coordinate — an assertion that does not
    // say what its own name says.
    for line in [i64::MIN, -1, 0] {
        let di004_verdicts: Vec<_> = di_verdicts(&di004(line))
            .into_iter()
            .filter(|(_, _, code)| *code == "DI004")
            .collect();
        let (file, got, _) = di004_verdicts
            .first()
            .unwrap_or_else(|| panic!("DI004 expected for a site at line {line}"));
        assert_eq!(
            (file.as_str(), got.get()),
            ("reg.cs", 5),
            "a site at line {line} must anchor at the REGISTRATION site \
             (reg.cs:5). A refactor to `!= 0` passes every previously existing \
             test and fails here — which is the whole reason this control \
             exists — and so does a fallback that picks some other coordinate."
        );
    }
}

#[test]
fn a_positive_site_beyond_u32_is_still_a_site() {
    // The other half: the sentinel must not have become "small enough to fit".
    for line in [1_i64, 4_294_967_296, i64::MAX] {
        let di004_verdicts: Vec<_> = di_verdicts(&di004(line))
            .into_iter()
            .filter(|(_, _, code)| *code == "DI004")
            .collect();
        let (file, got, _) = di004_verdicts
            .first()
            .unwrap_or_else(|| panic!("DI004 expected for a site at line {line}"));
        assert_eq!(
            (file.as_str(), got.get()),
            ("call.cs", line),
            "a site at line {line} did not anchor the verdict — the sentinel \
             narrowed to something a u32 can hold"
        );
    }
}
