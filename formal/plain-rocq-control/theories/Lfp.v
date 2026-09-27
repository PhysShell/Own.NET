(* Generic solver theory for P-037 (INF-F3 / G-F1 / G-T2a), unbounded.
   PLAIN-ROCQ CONTROL of formal/mathcomp-spike/theories/Lfp.v (#367): the
   same statements, with Corelib + Stdlib only (no MathComp, HB or elpi).

   For ANY finite coordinate type I (any number of coordinates) and ANY
   join-semilattice L with bottom and a strict rank bounded by h:
   - Kleene/Jacobi iteration of a monotone F from bot reaches the least
     pre-fixpoint within |I| * h steps, and the Rust `lfp_jacobi` loop
     with |I| * h + 1 passes returns exactly it           (K10a/b, unbounded);
   - every FAIR chaotic schedule, run as the Rust `lfp_chaotic` loop, returns
     the same least fixpoint within the same pass budget   (K10c, unbounded);
   - a one-step lax simulation lifts to the least fixpoints (G-T2a lift).

   Representation: a state is a plain function I -> L. Its equality is
   pointwise (=1), decided by `seq_eq` over the enumeration of I, and that is
   exactly what MathComp's `x = y` on {ffun I -> L} means (ffunP). So
   `jacobi .. = Some lfp` there reads `exists x, jacobi .. = Some x /\ x =1 lfp`
   here. No axiom is used. *)

From Corelib Require Import ssreflect ssrfun ssrbool.
From Stdlib Require Import Arith Lia List.

Set Implicit Arguments.
Unset Strict Implicit.

(* ---- generic support: what finType / {ffun} / bigop gave for free ------- *)

(* A finite coordinate type: decidable equality and a complete enumeration. *)
Record finIx := FinIx {
  ix :> Type;
  ix_eqb : ix -> ix -> bool;
  ix_eqbP : forall a b, reflect (a = b) (ix_eqb a b);
  ix_enum : list ix;
  ix_enumP : forall a, In a ix_enum }.

Lemma forallb_false A (f : A -> bool) l :
  forallb f l = false -> exists a, In a l /\ f a = false.
Proof.
elim: l => [|a l IH] //=; case E: (f a) => /= H; last by exists a; auto.
by case: (IH H) => b [? ?]; exists b; auto.
Qed.

Lemma sum_le A (f g : A -> nat) l :
  (forall a, f a <= g a) -> list_sum (map f l) <= list_sum (map g l).
Proof. by move=> fg; elim: l => [|a l IH] //=; have := fg a; lia. Qed.

Lemma sum_lt A (f g : A -> nat) l a :
  (forall b, f b <= g b) -> In a l -> f a < g a -> list_sum (map f l) < list_sum (map g l).
Proof.
move=> fg; elim: l => [|b l IH] //= [<- | /IH H] lt; first by have := sum_le l fg; lia.
by have := fg b; have := H lt; lia.
Qed.

Section Solver.

Variables (L : Type) (eqL : L -> L -> bool).
Hypothesis eqLP : forall x y, reflect (x = y) (eqL x y).
Variables (join : L -> L -> L) (bot : L).
Hypothesis joinC : forall x y, join x y = join y x.
Hypothesis joinA : forall x y z, join x (join y z) = join (join x y) z.
Hypothesis joinxx : forall x, join x x = x.
Hypothesis join0x : forall x, join bot x = x.

(* The order induced by the join, as the Rust kernel defines `leq`. *)
Definition le x y := eqL (join x y) y.

Lemma le_refl x : le x x. Proof. by rewrite /le joinxx; apply/eqLP. Qed.
Lemma bot_le x : le bot x. Proof. by rewrite /le join0x; apply/eqLP. Qed.
Lemma le_trans y x z : le x y -> le y z -> le x z.
Proof. by rewrite /le => /eqLP <- /eqLP <-; rewrite joinA joinA joinxx; apply/eqLP. Qed.
Lemma le_anti x y : le x y -> le y x -> x = y.
Proof. by rewrite /le joinC => /eqLP -> /eqLP. Qed.

Lemma le_joinl x y : le x (join x y). Proof. by rewrite /le joinA joinxx; apply/eqLP. Qed.
Lemma le_joinr x y : le y (join x y). Proof. by rewrite joinC le_joinl. Qed.
Lemma join_lub x y z : le x z -> le y z -> le (join x y) z.
Proof. by rewrite /le => /eqLP hx /eqLP hy; rewrite -joinA hy hx; apply/eqLP. Qed.
Lemma le_join2 x x' y y' : le x x' -> le y y' -> le (join x y) (join x' y').
Proof.
move=> hx hy; apply: join_lub; first exact: le_trans hx (le_joinl _ _).
exact: le_trans hy (le_joinr _ _).
Qed.

(* A strict rank bounded by h: the finite-height hypothesis (G-L3). *)
Variables (rank : L -> nat) (h : nat).
Hypothesis rank_lt : forall x y, le x y -> ~~ eqL x y -> rank x < rank y.
Hypothesis rank_h : forall x, rank x <= h.

Lemma rank_le x y : le x y -> rank x <= rank y.
Proof. by case E: (eqL x y) => l; [move/eqLP: E => ->; lia | have := rank_lt l (negbT E); lia]. Qed.

Variable I : finIx.
Local Notation state := (I -> L).
Implicit Types (x y z : state) (a b : state * bool).

Definition sle x y := forall i, le (x i) (y i).
Definition seq_eq x y := forallb (fun i => eqL (x i) (y i)) (ix_enum I).
Definition sbot : state := fun _ => bot.
Definition srank x := list_sum (map (fun i => rank (x i)) (ix_enum I)).
Definition N := length (ix_enum I) * h.

Lemma seq_eqP x y : reflect (x =1 y) (seq_eq x y).
Proof.
apply: (iffP idP) => [/forallb_forall H i | H]; first by apply/eqLP/H/ix_enumP.
by apply/forallb_forall => i _; apply/eqLP.
Qed.
Lemma seq_eq_congr x x' y y' : x =1 x' -> y =1 y' -> seq_eq x y = seq_eq x' y'.
Proof.
move=> ex ey; apply/idP/idP => /seq_eqP e; apply/seq_eqP => i.
  by rewrite -ex -ey. by rewrite ex ey.
Qed.

Lemma sle_refl x : sle x x. Proof. by move=> i; exact: le_refl. Qed.
Lemma sbot_le x : sle sbot x. Proof. by move=> i; exact: bot_le. Qed.
Lemma sle_trans y x z : sle x y -> sle y z -> sle x z.
Proof. by move=> xy yz i; exact: le_trans (xy i) (yz i). Qed.
Lemma sle_anti x y : sle x y -> sle y x -> x =1 y.
Proof. by move=> xy yx i; exact: le_anti. Qed.

Lemma srank_le x : srank x <= N.
Proof.
rewrite /srank /N; elim: (ix_enum I) => [|i l IH] //=.
by have := rank_h (x i); lia.
Qed.

Lemma srank_lt x y : sle x y -> ~~ seq_eq y x -> srank x < srank y.
Proof.
move=> xy /negbTE /forallb_false [i [_ /negbT ni]].
rewrite /srank; apply: (sum_lt (fun j => rank_le (xy j)) (ix_enumP i)); apply: rank_lt (xy i) _.
by apply: contra ni => /eqLP ->; apply/eqLP.
Qed.

(* ---- Jacobi / Kleene iteration ------------------------------------------ *)

Variable F : state -> state.
Hypothesis F_mono : forall x y, sle x y -> sle (F x) (F y).

(* Monotone already forces F to respect pointwise equality: no extra hypothesis. *)
Lemma F_ext x y : x =1 y -> F x =1 F y.
Proof.
move=> e; apply: sle_anti; apply: F_mono => i; rewrite e; exact: le_refl.
Qed.

Definition it k := Nat.iter k F sbot.

Lemma it_up k : sle (it k) (it (S k)).
Proof. elim: k => [|k IH]; first exact: sbot_le. exact: F_mono. Qed.

(* Below every pre-fixpoint: stronger than K10b's "below every fixpoint". *)
Lemma it_below y k : sle (F y) y -> sle (it k) y.
Proof.
move=> pre; elim: k => [|k IH]; first exact: sbot_le.
by apply: sle_trans pre; apply: F_mono.
Qed.

Lemma it_climb k : ~~ seq_eq (F (it k)) (it k) -> k < srank (it (S k)).
Proof.
elim: k => [|k IH] ne; first by have := srank_lt (it_up 0) ne; lia.
have ne' : ~~ seq_eq (F (it k)) (it k).
  apply: contra ne => /seq_eqP e; apply/seq_eqP => i; exact: F_ext e i.
by have := IH ne'; have := srank_lt (it_up (S k)) ne; lia.
Qed.

Definition lfp := it N.

Lemma lfp_fix : F lfp =1 lfp.
Proof.
apply/seq_eqP; case E: (seq_eq _ _) => //.
by have := it_climb (negbT E); have := srank_le (it (S N)); lia.
Qed.

Lemma lfp_least y : sle (F y) y -> sle lfp y. Proof. exact: it_below. Qed.

Lemma fix_is_lfp x : F x =1 x -> sle x lfp -> x =1 lfp.
Proof. by move=> fx xl; apply: sle_anti xl (lfp_least _) => i; rewrite fx; exact: le_refl. Qed.

Lemma it_stable m : it (N + m) =1 lfp.
Proof.
elim: m => [|m IH] i; first by rewrite Nat.add_0_r.
by rewrite Nat.add_succ_r /=; rewrite (F_ext IH) lfp_fix.
Qed.

(* The Rust `lfp_jacobi` loop, literally: compute next; if next == x return
   x; else continue. `max_passes` = MAX_COORDS * HEIGHT + 1 = N + 1. *)
Fixpoint jacobi (fuel : nat) (x : state) : option state :=
  if fuel is S f then (if seq_eq (F x) x then Some x else jacobi f (F x)) else None.

Theorem jacobi_is_lfp : exists x, jacobi (S N) sbot = Some x /\ x =1 lfp.
Proof.
have below k : sle (it k) lfp by apply: it_below => i; rewrite lfp_fix; exact: le_refl.
suff gen f k : N <= k + f -> exists x, jacobi (S f) (it k) = Some x /\ x =1 lfp.
  exact: (gen N 0).
elim: f k => [|f IH] k hk /=; case: ifP => [/seq_eqP fx | /negbT nfx].
- by exists (it k); split=> //; exact: fix_is_lfp fx (below k).
- have e : it k =1 lfp by rewrite (_ : k = N + (k - N)); [lia | exact: it_stable].
  by case/negP: nfx; apply/seq_eqP => i; rewrite (F_ext e) lfp_fix e.
- by exists (it k); split=> //; exact: fix_is_lfp fx (below k).
- by apply: (IH (S k)); lia.
Qed.

(* ---- Chaotic (Gauss-Seidel) iteration ----------------------------------- *)

(* One update of the Rust loop: v = step(i, x); if x_i != v, write it and
   mark the pass as changed. *)
Definition upd (xc : state * bool) (i : I) : state * bool :=
  let: (x, c) := xc in
  if eqL (x i) (F x i) then (x, c) else (fun j => if ix_eqb j i then F x i else x j, true).

(* The Rust `lfp_chaotic` loop: passes over `sched` until one changes nothing. *)
Fixpoint chaotic (sched : list I) (fuel : nat) (x : state) : option state :=
  if fuel is S f then
    let: (x', c) := fold_left upd sched (x, false) in
    if c then chaotic sched f x' else Some x'
  else None.

(* Invariant: below the lfp and a post-fixpoint (x <= F x). *)
Definition inv x := sle x lfp /\ sle x (F x).

(* b is reachable from a by updates: invariant kept, ascending, and either
   nothing happened or the change flag is set and the state really moved. *)
Definition grows a b :=
  [/\ inv b.1, sle a.1 b.1 & (b.1 =1 a.1 /\ b.2 = a.2) \/ (b.2 = true /\ ~~ seq_eq b.1 a.1)].

Lemma upd_grows a i : inv a.1 -> grows a (upd a i).
Proof.
case: a => x c [xl xF] /=; case: ifP => [_ | /negbT ne].
  by split=> //; [apply: sle_refl | left].
set x' := fun j => if ix_eqb j i then F x i else x j.
have xx' : sle x x'.
  by move=> j; rewrite /x'; case: ix_eqbP => [-> | _]; [exact: xF | exact: le_refl].
split=> //=; last first.
  right; split=> //; apply: contra ne => /seq_eqP/(_ i) e.
  by move: e; rewrite /x'; case: ix_eqbP => // _ ->; apply/eqLP.
split=> j; rewrite /x'; case: ix_eqbP => [-> | _].
- by have := F_mono xl i; rewrite lfp_fix.
- exact: xl.
- exact: F_mono xx' i.
- exact: le_trans (xF j) (F_mono xx' j).
Qed.

Lemma grows_trans a b c : grows a b -> grows b c -> grows a c.
Proof.
case=> _ ab bab [ic bc cbc]; split=> //; first exact: sle_trans ab bc.
case: cbc => [[ecb e2] | [c2 ncb]].
  case: bab => [[eba e2'] | [b2 nba]].
    by left; split; [move=> i; rewrite ecb eba | congruence].
  by right; split; [congruence | rewrite (seq_eq_congr ecb (fun _ => erefl))].
right; split=> //; apply: contra ncb => /seq_eqP ca; apply/seq_eqP.
have ba : b.1 =1 a.1 by apply: sle_anti ab => i; rewrite -ca; exact: bc.
by move=> i; rewrite ca ba.
Qed.

Lemma fold_grows s a : inv a.1 -> grows a (fold_left upd s a).
Proof.
elim: s a => [|i s IH] a ia /=.
  by split=> //; [apply: sle_refl | left].
have g := upd_grows i ia; case: (g) => ig _ _; exact: grows_trans g (IH _ ig).
Qed.

Lemma fold_true s x : (fold_left upd s (x, true)).2 = true.
Proof. by elim: s x => [|i s IH] x //=; case: ifP => _; apply: IH. Qed.

Lemma fold_quiet s x : (fold_left upd s (x, false)).2 = false -> forall i, In i s -> x i = F x i.
Proof.
elim: s => [|a s IH] //=; case: ifP => [/eqLP e | _]; last by rewrite fold_true.
by move=> q i [<- // | /(IH q)].
Qed.

Theorem chaotic_is_lfp sched : (forall i, In i sched) ->
  exists x, chaotic sched (S N) sbot = Some x /\ x =1 lfp.
Proof.
move=> fair.
suff gen f x : inv x -> N < f + srank x -> exists x', chaotic sched f x = Some x' /\ x' =1 lfp.
  by apply: gen; [split; apply: sbot_le | lia].
elim: f x => [|f IH] x ix hN /=.
  by have := srank_le x; lia.
have := fold_grows sched (a := (x, false)) ix.
case E: (fold_left upd sched (x, false)) => [x' c] [ix' xx' ch] /=.
rewrite /= in ix' xx' ch.
case: c E ch => E ch.
  case: ch => [[_] // | [_ nx]]; apply: IH ix' _.
  by have := srank_lt xx' nx; lia.
have ex : x' =1 x by case: ch => [[] | []].
have fx : F x =1 x.
  move=> i; symmetry; apply: (fold_quiet (s := sched)); last exact: fair.
  by rewrite E.
exists x'; split=> // i; rewrite ex; case: ix => xl _; exact: fix_is_lfp fx xl i.
Qed.

(* ---- Lax simulation lifts to the least fixpoints (G-T2a) ---------------- *)

Variable G : state -> state.
Hypothesis G_mono : forall x y, sle x y -> sle (G x) (G y).
Variable alpha : state -> state.
Hypothesis alpha_bot : alpha sbot =1 sbot.
Hypothesis alpha_step : forall x, sle (alpha (F x)) (G (alpha x)).

Lemma lax_simulation_it k : sle (alpha (it k)) (Nat.iter k G sbot).
Proof.
elim: k => [|k IH]; first by move=> i; rewrite alpha_bot; exact: le_refl.
by apply: sle_trans (alpha_step _) (G_mono IH).
Qed.

(* alpha(lfp F) <= lfp G: the right-hand side is `lfp` of the section
   instantiated at G (same N), i.e. G's least fixpoint by the theorems above. *)
Theorem lax_simulation_lfp : sle (alpha lfp) (Nat.iter N G sbot).
Proof. exact: lax_simulation_it. Qed.

End Solver.
