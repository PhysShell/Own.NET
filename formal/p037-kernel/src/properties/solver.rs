//! K10: the concrete solver terminates within the height bound, reaches a
//! fixpoint, the LEAST fixpoint, and is schedule-independent.

#[cfg(test)]
mod tests {
    use super::super::{all_cells, lfp, permutations, random_system, systems_exhaustive, Rng};
    use crate::{solve_with, Cells, System, MAX_COORDS};

    fn is_fixpoint(sys: &System, x: [Cells; MAX_COORDS]) -> bool {
        (0..sys.n).all(|i| x.get(i).copied() == Some(sys.step(i, &x)))
    }

    #[test]
    fn k10_lfp_is_the_least_fixpoint_exhaustive() {
        for n in 1..=2 {
            for sys in systems_exhaustive(n) {
                let least = lfp(&sys);
                assert!(is_fixpoint(&sys, least), "{sys:?}");
                for p in permutations(n) {
                    assert_eq!(solve_with(&sys, &p), Some(least), "{sys:?} under {p:?}");
                }
                // least: below every fixpoint of the (finite) domain
                for a in all_cells() {
                    for b in all_cells() {
                        let x = [a, if n > 1 { b } else { Cells::BOT }, Cells::BOT];
                        if is_fixpoint(&sys, x) {
                            assert!(
                                least.iter().zip(x.iter()).all(|(l, y)| l.leq(*y)),
                                "{sys:?}"
                            );
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn k10_lfp_is_schedule_independent_random() {
        let mut rng = Rng::new(0x0c1d);
        for _ in 0..20_000 {
            let sys = random_system(&mut rng, 3);
            let least = lfp(&sys);
            assert!(is_fixpoint(&sys, least));
            for p in permutations(3) {
                assert_eq!(solve_with(&sys, &p), Some(least), "{sys:?} under {p:?}");
            }
            assert_eq!(solve_with(&sys, &[2, 2, 0, 1, 0, 1, 2]), Some(least));
        }
    }
}

#[cfg(kani)]
mod proofs {
    //! Schedule-independence of a chaotic iteration follows from three facts
    //! the harnesses check separately, because the whole solver over a
    //! symbolic 3-coordinate SCC is beyond CBMC's memory: (a) `step` is
    //! monotone in the state, (b) `solve` returns a fixpoint below every
    //! fixpoint, and (c) on 2-coordinate SCCs with ≤ 1 edge each the chaotic
    //! result equals the Jacobi result under every fair schedule, directly.
    use super::super::symbolic::{any_index, any_schedule, any_small_system, any_system};
    use crate::{solve, solve_with, Cells, MAX_COORDS};

    fn leq_all(a: &[Cells; MAX_COORDS], b: &[Cells; MAX_COORDS]) -> bool {
        a.iter().zip(b.iter()).all(|(x, y)| x.leq(*y))
    }

    #[kani::proof]
    fn k10a_step_is_monotone_in_the_state() {
        let sys = any_system();
        let x: [Cells; MAX_COORDS] = kani::any();
        let y: [Cells; MAX_COORDS] = kani::any();
        kani::assume(leq_all(&x, &y));
        let i = any_index(sys.n);
        assert!(sys.step(i, &x).leq(sys.step(i, &y)));
    }

    #[kani::proof]
    #[kani::unwind(21)]
    fn k10b_solve_is_a_fixpoint_below_every_fixpoint() {
        let sys = any_system();
        let lfp = solve(&sys);
        assert!(lfp.is_some(), "terminates within the height bound");
        if let Some(x) = lfp {
            for i in 0..sys.n {
                assert_eq!(x.get(i).copied(), Some(sys.step(i, &x)));
            }
            let y: [Cells; MAX_COORDS] = kani::any();
            kani::assume((0..sys.n).all(|i| y.get(i).copied() == Some(sys.step(i, &y))));
            assert!(leq_all(&x, &y), "least");
        }
    }

    #[kani::proof]
    #[kani::unwind(21)]
    fn k10c_chaotic_equals_jacobi_on_small_sccs() {
        let sys = any_small_system();
        let sched = any_schedule(sys.n);
        let lfp = solve(&sys);
        assert!(lfp.is_some());
        assert_eq!(solve_with(&sys, &sched), lfp);
    }
}
