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
    use super::super::symbolic::{any_schedule, any_system};
    use crate::{solve, solve_with};

    #[kani::proof]
    #[kani::unwind(21)]
    fn k10_lfp_is_a_schedule_independent_fixpoint() {
        let sys = any_system();
        let sched = any_schedule(sys.n);
        let lfp = solve(&sys);
        assert!(lfp.is_some(), "terminates within the height bound");
        if let Some(x) = lfp {
            for i in 0..sys.n {
                assert_eq!(x.get(i).copied(), Some(sys.step(i, &x)));
            }
        }
        assert_eq!(solve_with(&sys, &sched), lfp);
    }
}
