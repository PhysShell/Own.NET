//! K9 (the residual-⊥ lemma) and K11 (G-T2a / G-T2b).
//!
//! K9 covers all three groundings for every cell value. K11 is G-T2a: the
//! pure-lattice lax simulation against the collapsed semantic system, which
//! holds unconditionally pre-finalization (and, pinned, NOT post-finalization:
//! row 14). K11b is G-T2b as amended after the A0 spike: against TODAY'S
//! derivation (release priority, synthetic borrows) the finalized guarded
//! collapse is below today's value or the pair is exactly (unknown, may),
//! the declared verdict-equivalent class 3 — the pinned counterexample that
//! forced the amendment is `k11_finding_release_priority_drops_an_unresolved_forward`.

/// The frontend's cell-local facts are consistent.
///
/// A cell that records a local release (`must`/`may`) receives no forward
/// edge (a released resource is not also handed on in that cell). TRUSTED
/// INPUT assumption.
#[must_use]
pub fn release_cells_have_no_edges(sys: &crate::System) -> bool {
    use crate::{Mask, Transfer};
    sys.coords.iter().take(sys.n).all(|c| {
        let rel = |t: Transfer| matches!(t, Transfer::Must | Transfer::May);
        c.edges.iter().flatten().all(|e| {
            let hits_pos = !matches!(e.mask, Mask::NegOnly);
            let hits_neg = !matches!(e.mask, Mask::PosOnly);
            !((hits_pos && rel(c.seed.pos)) || (hits_neg && rel(c.seed.neg)))
        })
    })
}

/// No coordinate seeds `unknown` (no unresolved callee inside the SCC).
#[must_use]
pub fn no_unknown_seed(sys: &crate::System) -> bool {
    sys.coords
        .iter()
        .take(sys.n)
        .all(|c| c.seed.pos != crate::Transfer::Unknown && c.seed.neg != crate::Transfer::Unknown)
}

#[cfg(test)]
mod tests {
    use super::super::{all_cells, first, lfp, random_system, systems_exhaustive, Rng, DEAD};
    use super::{no_unknown_seed, release_cells_have_no_edges};
    use crate::{
        lemma_guarded, lemma_today, Cells, Coord, Edge, Grounding, Mask, Shape, System, Transfer,
        Transform, MAX_COORDS,
    };

    #[test]
    fn k9_residual_bottom_lemma_all_three_groundings() {
        for &t in &Transfer::ALL {
            let groundings = [
                (matches!(t, Transfer::Must | Transfer::May))
                    .then_some(Grounding::PartialLocalRelease(t)),
                Some(Grounding::GroundedForward(t)),
                Some(Grounding::Ungrounded),
            ];
            for g in groundings.into_iter().flatten() {
                let guarded = lemma_guarded(g).fin().collapse();
                let today = lemma_today(g).fin();
                assert!(
                    guarded.leq(today),
                    "{g:?}: C(fin) = {guarded:?} ≰ fin(today) = {today:?}"
                );
            }
        }
    }

    #[test]
    fn k9_finalization_does_not_commute_with_collapse() {
        let c = Cells {
            pos: Transfer::Must,
            neg: Transfer::Bot,
        };
        assert_eq!(c.fin().collapse(), Transfer::May);
        assert_eq!(c.collapse().fin(), Transfer::Must);
        assert_ne!(c.fin().collapse(), c.collapse().fin(), "the §7.3 witness");
    }

    fn collapse_all(x: [Cells; MAX_COORDS]) -> [Transfer; MAX_COORDS] {
        let [a, b, c] = x;
        [a.collapse(), b.collapse(), c.collapse()]
    }

    #[test]
    fn k11_one_step_lax_simulation_holds_for_every_state() {
        // C(F_G(X)) ≤ F_0(C(X)) pointwise, F_0 = the collapsed system (§7.2)
        for n in 1..=2 {
            for sys in systems_exhaustive(n) {
                let c = sys.collapsed();
                for a in all_cells() {
                    for b in all_cells() {
                        let x1 = if n > 1 { b } else { Cells::BOT };
                        let x = [a, x1, Cells::BOT];
                        let cx = [
                            Cells::diag(a.collapse()),
                            Cells::diag(x1.collapse()),
                            Cells::BOT,
                        ];
                        for i in 0..n {
                            assert!(
                                sys.step(i, &x).collapse().leq(c.step(i, &cx).collapse()),
                                "{sys:?} at {x:?}"
                            );
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn k11_lfp_lax_simulation_against_the_collapsed_system() {
        let check = |sys: &System| {
            let g = lfp(sys);
            let t = lfp(&sys.collapsed());
            for (gv, tv) in collapse_all(g).iter().zip(t.iter()).take(sys.n) {
                assert!(gv.leq(tv.collapse()), "{sys:?}: {g:?} vs {t:?}");
            }
        };
        for n in 1..=2 {
            for sys in systems_exhaustive(n) {
                check(&sys);
            }
        }
        let mut rng = Rng::new(0x6172);
        for _ in 0..20_000 {
            check(&random_system(&mut rng, 3));
        }
    }

    #[test]
    fn k11_lfp_lax_simulation_against_today_post_finalization_under_the_assumptions() {
        // G-T2 as stated: C(fin(lfp F_G)) ≤ fin(lfp F_0), F_0 = today's derivation
        let check = |sys: &System| {
            if !(release_cells_have_no_edges(sys) && no_unknown_seed(sys)) {
                return;
            }
            let g = lfp(sys);
            let t = lfp(&sys.today());
            for (gv, tv) in g.iter().zip(t.iter()).take(sys.n) {
                assert!(
                    gv.fin().collapse().leq(tv.fin().collapse()),
                    "{sys:?}: {g:?} vs {t:?}"
                );
                assert!(gv.collapse().leq(tv.collapse()), "pre-fin too: {sys:?}");
            }
        };
        for n in 1..=2 {
            for sys in systems_exhaustive(n) {
                check(&sys);
            }
        }
        let mut rng = Rng::new(0x70da);
        for _ in 0..20_000 {
            check(&random_system(&mut rng, 3));
        }
    }

    #[test]
    fn k11b_legacy_observational_compatibility_g_t2b() {
        // G-T2b as amended (A0.5): for consistent cell facts, the finalized
        // guarded collapse is below today's finalized value, OR the pair is
        // exactly (unknown, may) — the declared class-3 legacy-honesty
        // difference. No `no_unknown_seed` hypothesis.
        let check = |sys: &System| {
            if !release_cells_have_no_edges(sys) {
                return;
            }
            let g = lfp(sys);
            let t = lfp(&sys.today());
            for (gv, tv) in g.iter().zip(t.iter()).take(sys.n) {
                let (gc, tc) = (gv.fin().collapse(), tv.fin().collapse());
                assert!(
                    gc.leq(tc) || (gc == Transfer::Unknown && tc == Transfer::May),
                    "{sys:?}: guarded {gc:?} vs today {tc:?}"
                );
                // class 3 is verdict-equivalent under INF-A1
                if !gc.leq(tc) {
                    assert_eq!(crate::lower(gc), crate::lower(tc));
                }
            }
        };
        for n in 1..=2 {
            for sys in systems_exhaustive(n) {
                check(&sys);
            }
        }
        let mut rng = Rng::new(0x67b2);
        for _ in 0..20_000 {
            check(&random_system(&mut rng, 3));
        }
    }

    #[test]
    fn row14_bare_collapsed_baseline_is_not_a_post_finalization_bound() {
        // G-T2a is stated pre-finalization on purpose: F(p, g){ if (g)
        // release p; else F(p, g); } has guarded fin (must, no) → may, while
        // the collapsed semantic system says must — wrong for F(p, false).
        let f = Coord {
            shape: Shape::Split(0),
            seed: Cells {
                pos: Transfer::Must,
                neg: Transfer::Bot,
            },
            edges: [
                Some(Edge {
                    callee: 0,
                    transform: Transform::Id,
                    mask: Mask::NegOnly,
                }),
                None,
            ],
        };
        let sys = System {
            n: 1,
            coords: [f, DEAD, DEAD],
        };
        let g = first(lfp(&sys));
        let c = first(lfp(&sys.collapsed()));
        assert_eq!(g.fin().collapse(), Transfer::May);
        assert_eq!(c.fin().collapse(), Transfer::Must);
        assert!(
            g.collapse().leq(c.collapse()),
            "G-T2a holds pre-finalization: must ≤ must"
        );
        assert!(
            !g.fin().collapse().leq(c.fin().collapse()),
            "and fails post-finalization"
        );
        let t = first(lfp(&sys.today()));
        assert_eq!(
            t.fin().collapse(),
            Transfer::May,
            "today's synthetic borrow restores it (G-T2b)"
        );
    }

    #[test]
    fn k11_finding_release_priority_drops_an_unresolved_forward() {
        // if (g) p.Dispose(); else Extern(p);   with Extern unresolved (unknown)
        // guarded: (must, unknown) ⇒ collapse unknown; today: release priority
        // ⇒ [dispose, borrow] ⇒ may. unknown ≰ may: G-T2's ≤ fails, verdicts
        // agree (INF-A1 lowers may and unknown alike to plain + OWN051).
        let m = Coord {
            shape: Shape::Split(0),
            seed: Cells {
                pos: Transfer::Must,
                neg: Transfer::Bot,
            },
            edges: [
                Some(Edge {
                    callee: 1,
                    transform: Transform::Opaque,
                    mask: Mask::NegOnly,
                }),
                None,
            ],
        };
        let extern_ = Coord {
            shape: Shape::Uncond,
            seed: Cells::diag(Transfer::Unknown),
            edges: [None, None],
        };
        let sys = System {
            n: 2,
            coords: [m, extern_, DEAD],
        };
        assert!(sys.well_formed() && release_cells_have_no_edges(&sys) && !no_unknown_seed(&sys));
        let g = first(lfp(&sys));
        let t = first(lfp(&sys.today()));
        assert_eq!(g.collapse(), Transfer::Unknown);
        assert_eq!(t.collapse(), Transfer::May);
        assert!(
            !g.fin().collapse().leq(t.fin().collapse()),
            "the pinned violation"
        );
        assert_eq!(
            crate::lower(g.collapse()),
            crate::lower(t.collapse()),
            "same verdict class"
        );
    }
}

#[cfg(kani)]
mod proofs {
    use super::super::symbolic::{any_small_system, any_system};
    use super::{no_unknown_seed, release_cells_have_no_edges};
    use crate::{lemma_guarded, lemma_today, solve, Cells, Grounding, Transfer, MAX_COORDS};

    #[kani::proof]
    fn k9_residual_bottom_lemma_all_three_groundings() {
        let g: Grounding = kani::any();
        if let Grounding::PartialLocalRelease(t) = g {
            kani::assume(matches!(t, Transfer::Must | Transfer::May));
        }
        assert!(lemma_guarded(g).fin().collapse().leq(lemma_today(g).fin()));
    }

    #[kani::proof]
    fn k11_one_step_lax_simulation() {
        // the induction step of G-T2 §7.2 on a symbolic 3-coordinate SCC and
        // a symbolic state: C(F_G(X)) ≤ F_0(C(X))
        let sys = any_system();
        let x: [Cells; MAX_COORDS] = kani::any();
        let [x0, x1, x2] = x;
        let cx = [
            Cells::diag(x0.collapse()),
            Cells::diag(x1.collapse()),
            Cells::diag(x2.collapse()),
        ];
        let c = sys.collapsed();
        for i in 0..MAX_COORDS {
            assert!(sys.step(i, &x).collapse().leq(c.step(i, &cx).collapse()));
        }
    }

    #[kani::proof]
    #[kani::unwind(21)]
    fn k11_lfp_lax_simulation_against_the_collapsed_system_on_small_sccs() {
        let sys = any_small_system();
        let g = solve(&sys);
        let t = solve(&sys.collapsed());
        assert!(g.is_some() && t.is_some());
        if let (Some(g), Some(t)) = (g, t) {
            let [g0, g1, _] = g;
            let [t0, t1, _] = t;
            assert!(g0.collapse().leq(t0.collapse()) && g1.collapse().leq(t1.collapse()));
        }
    }

    #[kani::proof]
    #[kani::unwind(21)]
    fn k11b_legacy_observational_compatibility_on_small_sccs() {
        // G-T2b: guarded ≤ today, or exactly (unknown, may) — no no-unknown
        // hypothesis, consistent cell facts only
        let sys = any_small_system();
        kani::assume(release_cells_have_no_edges(&sys));
        let g = solve(&sys);
        let t = solve(&sys.today());
        assert!(g.is_some() && t.is_some());
        if let (Some(g), Some(t)) = (g, t) {
            let [g0, g1, _] = g;
            let [t0, t1, _] = t;
            for (gv, tv) in [(g0, t0), (g1, t1)] {
                let (gc, tc) = (gv.fin().collapse(), tv.fin().collapse());
                assert!(gc.leq(tc) || (gc == Transfer::Unknown && tc == Transfer::May));
            }
        }
    }

    #[kani::proof]
    #[kani::unwind(21)]
    fn k11_lfp_lax_simulation_against_today_post_finalization_on_small_sccs() {
        let sys = any_small_system();
        kani::assume(release_cells_have_no_edges(&sys) && no_unknown_seed(&sys));
        let g = solve(&sys);
        let t = solve(&sys.today());
        assert!(g.is_some() && t.is_some());
        if let (Some(g), Some(t)) = (g, t) {
            let [g0, g1, _] = g;
            let [t0, t1, _] = t;
            assert!(g0.fin().collapse().leq(t0.fin().collapse()));
            assert!(g1.fin().collapse().leq(t1.fin().collapse()));
        }
    }
}
