//! K1 (transfer join laws), K2 (election join laws), K5 (collapse).

#[cfg(test)]
mod tests {
    use super::super::{all_cells, all_elections};
    use crate::{Cells, Election, Transfer};

    #[test]
    fn k1_transfer_join_is_commutative_associative_idempotent() {
        for &a in &Transfer::ALL {
            assert_eq!(a.join(a), a, "idempotent {a:?}");
            assert_eq!(a.join(Transfer::Bot), a, "⊥ identity {a:?}");
            assert_eq!(
                a.join(Transfer::Unknown),
                Transfer::Unknown,
                "unknown absorbs {a:?}"
            );
            for &b in &Transfer::ALL {
                assert_eq!(a.join(b), b.join(a), "commutative {a:?} {b:?}");
                for &c in &Transfer::ALL {
                    assert_eq!(
                        a.join(b).join(c),
                        a.join(b.join(c)),
                        "associative {a:?} {b:?} {c:?}"
                    );
                }
            }
        }
    }

    #[test]
    fn k1_transfer_order_is_a_partial_order_of_height_three() {
        for &a in &Transfer::ALL {
            assert!(a.leq(a));
            for &b in &Transfer::ALL {
                if a.leq(b) && b.leq(a) {
                    assert_eq!(a, b, "antisymmetric");
                }
                for &c in &Transfer::ALL {
                    if a.leq(b) && b.leq(c) {
                        assert!(a.leq(c), "transitive {a:?} {b:?} {c:?}");
                    }
                }
            }
        }
        assert!(!Transfer::No.leq(Transfer::Must) && !Transfer::Must.leq(Transfer::No));
        assert!(Transfer::Bot.leq(Transfer::No) && Transfer::No.leq(Transfer::May));
        assert!(Transfer::May.leq(Transfer::Unknown));
    }

    #[test]
    fn k1_cells_inherit_the_laws_componentwise() {
        for a in all_cells() {
            assert_eq!(a.join(a), a);
            assert_eq!(a.join(Cells::BOT), a);
            for b in all_cells() {
                assert_eq!(a.join(b), b.join(a));
                assert_eq!(a.leq(b), a.pos.leq(b.pos) && a.neg.leq(b.neg));
                for c in all_cells() {
                    assert_eq!(a.join(b).join(c), a.join(b.join(c)));
                }
            }
        }
    }

    #[test]
    fn k2_election_join_is_commutative_associative_idempotent() {
        let all = all_elections();
        for &a in &all {
            assert_eq!(a.join(a), a);
            assert_eq!(a.join(Election::None), a, "None is the identity");
            assert_eq!(
                a.join(Election::Conflict),
                Election::Conflict,
                "Conflict absorbs"
            );
            for &b in &all {
                assert_eq!(a.join(b), b.join(a));
                for &c in &all {
                    assert_eq!(a.join(b).join(c), a.join(b.join(c)));
                }
            }
        }
        assert_eq!(Election::One(0).join(Election::One(1)), Election::Conflict);
        assert!(!Election::One(0).leq(Election::One(1)));
    }

    #[test]
    fn k5_collapse_is_monotone_and_a_join_morphism() {
        for a in all_cells() {
            assert_eq!(Cells::diag(a.pos).collapse(), a.pos, "C(Uncond(t)) = t");
            for b in all_cells() {
                if a.leq(b) {
                    assert!(a.collapse().leq(b.collapse()), "monotone {a:?} {b:?}");
                }
                assert_eq!(
                    a.join(b).collapse(),
                    a.collapse().join(b.collapse()),
                    "morphism"
                );
            }
        }
    }

    #[test]
    fn finalization_is_not_monotone_and_the_note_says_so() {
        // ⊥ ≤ must, but fin(⊥) = no is incomparable with must: nothing in
        // P-037 claims fin is monotone, and the harnesses never assume it.
        assert!(Transfer::Bot.leq(Transfer::Must));
        assert!(!Transfer::Bot.fin().leq(Transfer::Must.fin()));
    }
}

#[cfg(kani)]
mod proofs {
    use crate::{Cells, Election, Transfer};

    #[kani::proof]
    fn k1_transfer_join_laws() {
        let a: Transfer = kani::any();
        let b: Transfer = kani::any();
        let c: Transfer = kani::any();
        assert_eq!(a.join(b), b.join(a));
        assert_eq!(a.join(b).join(c), a.join(b.join(c)));
        assert_eq!(a.join(a), a);
        assert_eq!(a.join(Transfer::Bot), a);
        assert_eq!(a.join(Transfer::Unknown), Transfer::Unknown);
    }

    #[kani::proof]
    fn k1_transfer_order_is_a_partial_order() {
        let a: Transfer = kani::any();
        let b: Transfer = kani::any();
        let c: Transfer = kani::any();
        assert!(a.leq(a));
        if a.leq(b) && b.leq(a) {
            assert_eq!(a, b);
        }
        if a.leq(b) && b.leq(c) {
            assert!(a.leq(c));
        }
    }

    #[kani::proof]
    fn k1_cells_join_laws() {
        let a: Cells = kani::any();
        let b: Cells = kani::any();
        let c: Cells = kani::any();
        assert_eq!(a.join(b), b.join(a));
        assert_eq!(a.join(b).join(c), a.join(b.join(c)));
        assert_eq!(a.join(a), a);
        assert_eq!(a.join(Cells::BOT), a);
    }

    #[kani::proof]
    fn k2_election_join_laws() {
        let a: Election = kani::any();
        let b: Election = kani::any();
        let c: Election = kani::any();
        assert_eq!(a.join(b), b.join(a));
        assert_eq!(a.join(b).join(c), a.join(b.join(c)));
        assert_eq!(a.join(a), a);
        assert_eq!(a.join(Election::None), a);
        assert_eq!(a.join(Election::Conflict), Election::Conflict);
    }

    #[kani::proof]
    fn k5_collapse_monotone_and_join_morphism() {
        let a: Cells = kani::any();
        let b: Cells = kani::any();
        if a.leq(b) {
            assert!(a.collapse().leq(b.collapse()));
        }
        assert_eq!(a.join(b).collapse(), a.collapse().join(b.collapse()));
        let t: Transfer = kani::any();
        assert_eq!(Cells::diag(t).collapse(), t);
    }
}
