(* Generic solver theory for P-037 (INF-F3 / G-F1 / G-T2a), unbounded.

   For ANY finite coordinate type I (any number of coordinates) and ANY
   join-semilattice L with bottom and a strict rank bounded by h:
   - Kleene/Jacobi iteration of a monotone F from bot reaches the least
     pre-fixpoint within #|I| * h steps, and the Rust `lfp_jacobi` loop
     with #|I| * h + 1 passes returns exactly it           (K10a/b, unbounded);
   - every FAIR chaotic schedule, run as the Rust `lfp_chaotic` loop, returns
     the same least fixpoint within the same pass budget     (K10c, unbounded);
   - a one-step lax simulation lifts to the least fixpoints  (G-T2a lift).
   Kani checks these at 3 coordinates / 2 edges (K10b) and 2 coordinates /
   1 edge (K10c, K11 at the lfp); the note calls the rest "the standard
   argument". Here it is the argument, checked. *)

From mathcomp Require Import boot.

Set Implicit Arguments.
Unset Strict Implicit.
Unset Printing Implicit Defensive.

Section Solver.

Variable L : eqType.
Variables (join : L -> L -> L) (bot : L).
Hypothesis joinC : forall x y, join x y = join y x.
Hypothesis joinA : forall x y z, join x (join y z) = join (join x y) z.
Hypothesis joinxx : forall x, join x x = x.
Hypothesis join0x : forall x, join bot x = x.

(* The order induced by the join, as the Rust kernel defines `leq`. *)
Definition le x y := join x y == y.

Lemma le_refl x : le x x. Proof. by rewrite /le joinxx. Qed.
Lemma bot_le x : le bot x. Proof. by rewrite /le join0x. Qed.
Lemma le_trans y x z : le x y -> le y z -> le x z.
Proof. by rewrite /le => /eqP <- /eqP <-; rewrite joinA joinA joinxx. Qed.
Lemma le_anti x y : le x y -> le y x -> x = y.
Proof. by rewrite /le joinC => /eqP -> /eqP. Qed.

Lemma le_joinl x y : le x (join x y). Proof. by rewrite /le joinA joinxx. Qed.
Lemma le_joinr x y : le y (join x y). Proof. by rewrite joinC le_joinl. Qed.
Lemma join_lub x y z : le x z -> le y z -> le (join x y) z.
Proof. by rewrite /le => /eqP hx /eqP hy; rewrite -joinA hy hx. Qed.
Lemma le_join2 x x' y y' : le x x' -> le y y' -> le (join x y) (join x' y').
Proof.
move=> hx hy; apply: join_lub; first exact: le_trans hx (le_joinl _ _).
exact: le_trans hy (le_joinr _ _).
Qed.

(* A strict rank bounded by h: the finite-height hypothesis (G-L3). *)
Variables (rank : L -> nat) (h : nat).
Hypothesis rank_lt : forall x y, le x y -> x != y -> rank x < rank y.
Hypothesis rank_h : forall x, rank x <= h.

Variable I : finType.
Local Notation state := {ffun I -> L}.
Implicit Types (x y z : state) (a b : state * bool).

Definition sle (x y : state) := [forall i, le (x i) (y i)].
Definition sbot : state := [ffun=> bot].
Definition srank (x : state) := \sum_i rank (x i).
Definition N := #|I| * h.

Lemma sleP x y : reflect (forall i, le (x i) (y i)) (sle x y).
Proof. exact: forallP. Qed.
Lemma sle_refl x : sle x x. Proof. by apply/sleP => i; exact: le_refl. Qed.
Lemma sbot_le x : sle sbot x. Proof. by apply/sleP => i; rewrite ffunE bot_le. Qed.
Lemma sle_trans y x z : sle x y -> sle y z -> sle x z.
Proof. by move=> /sleP xy /sleP yz; apply/sleP => i; exact: le_trans (xy i) (yz i). Qed.
Lemma sle_anti x y : sle x y -> sle y x -> x = y.
Proof. by move=> /sleP xy /sleP yx; apply/ffunP => i; exact: le_anti. Qed.

Lemma srank_le x : srank x <= N.
Proof.
by rewrite /N -sum_nat_const /srank; apply: leq_sum => i _; exact: rank_h.
Qed.

Lemma srank_lt x y : sle x y -> x != y -> srank x < srank y.
Proof.
move=> /sleP xy nxy.
have [i ni] : exists i, x i != y i.
  apply/existsP; apply: contraNT nxy => /existsPn e.
  by apply/eqP/ffunP => i; apply/eqP/negbNE/e.
rewrite /srank (bigD1 i) //= [X in _ < X](bigD1 i) //=.
rewrite -addSn; apply: leq_add; first exact: rank_lt.
apply: leq_sum => j _; case: (eqVneq (x j) (y j)) => [-> // | nj].
exact/ltnW/rank_lt.
Qed.

(* ---- Jacobi / Kleene iteration ------------------------------------------ *)

Variable F : state -> state.
Hypothesis F_mono : forall x y, sle x y -> sle (F x) (F y).

Definition it k := iter k F sbot.

Lemma it_up k : sle (it k) (it k.+1).
Proof.
elim: k => [|k IH]; first exact: sbot_le.
by rewrite /it !iterS; apply: F_mono.
Qed.

(* Below every pre-fixpoint: stronger than K10b's "below every fixpoint". *)
Lemma it_below y k : sle (F y) y -> sle (it k) y.
Proof.
move=> pre; elim: k => [|k IH]; first exact: sbot_le.
by rewrite /it iterS; apply: sle_trans pre; apply: F_mono.
Qed.

Lemma it_climb k : F (it k) != it k -> k < srank (it k.+1).
Proof.
elim: k => [|k IH] ne.
  by apply: leq_ltn_trans (leq0n _) (srank_lt (it_up 0) _); rewrite eq_sym.
have ne' : F (it k) != it k.
  by apply: contra ne => /eqP e; change (F (F (it k)) == F (it k)); rewrite e e.
apply: leq_ltn_trans (IH ne') (srank_lt (it_up k.+1) _).
by rewrite eq_sym.
Qed.

Definition lfp := it N.

Lemma lfp_fix : F lfp = lfp.
Proof.
apply/eqP; apply: contraT => ne.
by have := leq_ltn_trans (srank_le (it N.+1)) (it_climb ne); rewrite ltnn.
Qed.

Lemma lfp_least y : sle (F y) y -> sle lfp y. Proof. exact: it_below. Qed.

Lemma fix_is_lfp x : F x = x -> sle x lfp -> x = lfp.
Proof. by move=> fx xl; apply: sle_anti xl (lfp_least _); rewrite fx sle_refl. Qed.

Lemma it_stable m : it (N + m) = lfp.
Proof. by elim: m => [|m IH]; rewrite ?addn0 // addnS /it iterS -/(it _) IH lfp_fix. Qed.

(* The Rust `lfp_jacobi` loop, literally: compute next; if next == x return
   x; else continue. `max_passes` = MAX_COORDS * HEIGHT + 1 = N + 1. *)
Fixpoint jacobi (fuel : nat) (x : state) : option state :=
  if fuel is f.+1 then (if F x == x then Some x else jacobi f (F x)) else None.

Theorem jacobi_is_lfp : jacobi N.+1 sbot = Some lfp.
Proof.
have below k : sle (it k) lfp by apply: it_below; rewrite lfp_fix sle_refl.
suff gen f k : N <= k + f -> jacobi f.+1 (it k) = Some lfp by exact: (gen N 0).
elim: f k => [|f IH] k hk /=; case: ifP => [/eqP fx | /negbT nfx].
- by rewrite (fix_is_lfp fx (below k)).
- rewrite addn0 in hk.
  have e : it k = lfp by rewrite -(subnKC hk) it_stable.
  by move: nfx; rewrite -/(it k) e lfp_fix eqxx.
- by rewrite (fix_is_lfp fx (below k)).
- by apply: (IH k.+1); rewrite addSnnS.
Qed.

(* ---- Chaotic (Gauss-Seidel) iteration ----------------------------------- *)

(* One update of the Rust loop: v = step(i, x); if x_i != v, write it and
   mark the pass as changed. *)
Definition upd (xc : state * bool) (i : I) : state * bool :=
  let: (x, c) := xc in
  if x i == F x i then (x, c) else ([ffun j => if j == i then F x i else x j], true).

(* The Rust `lfp_chaotic` loop: passes over `sched` until one changes nothing. *)
Fixpoint chaotic (sched : seq I) (fuel : nat) (x : state) : option state :=
  if fuel is f.+1 then
    let: (x', c) := foldl upd (x, false) sched in
    if c then chaotic sched f x' else Some x'
  else None.

(* Invariant: below the lfp and a post-fixpoint (x <= F x). *)
Definition inv x := sle x lfp && sle x (F x).

(* b is reachable from a by updates: invariant kept, ascending, and either
   nothing happened or the change flag is set and the state really moved. *)
Definition grows (a b : state * bool) :=
  [/\ inv b.1, sle a.1 b.1 & b = a \/ (b.2 /\ b.1 != a.1)].

Lemma upd_grows a i : inv a.1 -> grows a (upd a i).
Proof.
case: a => x c /andP[/sleP xl /sleP xF] /=; case: ifP => [_ | /negbT ne].
  by split=> //; [apply/andP; split; apply/sleP | apply: sle_refl | left].
have xx' : sle x [ffun j => if j == i then F x i else x j].
  by apply/sleP => j; rewrite ffunE; case: eqP => [-> | _]; [exact: xF | exact: le_refl].
split=> //=; last first.
  right; split=> //; apply: contra ne => /eqP/ffunP/(_ i) e.
  by rewrite -e ffunE eqxx.
apply/andP; split; apply/sleP => j; rewrite ffunE; case: eqP => [-> | _].
- by rewrite -lfp_fix; move/sleP: (F_mono (introT (sleP _ _) xl)); apply.
- exact: xl.
- by move/sleP: (F_mono xx'); apply.
- by apply: le_trans (xF j) _; move/sleP: (F_mono xx'); apply.
Qed.

Lemma grows_trans a b c : grows a b -> grows b c -> grows a c.
Proof.
case=> _ ab bab [ic bc cbc]; split=> //; first exact: sle_trans ab bc.
case: cbc => [-> // | [c2 ncb]]; right; split=> //.
case: bab => [eba | [b2 nba]]; first by rewrite -eba.
apply: contra nba => /eqP cea.
by apply/eqP/sle_anti => //; rewrite -cea.
Qed.

Lemma fold_grows s a : inv a.1 -> grows a (foldl upd a s).
Proof.
elim: s a => [|i s IH] a ia /=.
  by split=> //; [apply: sle_refl | left].
have g := upd_grows i ia; case: (g) => ig _ _; exact: grows_trans g (IH _ ig).
Qed.

Lemma fold_true s x : (foldl upd (x, true) s).2.
Proof. by elim: s x => [|i s IH] x //=; case: ifP => _; apply: IH. Qed.

Lemma fold_quiet s x : ~~ (foldl upd (x, false) s).2 -> forall i, i \in s -> x i = F x i.
Proof.
elim: s => [|a s IH] //=; case: ifP => [/eqP e | _]; last by rewrite fold_true.
by move=> q i; rewrite inE => /orP[/eqP -> // | /(IH q)].
Qed.

Theorem chaotic_is_lfp sched : (forall i, i \in sched) -> chaotic sched N.+1 sbot = Some lfp.
Proof.
move=> fair.
suff gen f x : inv x -> N < f + srank x -> chaotic sched f x = Some lfp.
  by apply: gen; [apply/andP; split; apply: sbot_le | rewrite addSn ltnS leq_addr].
elim: f x => [|f IH] x ix hN /=.
  by move: (leq_ltn_trans (srank_le x) hN); rewrite ltnn.
have := fold_grows sched (a := (x, false)) ix.
case E: (foldl upd (x, false) sched) => [x' c] [ix' xx' ch] /=.
rewrite /= in ix' xx' ch.
case: c E ch => E ch.
  case: ch => [[] // | [_ /= nx]]; apply: IH ix' _.
  by apply: leq_trans hN _; rewrite addSnnS leq_add2l srank_lt // eq_sym.
have -> : x' = x by case: ch => [[] | []].
have fx : F x = x.
  apply/ffunP => i; symmetry; apply: (fold_quiet (s := sched)); last exact: fair.
  by rewrite E.
by congr Some; apply: fix_is_lfp fx _; case/andP: ix.
Qed.

(* ---- Lax simulation lifts to the least fixpoints (G-T2a) ---------------- *)

Variable G : state -> state.
Hypothesis G_mono : forall x y, sle x y -> sle (G x) (G y).
Variable alpha : state -> state.
Hypothesis alpha_bot : alpha sbot = sbot.
Hypothesis alpha_step : forall x, sle (alpha (F x)) (G (alpha x)).

Lemma lax_simulation_it k : sle (alpha (it k)) (iter k G sbot).
Proof.
elim: k => [|k IH]; first by rewrite alpha_bot sle_refl.
by apply: sle_trans (alpha_step _) (G_mono IH).
Qed.

(* alpha(lfp F) <= lfp G: the right-hand side is `lfp` of the section
   instantiated at G (same N), i.e. G's least fixpoint by the theorems above. *)
Theorem lax_simulation_lfp : sle (alpha lfp) (iter N G sbot).
Proof. exact: lax_simulation_it. Qed.

End Solver.
