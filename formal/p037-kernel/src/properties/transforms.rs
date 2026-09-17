//! K3 (every G-F2 transform and the G-S4 mask are monotone), K8 (id/neg
//! involutions), K12 (`Uncond` coordinates stay diagonal under the solver),
//! and the read-below-collapse lemma K11 rests on.

#[cfg(test)]
mod tests {
    use super::super::{all_cells, lfp, random_system, systems_exhaustive, Rng};
    use crate::{contribute, read, Cells, Mask, Shape, Transform};

    #[test]
    fn k3_reads_and_contributions_are_monotone() {
        for &t in &Transform::ALL {
            for a in all_cells() {
                for b in all_cells() {
                    if a.leq(b) {
                        assert!(read(t, a).leq(read(t, b)), "{t:?} {a:?} {b:?}");
                        for &m in &Mask::ALL {
                            assert!(contribute(m, read(t, a)).leq(contribute(m, read(t, b))));
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn k3_every_read_component_is_below_the_collapse() {
        // the one-line lemma behind G-T2 §7.2: a projected, swapped or mapped
        // cell is ≤ the join of the cells, and masking only lowers.
        for &t in &Transform::ALL {
            for c in all_cells() {
                let r = read(t, c);
                assert!(
                    r.pos.leq(c.collapse()) && r.neg.leq(c.collapse()),
                    "{t:?} {c:?}"
                );
                for &m in &Mask::ALL {
                    assert!(contribute(m, r).leq(r));
                }
            }
        }
    }

    #[test]
    fn k8_id_and_neg_are_involutions_and_the_rest_are_diagonal() {
        for c in all_cells() {
            assert_eq!(read(Transform::Id, read(Transform::Id, c)), c);
            assert_eq!(read(Transform::Neg, read(Transform::Neg, c)), c);
            assert_eq!(read(Transform::Neg, c), c.swap());
            assert_eq!(read(Transform::ConstPos, c), Cells::diag(c.pos));
            assert_eq!(read(Transform::ConstNeg, c), Cells::diag(c.neg));
            assert_eq!(read(Transform::Opaque, c), Cells::diag(c.collapse()));
            assert!(read(Transform::Opaque, c).is_diag());
        }
    }

    #[test]
    fn k12_uncond_coordinates_stay_diagonal_exhaustive() {
        for n in 1..=2 {
            for sys in systems_exhaustive(n) {
                let x = lfp(&sys);
                for (c, v) in sys.coords.iter().zip(x.iter()).take(sys.n) {
                    if matches!(c.shape, Shape::Uncond) {
                        assert!(v.is_diag(), "{sys:?} -> {x:?}");
                    }
                }
            }
        }
    }

    #[test]
    fn k12_uncond_coordinates_stay_diagonal_random() {
        let mut rng = Rng::new(0xd1a6);
        for _ in 0..20_000 {
            let sys = random_system(&mut rng, 3);
            let x = lfp(&sys);
            for (c, v) in sys.coords.iter().zip(x.iter()).take(sys.n) {
                if matches!(c.shape, Shape::Uncond) {
                    assert!(v.is_diag(), "{sys:?} -> {x:?}");
                }
            }
        }
    }
}

#[cfg(kani)]
mod proofs {
    use crate::{contribute, read, solve, Cells, Mask, Shape, System, Transform, MAX_COORDS};

    #[kani::proof]
    fn k3_reads_and_contributions_are_monotone() {
        let t: Transform = kani::any();
        let m: Mask = kani::any();
        let a: Cells = kani::any();
        let b: Cells = kani::any();
        if a.leq(b) {
            assert!(read(t, a).leq(read(t, b)));
            assert!(contribute(m, read(t, a)).leq(contribute(m, read(t, b))));
        }
        let r = read(t, a);
        assert!(r.pos.leq(a.collapse()) && r.neg.leq(a.collapse()));
        assert!(contribute(m, r).leq(r));
    }

    #[kani::proof]
    fn k8_involutions() {
        let c: Cells = kani::any();
        assert_eq!(read(Transform::Id, read(Transform::Id, c)), c);
        assert_eq!(read(Transform::Neg, read(Transform::Neg, c)), c);
        assert!(read(Transform::Opaque, c).is_diag());
        assert!(read(Transform::ConstPos, c).is_diag());
        assert!(read(Transform::ConstNeg, c).is_diag());
    }

    #[kani::proof]
    #[kani::unwind(21)]
    fn k12_uncond_coordinates_stay_diagonal() {
        let sys: System = kani::any();
        kani::assume(sys.n >= 1 && sys.n <= MAX_COORDS && sys.well_formed());
        let x = solve(&sys);
        assert!(x.is_some(), "terminates within the height bound");
        if let Some(x) = x {
            for (c, v) in sys.coords.iter().zip(x.iter()).take(sys.n) {
                if matches!(c.shape, Shape::Uncond) {
                    assert!(v.is_diag());
                }
            }
        }
    }
}
