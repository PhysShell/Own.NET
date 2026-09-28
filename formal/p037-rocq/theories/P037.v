(* The P-037 kernel of formal/p037-kernel/src/lib.rs, transposed, and the
   generic theorems of Lfp.v instantiated on it.
   PLAIN-ROCQ CONTROL of formal/mathcomp-spike/theories/P037.v (#367).

   Every finite operation below is pinned EXTENSIONALLY to the Rust kernel by
   Correspondence.v (full truth tables exported from the crate itself). The
   structural parts (`step`, `collapsed`, the two solver loops) are hand-
   transposed and cross-checked on exported solver vectors. *)

From Corelib Require Import ssreflect ssrfun ssrbool.
From Stdlib Require Import Arith List.
From PlainSpike Require Import Lfp.

Set Implicit Arguments.
Unset Strict Implicit.

(* The generated RustTables.v is shared with the MathComp spike verbatim; it
   spells lists MathComp-style. *)
Notation seq := list.
Notation "[:: ]" := nil (format "[:: ]").
Notation "[:: x1 ; .. ; xn ]" := (cons x1 .. (cons xn nil) ..).

(* ---- INF-L1/L2: the base transfer lattice ------------------------------- *)

Inductive transfer := Bot | No | Must | May | Unknown.
Scheme Equality for transfer.
Lemma teqP a b : reflect (a = b) (transfer_beq a b). Proof. by case: a; case: b; constructor. Qed.

Definition tjoin a b :=
  match a, b with
  | Bot, x | x, Bot => x
  | Unknown, _ | _, Unknown => Unknown
  | No, No => No
  | Must, Must => Must
  | _, _ => May
  end.
Definition fin t := if t is Bot then No else t.

Lemma tjoinC a b : tjoin a b = tjoin b a. Proof. by case: a; case: b. Qed.
Lemma tjoinA a b c : tjoin a (tjoin b c) = tjoin (tjoin a b) c.
Proof. by case: a; case: b; case: c. Qed.
Lemma tjoinxx a : tjoin a a = a. Proof. by case: a. Qed.

(* G-L3 height: Bot < No | Must < May < Unknown. *)
Definition trank t := match t with Bot => 0 | No | Must => 1 | May => 2 | Unknown => 3 end.

(* ---- G-L2: product cells (pos, neg) ------------------------------------- *)

Definition cells := (transfer * transfer)%type.
Definition cbot : cells := (Bot, Bot).
Definition diag t : cells := (t, t).
Definition cjoin (c d : cells) : cells := (tjoin c.1 d.1, tjoin c.2 d.2).
Definition collapse (c : cells) := tjoin c.1 c.2.
Definition cfin (c : cells) : cells := (fin c.1, fin c.2).
Definition crank (c : cells) := trank c.1 + trank c.2.
Definition ceqb (c d : cells) := transfer_beq c.1 d.1 && transfer_beq c.2 d.2.
Lemma ceqP c d : reflect (c = d) (ceqb c d).
Proof.
case: c d => [a b] [a' b']; rewrite /ceqb /=; apply: (iffP andP) => [[/teqP -> /teqP ->] | [-> ->]] //.
by split; apply/teqP.
Qed.

(* Candidate B: the product inherits the laws cellwise, from the base laws. *)
Lemma cjoinC c d : cjoin c d = cjoin d c. Proof. by rewrite /cjoin tjoinC (tjoinC c.2). Qed.
Lemma cjoinA c d e : cjoin c (cjoin d e) = cjoin (cjoin c d) e.
Proof. by rewrite /cjoin /= !tjoinA. Qed.
Lemma cjoinxx c : cjoin c c = c. Proof. by case: c => a b; rewrite /cjoin !tjoinxx. Qed.
Lemma cjoin0x c : cjoin cbot c = c. Proof. by case: c. Qed.

Notation cle := (le ceqb cjoin).

(* Explicit enumerations; finite facts are decided with `forallb` over them. *)
Definition tall := [:: Bot; No; Must; May; Unknown].
Definition call : seq cells := flat_map (fun a => map (fun b => (a, b)) tall) tall.
Lemma tallP t : In t tall. Proof. by case: t; simpl; tauto. Qed.
Lemma callP (c : cells) : In c call.
Proof. by case: c => a b; apply/in_flat_map; exists a; split; [apply: tallP | apply/in_map/tallP]. Qed.

(* The rank is strict and bounded by HEIGHT = 6: decided over all 625 pairs. *)
Definition crank_b :=
  forallb (fun c => forallb (fun d =>
    cle c d ==> ~~ ceqb c d ==> Nat.ltb (crank c) (crank d)) call) call
  && forallb (fun c => Nat.leb (crank c) 6) call.
Lemma crank_ok : crank_b. Proof. by vm_compute. Qed.

Lemma crank_lt c d : cle c d -> ~~ ceqb c d -> crank c < crank d.
Proof.
case/andP: crank_ok => /forallb_forall/(_ c (callP c))/forallb_forall/(_ d (callP d)) H _ l n.
by apply/Nat.ltb_lt; move: H; rewrite l n.
Qed.
Lemma crank_h c : crank c <= 6.
Proof. by case/andP: crank_ok => _ /forallb_forall/(_ c (callP c))/Nat.leb_le. Qed.

(* ---- G-S5 / G-F2 / G-S4: edge transforms and branch masks --------------- *)

Inductive transform := ConstPos | ConstNeg | Id | Neg | Opaque.
Inductive mask := Both | PosOnly | NegOnly.
Scheme Equality for transform.
Scheme Equality for mask.

Definition read t (c : cells) : cells :=
  match t with
  | ConstPos => diag c.1 | ConstNeg => diag c.2 | Id => c
  | Neg => (c.2, c.1) | Opaque => diag (collapse c)
  end.
Definition contribute m (r : cells) : cells :=
  match m with Both => r | PosOnly => (r.1, Bot) | NegOnly => (Bot, r.2) end.

(* ---- G-F1: one SCC of ANY size, ANY number of edges per coordinate ------ *)

Record edge (I : Type) := Edge { callee : I; xf : transform; msk : mask }.
Record system (I : finIx) := System { seed : I -> cells; edges : I -> seq (edge I) }.

Section Sys.
Variable I : finIx.
Implicit Types (S : system I).

(* `System::step`: the seed joined, left to right, with every masked,
   transformed edge read — the Rust loop's exact fold order. *)
Definition contrib (x : I -> cells) (e : edge I) := contribute (msk e) (read (xf e) (x (callee e))).
Definition step S (x : I -> cells) i :=
  fold_left (fun acc e => cjoin acc (contrib x e)) (edges S i) (seed S i).
Definition FS S (x : I -> cells) : I -> cells := fun i => step S x i.

(* `System::collapsed` (F_0 of G-T2 §7.2): seeds collapsed onto the diagonal,
   every edge read opaquely with no mask. *)
Definition collapsed S :=
  System (fun i => diag (collapse (seed S i)))
         (fun i => map (fun e => Edge (callee e) Opaque Both) (edges S i)).

End Sys.

(* ---- Finite facts, decided by computation ------------------------------- *)

Definition xall := [:: ConstPos; ConstNeg; Id; Neg; Opaque].
Definition mall := [:: Both; PosOnly; NegOnly].

(* K3 (every read and mask monotone) and the §7.2 lemma (a masked read sits
   below the collapse), as booleans over the whole finite domain. *)
Definition contrib_mono_b :=
  forallb (fun m => forallb (fun t => forallb (fun c => forallb (fun d =>
     cle c d ==> cle (contribute m (read t c)) (contribute m (read t d))) call) call) xall) mall.
Definition contrib_below_b :=
  forallb (fun m => forallb (fun t => forallb (fun c =>
     transfer_beq (tjoin (collapse (contribute m (read t c))) (collapse c)) (collapse c)) call) xall) mall.
Definition collapse_morph_b :=
  forallb (fun c => forallb (fun d =>
     transfer_beq (collapse (cjoin c d)) (tjoin (collapse c) (collapse d))) call) call.

Lemma contrib_mono_ok : contrib_mono_b. Proof. by vm_compute. Qed.
Lemma contrib_below_ok : contrib_below_b. Proof. by vm_compute. Qed.
Lemma collapse_morph_ok : collapse_morph_b. Proof. by vm_compute. Qed.

Lemma xallP t : In t xall. Proof. by case: t; simpl; tauto. Qed.
Lemma mallP m : In m mall. Proof. by case: m; simpl; tauto. Qed.

Lemma contrib_mono m t c d : cle c d -> cle (contribute m (read t c)) (contribute m (read t d)).
Proof.
move: contrib_mono_ok => /forallb_forall/(_ m (mallP m))/forallb_forall/(_ t (xallP t)).
by move=> /forallb_forall/(_ c (callP c))/forallb_forall/(_ d (callP d))/implyP.
Qed.
Lemma contrib_below m t c : tjoin (collapse (contribute m (read t c))) (collapse c) = collapse c.
Proof.
apply/teqP; move: contrib_below_ok => /forallb_forall/(_ m (mallP m)).
by move=> /forallb_forall/(_ t (xallP t))/forallb_forall/(_ c (callP c)).
Qed.
Lemma collapse_morph c d : collapse (cjoin c d) = tjoin (collapse c) (collapse d).
Proof.
apply/teqP; move: collapse_morph_ok => /forallb_forall/(_ c (callP c)).
by move=> /forallb_forall/(_ d (callP d)).
Qed.

Lemma collapse_diag t : collapse (diag t) = t. Proof. exact: tjoinxx. Qed.
Lemma diag_join s t : diag (tjoin s t) = cjoin (diag s) (diag t). Proof. by []. Qed.

Lemma cle_join2 a a' b b' : cle a a' -> cle b b' -> cle (cjoin a b) (cjoin a' b').
Proof. exact: (le_join2 ceqP cjoinC cjoinA cjoinxx). Qed.

(* ---- G-A1 / G-A2: application at the call site ------------------------- *)

Inductive selection := SelPos | SelNeg | Unselected.
Inductive lowered := Consume | Borrow | Plain.
Inductive shape := Uncond | Split.  (* the split's guard index is irrelevant here *)
Scheme Equality for selection.
Scheme Equality for lowered.
Scheme Equality for shape.

(* INF-A1: a raw Bot is finalized first (G-L4). *)
Definition lower t := match fin t with Must => Consume | No => Borrow | _ => Plain end.
(* G-A1/G-A2: finalize, then select a cell or lower the collapse (F2). *)
Definition apply sh c sel :=
  let f := cfin c in
  match sh, sel with
  | Split, SelPos => lower f.1
  | Split, SelNeg => lower f.2
  | _, _ => lower (collapse f)
  end.

(* K6, the G-A2 floor: consume iff a selected finalized `must` cell or a
   unanimous finalized `must` (Uncond coordinates are diagonal, K12). Finite:
   re-proved here only as the carrier of the unsafe-application control. *)
Definition sall := [:: SelPos; SelNeg; Unselected].
Definition isMust t := transfer_beq t Must.
Definition k6_b :=
  forallb (fun sh => forallb (fun c => forallb (fun sel =>
    (shape_beq sh Split || transfer_beq c.1 c.2) ==>
    Bool.eqb (lowered_beq (apply sh c sel) Consume)
     ((shape_beq sh Split && match sel with
                            | SelPos => isMust (cfin c).1
                            | SelNeg => isMust (cfin c).2
                            | Unselected => false end)
      || isMust (cfin c).1 && isMust (cfin c).2)) sall) call) [:: Uncond; Split].
Lemma k6_ok : k6_b. Proof. by vm_compute. Qed.

(* ---- The instance: unbounded K10 and G-T2a ------------------------------ *)

Section Instance.
Variable I : finIx.
Variable S : system I.
Notation csle := (sle ceqb cjoin (I:=I)).
Notation lfpS := (lfp cbot 6 (FS S)).

Lemma step_mono (G : system I) x y : csle x y -> csle (FS G x) (FS G y).
Proof.
move=> xy i; rewrite /FS /step.
suff gen es a b : cle a b ->
  cle (fold_left (fun acc e => cjoin acc (contrib x e)) es a)
      (fold_left (fun acc e => cjoin acc (contrib y e)) es b).
  by apply: gen; exact: (le_refl ceqP cjoinxx).
elim: es a b => [|e es IH] a b ab //=; apply: IH.
exact: cle_join2 ab (contrib_mono _ _ (xy _)).
Qed.

Definition N_ := length (ix_enum I) * 6.

(* K10a/b unbounded: the Rust Jacobi loop with N_ + 1 = |I| * HEIGHT + 1
   passes returns the least fixpoint, which is below every pre-fixpoint. *)
Theorem k10_jacobi :
  exists x, jacobi ceqb (FS S) (Nat.succ N_) (@sbot _ cbot I) = Some x /\ x =1 lfpS.
Proof. exact: (jacobi_is_lfp ceqP cjoinC cjoinA cjoinxx cjoin0x crank_lt crank_h (@step_mono S)). Qed.

Theorem k10_least y : csle (FS S y) y -> csle lfpS y.
Proof. exact: (lfp_least ceqP cjoinA cjoinxx cjoin0x 6 (@step_mono S)). Qed.

(* K10c unbounded: every fair schedule, repetitions allowed, gives the same
   answer within the same pass budget. *)
Theorem k10_chaotic sched : (forall i, In i sched) ->
  exists x, chaotic ceqb (FS S) sched (Nat.succ N_) (@sbot _ cbot I) = Some x /\ x =1 lfpS.
Proof. exact: (chaotic_is_lfp ceqP cjoinC cjoinA cjoinxx cjoin0x crank_lt crank_h (@step_mono S)). Qed.

(* Non-vacuity of the fairness hypothesis: a schedule that skips coordinates
   returns bot after one quiet pass, which is NOT the lfp once any seed is
   not bot. The Rust loop has the same behaviour (#368); K10c's harness
   assumes fairness too. *)
Lemma unfair_schedule_returns_bot : chaotic ceqb (FS S) nil (Nat.succ N_) (@sbot _ cbot I) = Some (@sbot _ cbot I).
Proof. by []. Qed.
Lemma lfp_above_seed i : cle (seed S i) (lfpS i).
Proof.
rewrite -(lfp_fix ceqP cjoinC cjoinxx cjoin0x crank_lt crank_h (@step_mono S) i) /FS /step.
move: (le_refl ceqP cjoinxx (seed S i)); move: {2 4}(seed S i) => a.
elim: (edges S i) a => [|e es IH] //= a sa; apply: IH.
exact: (le_trans ceqP cjoinA cjoinxx sa (le_joinl ceqP cjoinA cjoinxx _ _)).
Qed.

(* G-T2a one step: C(F_G(X)) <= F_C(C(X)), as diagonals. *)
Definition dc (x : I -> cells) : I -> cells := fun i => diag (collapse (x i)).

Lemma gt2a_one_step x : csle (dc (FS S x)) (FS (collapsed S) (dc x)).
Proof.
move=> i; rewrite /dc /FS /step /=.
suff gen es a b : cle (diag (collapse a)) b ->
  cle (diag (collapse (fold_left (fun acc e => cjoin acc (contrib x e)) es a)))
      (fold_left (fun acc e => cjoin acc (contrib (dc x) e))
             (map (fun e => Edge (callee e) Opaque Both) es) b).
  by apply: gen; exact: (le_refl ceqP cjoinxx).
elim: es a b => [|e es IH] a b ab //=; apply: IH.
have -> : contrib (dc x) (Edge (callee e) Opaque Both) = diag (collapse (x (callee e))).
  by rewrite /contrib /dc /= collapse_diag.
rewrite collapse_morph diag_join; apply: cle_join2 ab _.
by rewrite /le /cjoin /= /contrib contrib_below; apply/ceqP.
Qed.

(* G-T2a at the lfp, unbounded (K11 lfp is Kani-checked only at n = 2,
   <= 1 edge): C(lfp F_G) <= C(lfp F_C), exactly the Rust K11 comparison
   `gv.collapse().leq(tv.collapse())`, for every coordinate. *)
Theorem gt2a_lfp i :
  tjoin (collapse (lfpS i)) (collapse (lfp cbot 6 (FS (collapsed S)) i))
  = collapse (lfp cbot 6 (FS (collapsed S)) i).
Proof.
have H : csle (dc lfpS) (lfp cbot 6 (FS (collapsed S))) :=
  lax_simulation_lfp (alpha := dc) ceqP cjoinA cjoinxx 6 (@step_mono (collapsed S)) (fun _ => erefl) gt2a_one_step.
move/(_ i)/ceqP/(f_equal fst): H; rewrite /dc /=.
move: (lfpS i) (lfp cbot 6 (FS (collapsed S)) i) => g [l1 l2] /= e1.
by rewrite /collapse /= tjoinA e1.
Qed.

End Instance.

(* ---- Certificate checking: a solver trace from Rust, validated ----------- *)

(* The exported Rust Jacobi chain x_0 = bot, x_1, ..., x_k is accepted iff
   each x_{j+1} is Rocq's `step` of x_j and x_k is a fixpoint of it; then x_k
   IS the least fixpoint of the Rocq model (chain_lfp). This is how the
   hand-transposed `step`/`collapsed` are tied to the Rust ones, by
   computation on the Rust kernel's own outputs. *)
Section Certificate.
Variables (I : finIx) (S : system I) (ords : seq I).
Hypothesis ordsP : forall i, In i ords.

Definition step_to (x y : I -> cells) := forallb (fun i => ceqb (step S x i) (y i)) ords.
Fixpoint chain_ok (x : I -> cells) (rest : seq (I -> cells)) :=
  if rest is y :: r then step_to x y && chain_ok y r else step_to x x.

Lemma step_ext x y : x =1 y -> step S x =1 step S y.
Proof.
move=> e i; rewrite /step /contrib.
by elim: (edges S i) (seed S i) => //= e' es IH a; rewrite e IH.
Qed.

(* ssr's `last x (y :: r) = last y r` holds by computation; Stdlib's needs this. *)
Lemma last_cons A (y : A) r x : last (y :: r) x = last r y.
Proof. elim: r y x => [|a r IH] y x //; change (last (a :: r) x = last (a :: r) y); by rewrite !IH. Qed.

Theorem chain_lfp ch : chain_ok (fun _ => cbot) ch ->
  forall i, lfp cbot 6 (FS S) i = last ch (fun _ => cbot) i.
Proof.
have mono := @step_mono I S.
have below k : sle ceqb cjoin (it cbot (FS S) k) (lfp cbot 6 (FS S)).
  apply: (it_below ceqP cjoinA cjoinxx cjoin0x mono) => j.
  rewrite (lfp_fix ceqP cjoinC cjoinxx cjoin0x crank_lt crank_h mono j).
  exact: (le_refl ceqP cjoinxx).
suff gen k x rest : x =1 it cbot (FS S) k -> chain_ok x rest ->
    forall i, lfp cbot 6 (FS S) i = last rest x i.
  by apply: (gen 0).
elim: rest k x => [|y r IH] k x ex.
  move=> /forallb_forall fx; have fk : FS S (it cbot (FS S) k) =1 it cbot (FS S) k.
    by move=> i; rewrite /FS -(step_ext ex) -ex; apply/ceqP/fx.
  move=> i /=; rewrite ex.
  by rewrite (fix_is_lfp ceqP cjoinC cjoinA cjoinxx cjoin0x mono fk (below k)).
move=> /andP[/forallb_forall xy ok] i; rewrite last_cons; move: i; apply: (IH (Nat.succ k)) ok => i.
by rewrite /= /FS -(step_ext ex); apply/esym/ceqP/xy.
Qed.

End Certificate.
