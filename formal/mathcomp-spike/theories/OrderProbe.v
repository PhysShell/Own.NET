(* C7 probe: what MathComp's order hierarchy gives the P-037 lattice.
   Result recorded in docs/notes/mathcomp-ownnet-spike.md G. *)
From HB Require Import structures.
From mathcomp Require Import boot order.
From P037Spike Require Import P037.
Import Order.Theory DefaultProdOrder.
Local Open Scope order_scope.

Fact transfer_display : Order.disp_t. Proof. exact: Order.Disp tt tt. Qed.
Definition tle a b := tjoin a b == b.
Fact tle_refl : reflexive tle. Proof. by case. Qed.
Fact tle_anti : antisymmetric tle. Proof. by case; case. Qed.
Fact tle_trans : transitive tle. Proof. by case; case; case. Qed.
HB.instance Definition _ := Order.Le_isPOrder.Build transfer_display transfer tle_refl tle_anti tle_trans.
Fact leEjoin x y : (y <= x) = (tjoin x y == x). Proof. by rewrite /Order.le /= /tle tjoinC. Qed.
HB.instance Definition _ := Order.POrder_Join_isSemilattice.Build transfer_display transfer tjoinC tjoinA leEjoin.
Fact le0t (x : transfer) : Bot <= x. Proof. by case: x. Qed.
HB.instance Definition _ := Order.hasBottom.Build transfer_display transfer le0t.

(* What we get: *)
Check (Bot `|` Must).
Check (fun c d : transfer * transfer => c <= d).
Check (fun c d : transfer * transfer => c `|` d).
Check (fun c : transfer * transfer => \bot <= c).
Goal forall a b c d : transfer, a <= c -> b <= d -> a `|` b <= c `|` d.
Proof. by move=> *; apply: leU2. Qed.
Goal forall c d : transfer * transfer, c `|` d = d `|` c.
Proof. exact: joinC. Qed.
(* Not available: no order instance on {ffun I -> L} (the solver's state
   space), so `x <= y` for states does not typecheck; pointwise order and the
   fixpoint theory (none in boot/order; finset's `fixset` is for sets only)
   stay hand-written as in Lfp.v. *)
Fail Check (fun (I : finType) (x y : {ffun I -> transfer}) => x <= y).
