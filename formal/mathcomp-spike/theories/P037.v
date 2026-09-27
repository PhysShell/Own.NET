(* The P-037 kernel of formal/p037-kernel/src/lib.rs, transposed, and the
   generic theorems of Lfp.v instantiated on it.

   Every finite operation below is pinned EXTENSIONALLY to the Rust kernel by
   Correspondence.v (full truth tables exported from the crate itself). The
   structural parts (`step`, `collapsed`, the two solver loops) are hand-
   transposed and cross-checked on exported solver vectors. *)

From HB Require Import structures.
From mathcomp Require Import boot.
From P037Spike Require Import Lfp.

Set Implicit Arguments.
Unset Strict Implicit.
Unset Printing Implicit Defensive.

(* ---- INF-L1/L2: the base transfer lattice ------------------------------- *)

Inductive transfer := Bot | No | Must | May | Unknown.

(* Finite type by a bijection with 'I_5: equality, choice, countability and
   enumeration all come from MathComp. Literal ordinals, not `inord`: `inord`
   goes through `insub`/`idP`, which is opaque, and `==` would not compute. *)
Definition t2o t : 'I_5 :=
  match t with
  | Bot => @Ordinal 5 0 isT | No => @Ordinal 5 1 isT | Must => @Ordinal 5 2 isT
  | May => @Ordinal 5 3 isT | Unknown => @Ordinal 5 4 isT
  end.
Definition o2t (o : 'I_5) :=
  match nat_of_ord o with 0 => Bot | 1 => No | 2 => Must | 3 => May | _ => Unknown end.
Lemma t2oK : cancel t2o o2t. Proof. by case. Qed.
HB.instance Definition _ := Finite.copy transfer (can_type t2oK).

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

(* Candidate B: the product inherits the laws cellwise, from the base laws. *)
Lemma cjoinC c d : cjoin c d = cjoin d c. Proof. by rewrite /cjoin tjoinC (tjoinC c.2). Qed.
Lemma cjoinA c d e : cjoin c (cjoin d e) = cjoin (cjoin c d) e.
Proof. by rewrite /cjoin /= !tjoinA. Qed.
Lemma cjoinxx c : cjoin c c = c. Proof. by case: c => a b; rewrite /cjoin !tjoinxx. Qed.
Lemma cjoin0x c : cjoin cbot c = c. Proof. by case: c. Qed.

Notation cle := (le cjoin).

(* Explicit enumerations. MathComp's [forall x, P] over these finTypes does
   NOT reduce under vm_compute (the finType enum/card are locked), so finite
   facts are decided with `all` over explicit lists, plain-Rocq style. *)
Definition tall := [:: Bot; No; Must; May; Unknown].
Definition call : seq cells := [seq (a, b) | a <- tall, b <- tall].
Lemma tallP t : t \in tall. Proof. by case: t. Qed.
Lemma callP (c : cells) : c \in call.
Proof. by case: c => a b; apply/allpairsP; exists (a, b); rewrite !tallP. Qed.

(* The rank is strict and bounded by HEIGHT = 6: decided over all 625 pairs. *)
Definition crank_b :=
  all (fun c => all (fun d => cle c d ==> (c != d) ==> (crank c < crank d)) call) call
  && all (fun c => crank c <= 6) call.
Lemma crank_ok : crank_b. Proof. by vm_compute. Qed.

Lemma crank_lt c d : cle c d -> c != d -> crank c < crank d.
Proof.
case/andP: crank_ok => /allP/(_ c (callP c))/allP/(_ d (callP d))/implyP H _.
by move/H/implyP.
Qed.
Lemma crank_h c : crank c <= 6.
Proof. by case/andP: crank_ok => _ /allP/(_ c (callP c)). Qed.

(* ---- G-S5 / G-F2 / G-S4: edge transforms and branch masks --------------- *)

Inductive transform := ConstPos | ConstNeg | Id | Neg | Opaque.
Inductive mask := Both | PosOnly | NegOnly.

Definition read t (c : cells) : cells :=
  match t with
  | ConstPos => diag c.1 | ConstNeg => diag c.2 | Id => c
  | Neg => (c.2, c.1) | Opaque => diag (collapse c)
  end.
Definition contribute m (r : cells) : cells :=
  match m with Both => r | PosOnly => (r.1, Bot) | NegOnly => (Bot, r.2) end.

(* ---- G-F1: one SCC of ANY size, ANY number of edges per coordinate ------ *)

Record edge (I : Type) := Edge { callee : I; xf : transform; msk : mask }.
Record system (I : finType) := System { seed : I -> cells; edges : I -> seq (edge I) }.

Section Sys.
Variable I : finType.
Implicit Types (S : system I).

(* `System::step`: the seed joined, left to right, with every masked,
   transformed edge read — the Rust loop's exact fold order. *)
(* `step` takes a plain function so that it also EXECUTES under vm_compute
   (MathComp's {ffun} does not: its enum/card are locked); FS wraps it. *)
Definition contrib (x : I -> cells) (e : edge I) := contribute (msk e) (read (xf e) (x (callee e))).
Definition step S (x : I -> cells) i :=
  foldl (fun acc e => cjoin acc (contrib x e)) (seed S i) (edges S i).
Definition FS S (x : {ffun I -> cells}) : {ffun I -> cells} := [ffun i => step S x i].

(* `System::collapsed` (F_0 of G-T2 §7.2): seeds collapsed onto the diagonal,
   every edge read opaquely with no mask. *)
Definition collapsed S :=
  System (fun i => diag (collapse (seed S i)))
         (fun i => map (fun e => Edge (callee e) Opaque Both) (edges S i)).

End Sys.

(* ---- Finite facts, decided by computation over MathComp finTypes ------- *)

Definition x2o t : 'I_5 :=
  match t with
  | ConstPos => @Ordinal 5 0 isT | ConstNeg => @Ordinal 5 1 isT | Id => @Ordinal 5 2 isT
  | Neg => @Ordinal 5 3 isT | Opaque => @Ordinal 5 4 isT
  end.
Definition o2x (o : 'I_5) :=
  match nat_of_ord o with 0 => ConstPos | 1 => ConstNeg | 2 => Id | 3 => Neg | _ => Opaque end.
Lemma x2oK : cancel x2o o2x. Proof. by case. Qed.
HB.instance Definition _ := Finite.copy transform (can_type x2oK).
Definition m2o m : 'I_3 :=
  match m with Both => @Ordinal 3 0 isT | PosOnly => @Ordinal 3 1 isT | NegOnly => @Ordinal 3 2 isT end.
Definition o2m (o : 'I_3) := match nat_of_ord o with 0 => Both | 1 => PosOnly | _ => NegOnly end.
Lemma m2oK : cancel m2o o2m. Proof. by case. Qed.
HB.instance Definition _ := Finite.copy mask (can_type m2oK).

Definition xall := [:: ConstPos; ConstNeg; Id; Neg; Opaque].
Definition mall := [:: Both; PosOnly; NegOnly].

(* K3 (every read and mask monotone) and the §7.2 lemma (a masked read sits
   below the collapse), as booleans over the whole finite domain. *)
Definition contrib_mono_b :=
  all (fun m => all (fun t => all (fun c => all (fun d =>
     cle c d ==> cle (contribute m (read t c)) (contribute m (read t d))) call) call) xall) mall.
Definition contrib_below_b :=
  all (fun m => all (fun t => all (fun c =>
     tjoin (collapse (contribute m (read t c))) (collapse c) == collapse c) call) xall) mall.
Definition collapse_morph_b :=
  all (fun c => all (fun d => collapse (cjoin c d) == tjoin (collapse c) (collapse d)) call) call.

Lemma contrib_mono_ok : contrib_mono_b. Proof. by vm_compute. Qed.
Lemma contrib_below_ok : contrib_below_b. Proof. by vm_compute. Qed.
Lemma collapse_morph_ok : collapse_morph_b. Proof. by vm_compute. Qed.

Lemma xallP t : t \in xall. Proof. by case: t. Qed.
Lemma mallP m : m \in mall. Proof. by case: m. Qed.

Lemma contrib_mono m t c d : cle c d -> cle (contribute m (read t c)) (contribute m (read t d)).
Proof.
move: contrib_mono_ok => /allP/(_ m (mallP m))/allP/(_ t (xallP t)).
by move=> /allP/(_ c (callP c))/allP/(_ d (callP d))/implyP.
Qed.
Lemma contrib_below m t c : tjoin (collapse (contribute m (read t c))) (collapse c) == collapse c.
Proof. by move: contrib_below_ok => /allP/(_ m (mallP m))/allP/(_ t (xallP t))/allP/(_ c (callP c)). Qed.
Lemma collapse_morph c d : collapse (cjoin c d) = tjoin (collapse c) (collapse d).
Proof. by apply/eqP; move: collapse_morph_ok => /allP/(_ c (callP c))/allP/(_ d (callP d)). Qed.

Lemma collapse_diag t : collapse (diag t) = t. Proof. exact: tjoinxx. Qed.
Lemma diag_join s t : diag (tjoin s t) = cjoin (diag s) (diag t). Proof. by []. Qed.

Lemma cle_join2 a a' b b' : cle a a' -> cle b b' -> cle (cjoin a b) (cjoin a' b').
Proof. exact: (@le_join2 _ cjoin cjoinC cjoinA cjoinxx). Qed.

(* ---- G-A1 / G-A2: application at the call site ------------------------- *)

Inductive selection := SelPos | SelNeg | Unselected.
Inductive lowered := Consume | Borrow | Plain.
Inductive shape := Uncond | Split.  (* the split's guard index is irrelevant here *)

Definition s2n s := match s with SelPos => 0 | SelNeg => 1 | Unselected => 2 end.
Definition n2s n := match n with 0 => SelPos | 1 => SelNeg | _ => Unselected end.
Lemma s2nK : cancel s2n n2s. Proof. by case. Qed.
HB.instance Definition _ := Equality.copy selection (can_type s2nK).
Definition l2n l := match l with Consume => 0 | Borrow => 1 | Plain => 2 end.
Definition n2l n := match n with 0 => Consume | 1 => Borrow | _ => Plain end.
Lemma l2nK : cancel l2n n2l. Proof. by case. Qed.
HB.instance Definition _ := Equality.copy lowered (can_type l2nK).
Definition h2b h := if h is Split then true else false.
Definition b2h b := if b then Split else Uncond.
Lemma h2bK : cancel h2b b2h. Proof. by case. Qed.
HB.instance Definition _ := Equality.copy shape (can_type h2bK).

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
Definition k6_b :=
  all (fun sh => all (fun c => all (fun sel =>
    ((sh == Split) || (c.1 == c.2)) ==>
    ((apply sh c sel == Consume) ==
     ((sh == Split) && match sel with
                      | SelPos => (cfin c).1 == Must
                      | SelNeg => (cfin c).2 == Must
                      | Unselected => false end)
     || ((cfin c).1 == Must) && ((cfin c).2 == Must))) sall) call) [:: Uncond; Split].
Lemma k6_ok : k6_b. Proof. by vm_compute. Qed.

(* ---- The instance: unbounded K10 and G-T2a ------------------------------ *)

Section Instance.
Variable I : finType.
Variable S : system I.

Lemma step_mono (G : system I) x y : sle cjoin x y -> sle cjoin (FS G x) (FS G y).
Proof.
move=> /sleP xy; apply/sleP => i; rewrite !ffunE /step.
suff gen es a b : cle a b ->
  cle (foldl (fun acc e => cjoin acc (contrib x e)) a es)
      (foldl (fun acc e => cjoin acc (contrib y e)) b es).
  by apply: gen; exact: (@le_refl _ cjoin cjoinxx).
elim: es a b => [|e es IH] a b ab //=; apply: IH.
exact: cle_join2 ab (contrib_mono _ _ (xy _)).
Qed.

Definition N_ := #|I| * 6.

(* K10a/b unbounded: the Rust Jacobi loop with N_ + 1 = #|I| * HEIGHT + 1
   passes returns the least fixpoint, which is below every pre-fixpoint. *)
Theorem k10_jacobi :
  jacobi (FS S) N_.+1 (sbot cbot I) = Some (lfp cbot 6 (FS S)).
Proof. exact: (jacobi_is_lfp cjoinC cjoinA cjoinxx cjoin0x crank_lt crank_h (@step_mono S)). Qed.

Theorem k10_least y : sle cjoin (FS S y) y -> sle cjoin (lfp cbot 6 (FS S)) y.
Proof. exact: (@lfp_least _ cjoin cbot cjoinA cjoinxx cjoin0x 6 _ _ (@step_mono S)). Qed.

(* K10c unbounded: every fair schedule, repetitions allowed, gives the same
   answer within the same pass budget. *)
Theorem k10_chaotic sched : (forall i, i \in sched) ->
  chaotic (FS S) sched N_.+1 (sbot cbot I) = Some (lfp cbot 6 (FS S)).
Proof. exact: (@chaotic_is_lfp _ cjoin cbot cjoinC cjoinA cjoinxx cjoin0x _ _ crank_lt crank_h _ _ (@step_mono S)). Qed.

(* Non-vacuity of the fairness hypothesis: a schedule that skips coordinates
   returns bot after one quiet pass, which is NOT the lfp once any seed is
   not bot. The Rust loop has the same behaviour (its `solve_with` callers
   must pass a covering schedule); K10c's harness assumes it too. *)
Lemma unfair_schedule_returns_bot : chaotic (FS S) [::] N_.+1 (sbot cbot I) = Some (sbot cbot I).
Proof. by []. Qed.
Lemma lfp_above_seed i : cle (seed S i) (lfp cbot 6 (FS S) i).
Proof.
rewrite -(@lfp_fix _ cjoin cbot cjoin0x crank 6 crank_lt crank_h _ _ (@step_mono S)) ffunE /step.
move: (@le_refl _ _ cjoinxx (seed S i)); move: {2 4}(seed S i) => a.
elim: (edges S i) a => [|e es IH] //= a sa; apply: IH.
exact: le_trans cjoinA cjoinxx _ _ _ sa (le_joinl cjoinA cjoinxx _ _).
Qed.

(* G-T2a one step: C(F_G(X)) <= F_C(C(X)), as diagonals. *)
Definition dc x : {ffun I -> cells} := [ffun i => diag (collapse (x i))].

Lemma gt2a_one_step x : sle cjoin (dc (FS S x)) (FS (collapsed S) (dc x)).
Proof.
apply/sleP => i; rewrite !ffunE /step /=.
suff gen es a b : cle (diag (collapse a)) b ->
  cle (diag (collapse (foldl (fun acc e => cjoin acc (contrib x e)) a es)))
      (foldl (fun acc e => cjoin acc (contrib (dc x) e)) b
             (map (fun e => Edge (callee e) Opaque Both) es)).
  by apply: gen; exact: (@le_refl _ cjoin cjoinxx).
elim: es a b => [|e es IH] a b ab //=; apply: IH.
have -> : contrib (dc x) (Edge (callee e) Opaque Both) = diag (collapse (x (callee e))).
  by rewrite /contrib /= ffunE /= collapse_diag.
rewrite collapse_morph diag_join; apply: cle_join2 ab _.
by rewrite /le /cjoin /= /contrib (eqP (contrib_below _ _ _)).
Qed.

(* G-T2a at the lfp, unbounded (K11 lfp is Kani-checked only at n = 2,
   <= 1 edge): C(lfp F_G) <= C(lfp F_C), exactly the Rust K11 comparison
   `gv.collapse().leq(tv.collapse())`, for every coordinate. *)
Theorem gt2a_lfp i :
  tjoin (collapse (lfp cbot 6 (FS S) i)) (collapse (lfp cbot 6 (FS (collapsed S)) i))
  == collapse (lfp cbot 6 (FS (collapsed S)) i).
Proof.
have dc_bot : dc (sbot cbot I) = sbot cbot I by apply/ffunP => j; rewrite !ffunE.
have H : sle cjoin (dc (lfp cbot 6 (FS S))) (lfp cbot 6 (FS (collapsed S))) :=
  @lax_simulation_lfp _ cjoin cbot cjoinA cjoinxx 6 _ _ _ (@step_mono (collapsed S)) _
                      dc_bot gt2a_one_step.
move/sleP/(_ i): H; rewrite ffunE => /eqP/(congr1 fst) /=.
move: (lfp cbot 6 (FS S) i) (lfp cbot 6 (FS (collapsed S)) i) => g [l1 l2] /= e1.
by rewrite [collapse (l1, l2)]/collapse /= tjoinA e1.
Qed.

End Instance.

(* ---- Certificate checking: a solver trace from Rust, validated ----------- *)

(* The exported Rust Jacobi chain x_0 = bot, x_1, ..., x_k is accepted iff
   each x_{j+1} is Rocq's `step` of x_j and x_k is a fixpoint of it; then x_k
   IS the least fixpoint of the Rocq model (chain_lfp). This is how the
   hand-transposed `step`/`collapsed` are tied to the Rust ones, by
   computation on the Rust kernel's own outputs. *)
Section Certificate.
Variables (I : finType) (S : system I) (ords : seq I).
Hypothesis ordsP : forall i, i \in ords.

Definition step_to (x y : I -> cells) := all (fun i => step S x i == y i) ords.
Fixpoint chain_ok (x : I -> cells) (rest : seq (I -> cells)) :=
  if rest is y :: r then step_to x y && chain_ok y r else step_to x x.

Lemma step_ext x y : x =1 y -> step S x =1 step S y.
Proof.
move=> e i; rewrite /step /contrib.
by elim: (edges S i) (seed S i) => //= e' es IH a; rewrite e IH.
Qed.

Theorem chain_lfp ch : chain_ok (fun _ => cbot) ch ->
  forall i, lfp cbot 6 (FS S) i = last (fun _ => cbot) ch i.
Proof.
have below k : sle cjoin (it cbot (FS S) k) (lfp cbot 6 (FS S)).
  apply: (@it_below _ cjoin cbot cjoinA cjoinxx cjoin0x _ _ (@step_mono _ S)).
  rewrite (@lfp_fix _ cjoin cbot cjoin0x crank 6 crank_lt crank_h _ _ (@step_mono _ S)).
  by apply/sleP => j; exact: (@le_refl _ _ cjoinxx).
suff gen k x rest : x =1 it cbot (FS S) k -> chain_ok x rest ->
    forall i, lfp cbot 6 (FS S) i = last x rest i.
  by apply: (gen 0) => i; rewrite /it /= ffunE.
elim: rest k x => [|y r IH] k x ex /=.
  move=> /allP fx; have fk : FS S (it cbot (FS S) k) = it cbot (FS S) k.
    apply/ffunP => i; rewrite ffunE -(step_ext ex) -ex; exact/eqP/fx.
  have := @fix_is_lfp _ cjoin cbot cjoinC cjoinA cjoinxx cjoin0x 6 _ _ (@step_mono _ S) _ fk (below k).
  by move=> <- i; rewrite ex.
case/andP => /allP xy ok; apply: (IH k.+1) ok => i.
by rewrite /it iterS ffunE -/(it _ _ _) -(step_ext ex); apply/esym/eqP/xy.
Qed.

End Certificate.
