//! K6 (the G-A2 floor: consume only through a selected `must` cell or a
//! unanimous `must`), K7 (no fabricated consume), K13 (the worked rows of
//! P-037 §8 as concrete pins).

#[cfg(test)]
mod tests {
    use super::super::{all_cells, first, lfp, DEAD};
    use crate::{
        apply, lower, read, Cells, Coord, Edge, Lowered, Mask, Selection, Shape, System, Transfer,
        Transform,
    };

    fn selected(c: Cells, sel: Selection) -> Option<Transfer> {
        match sel {
            Selection::Pos => Some(c.fin().pos),
            Selection::Neg => Some(c.fin().neg),
            Selection::Unselected => None,
        }
    }

    #[test]
    fn k6_consume_only_through_a_selected_or_unanimous_must() {
        for c in all_cells() {
            for &sel in &Selection::ALL {
                for shape in [Shape::Uncond, Shape::Split(0)] {
                    if matches!(shape, Shape::Uncond) && !c.is_diag() {
                        continue; // an Uncond coordinate is a diagonal (K12)
                    }
                    let out = apply(shape, c, sel);
                    let f = c.fin();
                    let unanimous = f.pos == Transfer::Must && f.neg == Transfer::Must;
                    let picked = matches!(shape, Shape::Split(_))
                        && selected(c, sel) == Some(Transfer::Must);
                    assert_eq!(
                        out == Lowered::Consume,
                        picked || unanimous,
                        "{shape:?} {c:?} {sel:?}"
                    );
                    // G-A3: a selected `no` cell keeps the obligation with the caller
                    if matches!(shape, Shape::Split(_)) && selected(c, sel) == Some(Transfer::No) {
                        assert_eq!(out, Lowered::Borrow);
                    }
                    // an Uncond coordinate ignores the selection
                    if matches!(shape, Shape::Uncond) {
                        assert_eq!(out, apply(shape, c, Selection::Unselected));
                    }
                }
            }
        }
    }

    #[test]
    fn k7_unknown_opaque_and_differing_unselected_cells_never_consume() {
        for c in all_cells() {
            let f = c.fin();
            if f.pos != f.neg {
                assert_ne!(
                    apply(Shape::Split(0), c, Selection::Unselected),
                    Lowered::Consume,
                    "{c:?}"
                );
            }
            if f.pos == Transfer::Unknown {
                assert_eq!(apply(Shape::Split(0), c, Selection::Pos), Lowered::Plain);
            }
            if f.neg == Transfer::Unknown {
                assert_eq!(apply(Shape::Split(0), c, Selection::Neg), Lowered::Plain);
            }
            // an application-side read through an opaque edge consumes only
            // when both FINALIZED cells are must (G-A2 speaks of finalized cells)
            let r = read(Transform::Opaque, f);
            assert_eq!(
                lower(r.pos) == Lowered::Consume,
                f.pos == Transfer::Must && f.neg == Transfer::Must
            );
        }
        assert_eq!(
            lower(Transfer::Bot),
            Lowered::Borrow,
            "a raw ⊥ is finalized to no, never consumed"
        );
    }

    #[test]
    fn k7_witness_an_unfinalized_opaque_read_would_consume() {
        // Inside the solver ⊥ is the join identity (INF-L2), so an opaque read
        // of the UNfinalized pair (must, ⊥) is must — right for the fixpoint,
        // fatal at a call site: G-A2's "finalized" is load-bearing, and `apply`
        // therefore finalizes before it selects or collapses. A1 must keep
        // that order; this pin fails if anyone applies a raw solver value.
        let raw = Cells {
            pos: Transfer::Must,
            neg: Transfer::Bot,
        };
        assert_eq!(lower(read(Transform::Opaque, raw).pos), Lowered::Consume);
        assert_eq!(
            lower(read(Transform::Opaque, raw.fin()).pos),
            Lowered::Plain
        );
        assert_eq!(
            apply(Shape::Split(0), raw, Selection::Unselected),
            Lowered::Plain
        );
    }

    // ---- K13: P-037 §8 worked rows -----------------------------------------

    fn split(seed: Cells, edges: [Option<Edge>; 2]) -> Coord {
        Coord {
            shape: Shape::Split(0),
            seed,
            edges,
        }
    }

    fn uncond(t: Transfer) -> Coord {
        Coord {
            shape: Shape::Uncond,
            seed: Cells::diag(t),
            edges: [None, None],
        }
    }

    // the helper fills `Coord::edges` slots directly, hence the Option
    #[allow(clippy::unnecessary_wraps)]
    const fn edge(callee: usize, transform: Transform, mask: Mask) -> Option<Edge> {
        Some(Edge {
            callee,
            transform,
            mask,
        })
    }

    #[test]
    fn row1_teardown_skip() {
        // Teardown(bool skip){ if(!skip) release p; }  ⇒ Split(skip, no, must)
        let s = Cells {
            pos: Transfer::No,
            neg: Transfer::Must,
        };
        assert_eq!(
            apply(Shape::Split(0), s, Selection::Pos),
            Lowered::Borrow,
            "Teardown(true): honest OWN001"
        );
        assert_eq!(
            apply(Shape::Split(0), s, Selection::Neg),
            Lowered::Consume,
            "Teardown(false)"
        );
        assert_eq!(
            apply(Shape::Split(0), s, Selection::Unselected),
            Lowered::Plain,
            "Teardown(x): today"
        );
    }

    #[test]
    fn row3_dispose_bool_misplaced_release() {
        let canonical = Cells {
            pos: Transfer::Must,
            neg: Transfer::No,
        };
        assert_eq!(
            apply(Shape::Split(0), canonical, Selection::Pos),
            Lowered::Consume
        );
        let misplaced = Cells {
            pos: Transfer::No,
            neg: Transfer::Must,
        };
        assert_eq!(
            apply(Shape::Split(0), misplaced, Selection::Pos),
            Lowered::Borrow,
            "#305-B from the summary"
        );
    }

    #[test]
    fn rows7_8_wrapper_inherits_the_split_through_id_and_neg() {
        let inner = split(
            Cells {
                pos: Transfer::No,
                neg: Transfer::Must,
            },
            [None, None],
        );
        let outer_id = split(Cells::BOT, [edge(1, Transform::Id, Mask::Both), None]);
        let sys = System {
            n: 2,
            coords: [outer_id, inner, DEAD],
        };
        let x = first(lfp(&sys));
        assert_eq!(
            x,
            Cells {
                pos: Transfer::No,
                neg: Transfer::Must
            }
        );
        assert_eq!(
            apply(Shape::Split(0), x, Selection::Neg),
            Lowered::Consume,
            "Outer(false)"
        );
        let outer_neg = split(Cells::BOT, [edge(1, Transform::Neg, Mask::Both), None]);
        let sys = System {
            n: 2,
            coords: [outer_neg, inner, DEAD],
        };
        let x = first(lfp(&sys));
        assert_eq!(
            x,
            Cells {
                pos: Transfer::Must,
                neg: Transfer::No
            }
        );
        assert_eq!(
            apply(Shape::Split(0), x, Selection::Pos),
            Lowered::Consume,
            "Outer(true)"
        );
    }

    #[test]
    fn row9_alternating_recursion_is_unanimous_must() {
        // F(p, g){ if (g) release p; else F(p, !g); }
        let f = split(
            Cells {
                pos: Transfer::Must,
                neg: Transfer::Bot,
            },
            [edge(0, Transform::Neg, Mask::NegOnly), None],
        );
        let sys = System {
            n: 1,
            coords: [f, DEAD, DEAD],
        };
        let x = first(lfp(&sys));
        assert_eq!(x, Cells::diag(Transfer::Must));
        assert_eq!(
            apply(Shape::Split(0), x, Selection::Unselected),
            Lowered::Consume,
            "G-A2 route 2"
        );
    }

    #[test]
    fn rows12_13_mixed_release_forward_consumes_without_selection() {
        // if (g) release p; else MustSink(p);
        let m = split(
            Cells {
                pos: Transfer::Must,
                neg: Transfer::Bot,
            },
            [edge(1, Transform::Opaque, Mask::NegOnly), None],
        );
        let sys = System {
            n: 2,
            coords: [m, uncond(Transfer::Must), DEAD],
        };
        let x = first(lfp(&sys));
        assert_eq!(x.collapse(), Transfer::Must);
        assert_eq!(
            apply(Shape::Split(0), x, Selection::Unselected),
            Lowered::Consume,
            "row 13"
        );
        // today's read of the same body: release priority ⇒ may (§7.1)
        let t = first(lfp(&sys.today()));
        assert_eq!(t.collapse(), Transfer::May);
    }

    #[test]
    fn row14_one_cell_residual_bottom() {
        // F(p, g){ if (g) release p; else F(p, g); }
        let f = split(
            Cells {
                pos: Transfer::Must,
                neg: Transfer::Bot,
            },
            [edge(0, Transform::Id, Mask::NegOnly), None],
        );
        let sys = System {
            n: 1,
            coords: [f, DEAD, DEAD],
        };
        let x = first(lfp(&sys));
        assert_eq!(
            x,
            Cells {
                pos: Transfer::Must,
                neg: Transfer::Bot
            },
            "lfp keeps the residual ⊥"
        );
        assert_eq!(
            x.fin(),
            Cells {
                pos: Transfer::Must,
                neg: Transfer::No
            }
        );
        assert_eq!(x.fin().collapse(), Transfer::May);
        assert_eq!(
            apply(Shape::Split(0), x, Selection::Unselected),
            Lowered::Plain
        );
        assert_eq!(apply(Shape::Split(0), x, Selection::Pos), Lowered::Consume);
        assert_eq!(
            apply(Shape::Split(0), x, Selection::Neg),
            Lowered::Borrow,
            "F(p, false): honest OWN001"
        );
        let t = first(lfp(&sys.today()));
        assert_eq!(
            t.fin().collapse(),
            Transfer::May,
            "today: partial release ⇒ may — equal"
        );
    }

    #[test]
    fn row16_forward_grounded_residual_bottom() {
        // F(p, g){ if (g) MustSink(p); else F(p, g); }
        let f = split(
            Cells::BOT,
            [
                edge(1, Transform::Opaque, Mask::PosOnly),
                edge(0, Transform::Id, Mask::NegOnly),
            ],
        );
        let sys = System {
            n: 2,
            coords: [f, uncond(Transfer::Must), DEAD],
        };
        let x = first(lfp(&sys));
        assert_eq!(
            x,
            Cells {
                pos: Transfer::Must,
                neg: Transfer::Bot
            }
        );
        assert_eq!(x.fin().collapse(), Transfer::May);
        let t = first(lfp(&sys.today()));
        assert_eq!(
            t.fin().collapse(),
            Transfer::May,
            "today: forwards + synthetic borrow ⇒ may — equal"
        );
    }

    #[test]
    fn row17_none_coordinate_refined_through_const_pos() {
        // Outer(Resource p){ Inner(p, true); }, Inner = Split(g, must, no)
        let inner = split(
            Cells {
                pos: Transfer::Must,
                neg: Transfer::No,
            },
            [None, None],
        );
        let outer = Coord {
            shape: Shape::Uncond,
            seed: Cells::BOT,
            edges: [edge(1, Transform::ConstPos, Mask::Both), None],
        };
        let sys = System {
            n: 2,
            coords: [outer, inner, DEAD],
        };
        let x = first(lfp(&sys));
        assert_eq!(x, Cells::diag(Transfer::Must));
        assert_eq!(
            apply(Shape::Uncond, x, Selection::Unselected),
            Lowered::Consume
        );
        let t = first(lfp(&sys.today()));
        assert_eq!(
            t.collapse(),
            Transfer::May,
            "today: Inner = may forwards into may"
        );
    }

    #[test]
    fn row18_mutated_guard_degrades_to_opaque() {
        // the frontend degrades the edge to opaque (G-V4): reading join(must, no) = may
        let inner = split(
            Cells {
                pos: Transfer::Must,
                neg: Transfer::No,
            },
            [None, None],
        );
        let outer = split(Cells::BOT, [edge(1, Transform::Opaque, Mask::Both), None]);
        let sys = System {
            n: 2,
            coords: [outer, inner, DEAD],
        };
        let x = first(lfp(&sys));
        assert_eq!(
            apply(Shape::Split(0), x, Selection::Pos),
            Lowered::Plain,
            "never consume"
        );
    }
}

#[cfg(kani)]
mod proofs {
    use crate::{apply, lower, read, Cells, Lowered, Selection, Shape, Transfer, Transform};

    #[kani::proof]
    fn k6_consume_only_through_a_selected_or_unanimous_must() {
        let c: Cells = kani::any();
        let sel: Selection = kani::any();
        let shape: Shape = kani::any();
        kani::assume(matches!(shape, Shape::Split(_)) || c.is_diag());
        let out = apply(shape, c, sel);
        let f = c.fin();
        let picked = match (shape, sel) {
            (Shape::Split(_), Selection::Pos) => f.pos == Transfer::Must,
            (Shape::Split(_), Selection::Neg) => f.neg == Transfer::Must,
            _ => false,
        };
        let unanimous = f.pos == Transfer::Must && f.neg == Transfer::Must;
        assert_eq!(out == Lowered::Consume, picked || unanimous);
        if matches!(shape, Shape::Uncond) {
            assert_eq!(out, apply(shape, c, Selection::Unselected));
        }
    }

    #[kani::proof]
    fn k7_no_fabricated_consume() {
        let c: Cells = kani::any();
        let f = c.fin();
        if f.pos != f.neg {
            assert_ne!(
                apply(Shape::Split(0), c, Selection::Unselected),
                Lowered::Consume
            );
        }
        if f.pos == Transfer::Unknown {
            assert_eq!(apply(Shape::Split(0), c, Selection::Pos), Lowered::Plain);
        }
        if f.neg == Transfer::Unknown {
            assert_eq!(apply(Shape::Split(0), c, Selection::Neg), Lowered::Plain);
        }
        let r = read(Transform::Opaque, f);
        assert_eq!(
            lower(r.pos) == Lowered::Consume,
            f.pos == Transfer::Must && f.neg == Transfer::Must
        );
        assert_eq!(lower(Transfer::Bot), Lowered::Borrow);
        // the unfinalized witness: (must, ⊥) reads as must inside the solver,
        // so application MUST finalize first — and `apply` does
        let raw = Cells {
            pos: Transfer::Must,
            neg: Transfer::Bot,
        };
        assert_eq!(lower(read(Transform::Opaque, raw).pos), Lowered::Consume);
        assert_eq!(
            apply(Shape::Split(0), raw, Selection::Unselected),
            Lowered::Plain
        );
    }
}
