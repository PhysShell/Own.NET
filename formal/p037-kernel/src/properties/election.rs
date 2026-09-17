//! K4 (election import is monotone, Conflict propagates) and the election
//! pre-solver's order independence (K10, election half); P-037 §8 row 11.

#[cfg(test)]
mod tests {
    use super::super::{
        all_bindings, all_elections, first, lfp_election, permutations, random_election_system, Rng,
    };
    use crate::{
        elect_with, import, shape_of, Election, ElectionCoord, ElectionEdge, ElectionSystem,
        GuardBinding, Shape, MAX_EDGES,
    };

    #[test]
    fn k4_import_is_monotone_and_conflict_propagates() {
        for &b in &all_bindings() {
            assert_eq!(import(Election::None, b), Election::None);
            assert_eq!(import(Election::Conflict, b), Election::Conflict);
            for &e1 in &all_elections() {
                for &e2 in &all_elections() {
                    if e1.leq(e2) {
                        assert!(
                            import(e1, b).leq(import(e2, b)),
                            "{e1:?} ⊑ {e2:?} under {b:?}"
                        );
                    }
                }
            }
        }
        // the map is NOT a join-morphism (One(h) ⊔ One(h') = Conflict imports
        // as Conflict, while the imports join to One(g) or None): only
        // monotonicity is claimed by G-S1, and only monotonicity is proven.
        let b = GuardBinding::Id {
            callee: 0,
            caller: 2,
        };
        assert_ne!(
            import(Election::One(0).join(Election::One(1)), b),
            import(Election::One(0), b).join(import(Election::One(1), b))
        );
    }

    #[test]
    fn k4_import_maps_exactly_the_bound_guard() {
        assert_eq!(
            import(
                Election::One(1),
                GuardBinding::Id {
                    callee: 1,
                    caller: 2
                }
            ),
            Election::One(2)
        );
        assert_eq!(
            import(
                Election::One(1),
                GuardBinding::Neg {
                    callee: 1,
                    caller: 0
                }
            ),
            Election::One(0)
        );
        assert_eq!(
            import(
                Election::One(1),
                GuardBinding::Id {
                    callee: 0,
                    caller: 2
                }
            ),
            Election::None
        );
        assert_eq!(
            import(Election::One(1), GuardBinding::Const),
            Election::None
        );
        assert_eq!(
            import(Election::One(1), GuardBinding::Opaque),
            Election::None
        );
        assert_eq!(shape_of(Election::One(1)), Shape::Split(1));
        assert_eq!(shape_of(Election::Conflict), Shape::Uncond);
        assert_eq!(shape_of(Election::None), Shape::Uncond);
    }

    #[test]
    fn k10_election_lfp_is_schedule_independent_random() {
        let mut rng = Rng::new(0x5eed_e1ec);
        for _ in 0..20_000 {
            let n = 1_usize.saturating_add(rng.below(3));
            let sys = random_election_system(&mut rng, n);
            assert!(sys.well_formed());
            let jacobi = lfp_election(&sys);
            for p in permutations(n) {
                assert_eq!(elect_with(&sys, &p), Some(jacobi), "{sys:?} under {p:?}");
            }
            // a fair schedule with repeats
            assert_eq!(elect_with(&sys, &[0, 0, 2, 1, 1, 0]), Some(jacobi));
            for (i, &v) in jacobi.iter().enumerate() {
                assert_eq!(sys.step(i, &jacobi), v, "a fixpoint");
            }
        }
    }

    #[test]
    fn row11_late_conflict_cannot_leave_a_stale_import() {
        // W(bool f){ Inner(f); } imports Inner's election through an Id binding.
        let edge = ElectionEdge {
            callee: 1,
            binding: GuardBinding::Id {
                callee: 0,
                caller: 1,
            },
        };
        let w = ElectionCoord {
            seed: Election::None,
            edges: [Some(edge), None],
        };
        let dead = ElectionCoord {
            seed: Election::None,
            edges: [None; MAX_EDGES],
        };
        let inner_one = ElectionCoord {
            seed: Election::One(0),
            edges: [None; MAX_EDGES],
        };
        let sys = ElectionSystem {
            n: 2,
            coords: [w, inner_one, dead],
        };
        assert_eq!(
            first(lfp_election(&sys)),
            Election::One(1),
            "the wrapper inherits the split"
        );
        // Inner's election grows to Conflict: the lfp re-runs and W collapses.
        let inner_conflict = ElectionCoord {
            seed: Election::Conflict,
            edges: [None; MAX_EDGES],
        };
        let sys2 = ElectionSystem {
            n: 2,
            coords: [w, inner_conflict, dead],
        };
        assert_eq!(first(lfp_election(&sys2)), Election::Conflict);
        assert_eq!(shape_of(first(lfp_election(&sys2))), Shape::Uncond);
    }
}

#[cfg(kani)]
mod proofs {
    use crate::{elect, elect_with, import, Election, ElectionSystem, GuardBinding, MAX_COORDS};

    #[kani::proof]
    fn k4_import_is_monotone_and_conflict_propagates() {
        let e1: Election = kani::any();
        let e2: Election = kani::any();
        let b: GuardBinding = kani::any();
        if e1.leq(e2) {
            assert!(import(e1, b).leq(import(e2, b)));
        }
        assert_eq!(import(Election::Conflict, b), Election::Conflict);
        assert_eq!(import(Election::None, b), Election::None);
    }

    #[kani::proof]
    #[kani::unwind(9)]
    fn k10_election_lfp_is_schedule_independent() {
        let sys: ElectionSystem = kani::any();
        kani::assume(sys.n >= 1 && sys.n <= MAX_COORDS && sys.well_formed());
        let sched: [usize; MAX_COORDS] = kani::any();
        kani::assume(sched.iter().all(|&i| i < sys.n));
        kani::assume((0..sys.n).all(|i| sched.contains(&i)));
        let jacobi = elect(&sys);
        assert!(jacobi.is_some(), "terminates within the height bound");
        assert_eq!(elect_with(&sys, &sched), jacobi);
    }
}
