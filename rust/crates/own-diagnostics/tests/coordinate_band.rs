//! Acceptance groups 3 and 4 for `SourceLine`: the SARIF projection domain,
//! and the identity re-proof.
//!
//! Group 4 is here because "the newtype derives `Ord` and `Hash`" is not
//! evidence. Three of the carriers this change widened participate in a
//! comparison key, so widening them is a change to identity, and #255's
//! non-collapsing property has to be re-shown over the new range rather than
//! assumed to survive it.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing
)]

use own_diagnostics::{build_sarif, sort_emission_order};
use own_diagnostics::{DiagKey, Diagnostic, Evidence, LocatedDiagnostic};
use own_ir::span::SourceLine;

const U32_MAX: i64 = 4_294_967_295;
const ABOVE_U32: i64 = 4_294_967_296;

fn diag(line: i64) -> Diagnostic {
    Diagnostic::new("OWN001", "not released", SourceLine(line)).expect("OWN001 is known")
}

// ---------------------------------------------------------------------------
// Group 3 — the projection domain
// ---------------------------------------------------------------------------

/// Measured against the reference and frozen here verbatim. The gate is `>= 1`
/// and the ceiling is gone: SARIF's admission domain is narrower **only at the
/// bottom**, which is a property of the format, not of the verdict.
#[test]
fn the_sarif_region_matches_the_reference_over_the_whole_band() {
    let expected: [(i64, Option<i64>); 6] = [
        (i64::MIN, None),
        (-1, None),
        (0, None),
        (1, Some(1)),
        (ABOVE_U32, Some(ABOVE_U32)),
        (i64::MAX, Some(i64::MAX)),
    ];
    for (line, want) in expected {
        let log = build_sarif(&[diag(line)], "A.cs", "error");
        let got = log.runs[0].results[0].locations[0]
            .physical_location
            .region
            .as_ref()
            .map(|r| r.start_line.get());
        assert_eq!(
            got, want,
            "line {line}: SARIF region mismatch. Below 1 the reference omits \
             the region entirely; at or above it the value is emitted verbatim, \
             including past u32::MAX — a narrower carrier here would turn a \
             legal startLine into a wrong one."
        );
    }
}

// ---------------------------------------------------------------------------
// Group 4 — identity re-proof
// ---------------------------------------------------------------------------

#[test]
fn a_diag_key_separates_lines_a_u32_would_confuse() {
    // The pairs are chosen so that a `as u32` TRUNCATION collapses them —
    // which the first version of this test did not do, and a truncating
    // mutation survived it. `u32::MAX + 1` truncates to 0, and `-1` truncates
    // to `u32::MAX`, so each pair is one value the old ceiling could hold and
    // one it could not that lands on it.
    for (a, b) in [
        (0_i64, ABOVE_U32),
        (-1_i64, U32_MAX),
        (1_i64, ABOVE_U32 + 1),
        (i64::MIN, 0),
    ] {
        assert_ne!(
            DiagKey::new(SourceLine(a), "OWN001"),
            DiagKey::new(SourceLine(b), "OWN001"),
            "DiagKey collapsed lines {a} and {b} — the comparison key is \
             narrower than the coordinate it keys on"
        );
    }
}

#[test]
fn a_diag_identity_does_not_collapse_on_the_line_alone() {
    // Everything except the primary line is held identical, so the line is the
    // only thing identity can be separating on.
    let one = LocatedDiagnostic::new("src/A.cs", diag(ABOVE_U32));
    let other = LocatedDiagnostic::new("src/A.cs", diag(0));
    assert_ne!(
        one.identity(),
        other.identity(),
        "two diagnostics differing ONLY in a line beyond u32::MAX share an \
         identity — #255's non-collapsing key stops holding exactly where the \
         old ceiling used to be"
    );
}

#[test]
fn an_evidence_identity_separates_secondary_lines_past_the_old_ceiling() {
    let base = || diag(1);
    // Both values are POSITIVE, and that is the point. The secondary producer
    // is admission-gated at `>= 1`, so an evidence line of 0 never reaches
    // identity in a real pipeline — proving non-collapse on it proves it
    // outside the domain the property has to hold on. `1` and `u32::MAX + 2`
    // both truncate to `1` under `as u32`, so the pair still collapses under
    // the mutation while staying inside the admissible range.
    let one = LocatedDiagnostic::new(
        "src/A.cs",
        base().with_evidence(vec![Evidence::new(
            SourceLine(ABOVE_U32 + 1),
            "registered here",
        )]),
    );
    let other = LocatedDiagnostic::new(
        "src/A.cs",
        base().with_evidence(vec![Evidence::new(SourceLine(1), "registered here")]),
    );
    assert_ne!(
        one.identity(),
        other.identity(),
        "evidence at two different lines beyond u32::MAX compares equal — the \
         secondary carrier is keyed more narrowly than it is stored"
    );
}

#[test]
fn the_production_sorter_orders_the_band_signed() {
    // Through `sort_emission_order`, NOT through `Vec<SourceLine>::sort`. The
    // first version of this control sorted the newtype directly, which proves
    // the derived `Ord` and says nothing about the emission contract — a sort
    // key written `a.line.get() as u32` would have left it green.
    let mut diags: Vec<Diagnostic> = [1_i64, i64::MAX, -1, U32_MAX, i64::MIN, 0, ABOVE_U32]
        .into_iter()
        .map(diag)
        .collect();
    sort_emission_order(&mut diags);
    let got: Vec<i64> = diags.iter().map(|d| d.line.get()).collect();
    assert_eq!(
        got,
        vec![i64::MIN, -1, 0, 1, U32_MAX, ABOVE_U32, i64::MAX],
        "the emission order is not signed — an unsigned sort key puts the \
         negatives last and reorders every diagnostic on a file that has one"
    );
}

/// The **secondary** projection path, which the primary control cannot reach.
///
/// `Evidence.line` travels a different route to SARIF: `steps_for` copies it
/// into a `Step`, `emittable` applies the `>= 1` gate, and `related_locations`
/// and `code_flow` each build a `Region` from it. So a truncation introduced in
/// `steps_for` leaves every other control here green — `EvidenceIdentity`
/// inspects the `Evidence`, and the primary region never passes through a
/// `Step` at all.
///
/// Both consumers are asserted, not just one: they share `emittable` today, and
/// a control that only checked `relatedLocations` would be relying on that.
#[test]
fn the_secondary_sarif_path_carries_evidence_lines_over_the_band() {
    let expected: [(i64, Option<i64>); 5] = [
        (-1, None),
        (0, None),
        (1, Some(1)),
        (ABOVE_U32, Some(ABOVE_U32)),
        (i64::MAX, Some(i64::MAX)),
    ];
    for (line, want) in expected {
        let d = diag(1).with_evidence(vec![
            Evidence::new(SourceLine(line), "registered here").with_role("registered")
        ]);
        let log = build_sarif(&[d], "A.cs", "error");
        let result = &log.runs[0].results[0];

        let related: Vec<i64> = result
            .related_locations
            .iter()
            .filter_map(|l| l.physical_location.region.as_ref())
            .map(|r| r.start_line.get())
            .collect();
        let flow: Vec<i64> = result
            .code_flows
            .iter()
            .flat_map(|f| f.thread_flows.iter())
            .flat_map(|t| t.locations.iter())
            .filter_map(|l| l.location.physical_location.region.as_ref())
            .map(|r| r.start_line.get())
            .collect();

        let want_vec: Vec<i64> = want.into_iter().collect();
        assert_eq!(
            related, want_vec,
            "evidence line {line}: relatedLocations mismatch — below 1 the \
             secondary location is dropped entirely, at or above it the value \
             rides through verbatim"
        );
        assert_eq!(
            flow, want_vec,
            "evidence line {line}: codeFlows mismatch. relatedLocations and \
             codeFlows are two separate consumers of the same Step; checking \
             only one would lean on them sharing `emittable` today"
        );
    }
}
