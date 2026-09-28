(* The drift seam: the Rocq model of P037.v against the Rust kernel's own
   outputs (RustTables.v, generated from formal/p037-kernel by export/, moved
   mechanically from formal/mathcomp-spike/export/, PR #367).
   PLAIN-ROCQ CONTROL of formal/mathcomp-spike/theories/Correspondence.v.

   1. Every finite operation is equal to the Rust one on its WHOLE domain:
      each exported row agrees with the Rocq function, and every input of the
      domain has its Rocq row in the export (so no row is missing or stale).
   2. The height constants agree, so the proved pass bound is Rust's.
   3. For 300 seeded random SCCs, Rust's Jacobi chain (produced by the
      kernel's `System::step`) and the chain of `sys.collapsed()` are
      accepted by the proved certificate checker of P037.v: the Rust answers
      ARE the Rocq model's least fixpoints (chain_lfp).
   Regenerate RustTables.v after any kernel change; a divergence fails here. *)

From Corelib Require Import ssreflect ssrfun ssrbool.
From Stdlib Require Import List.
From PlainSpike Require Import Lfp P037 RustTables.

Set Implicit Arguments.
Unset Strict Implicit.

(* ---- 1. finite operations, extensionally --------------------------------- *)

(* Row equality and membership: what MathComp's eqType on products gave free. *)
Definition peq A B (ea : A -> A -> bool) (eb : B -> B -> bool) (p q : A * B) :=
  ea p.1 q.1 && eb p.2 q.2.
Definition memb A (eq : A -> A -> bool) (x : A) l := existsb (eq x) l.
Notation teq := transfer_beq.

Definition join_ok :=
  forallb (fun r => let '(a, b, c) := r in teq (tjoin a b) c) rust_join
  && forallb (fun a => forallb (fun b =>
       memb (peq (peq teq teq) teq) (a, b, tjoin a b) rust_join) tall) tall.
Definition fin_lower_ok :=
  forallb (fun r => let '(a, f, l) := r in teq (fin a) f && lowered_beq (lower a) l) rust_fin_lower
  && forallb (fun a => memb (peq (peq teq teq) lowered_beq) (a, fin a, lower a) rust_fin_lower) tall.
Definition collapse_ok :=
  forallb (fun r => let '(c, t) := r in teq (collapse c) t) rust_collapse
  && forallb (fun c => memb (peq ceqb teq) (c, collapse c) rust_collapse) call.
Definition contribute_read_ok :=
  forallb (fun r => let '(t, m, c, d) := r in ceqb (contribute m (read t c)) d) rust_contribute_read
  && forallb (fun t => forallb (fun m => forallb (fun c =>
       memb (peq (peq (peq transform_beq mask_beq) ceqb) ceqb)
            (t, m, c, contribute m (read t c)) rust_contribute_read) call) mall) xall.
Definition apply_ok :=
  forallb (fun r => let '(sh, c, sel, l) := r in lowered_beq (apply sh c sel) l) rust_apply
  && forallb (fun sh => forallb (fun c => forallb (fun sel =>
       memb (peq (peq (peq shape_beq ceqb) selection_beq) lowered_beq)
            (sh, c, sel, apply sh c sel) rust_apply) sall) call) [:: Uncond; Split].

Theorem tables_match_rust :
  [&& join_ok, fin_lower_ok, collapse_ok, contribute_read_ok & apply_ok].
Proof. by vm_compute. Qed.

(* ---- 3 coordinates, as a finite index ------------------------------------ *)

Inductive c3 := C0 | C1 | C2.
Scheme Equality for c3.
Definition ords3 := [:: C0; C1; C2].
Lemma c3P a b : reflect (a = b) (c3_beq a b). Proof. by case: a; case: b; constructor. Qed.
Lemma ords3P' a : In a ords3. Proof. by case: a; simpl; tauto. Qed.
Definition I3 := {| ix := c3; ix_eqb := c3_beq; ix_eqbP := c3P; ix_enum := ords3; ix_enumP := ords3P' |}.
Lemma ords3P (i : I3) : In i ords3. Proof. exact: ords3P'. Qed.

(* ---- 2. constants --------------------------------------------------------- *)

Theorem constants_match_rust :
  [/\ rust_cells_height = 6, rust_transfer_height = 3
    & rust_max_passes_cells = Nat.succ (length (ix_enum I3) * rust_cells_height)].
Proof. by []. Qed.

(* So for the Rust bound (3 coordinates), N_ + 1 of P037.v IS max_passes. *)
Corollary k10_rust_bound (Sy : system I3) :
  exists x, jacobi ceqb (FS Sy) rust_max_passes_cells (@sbot _ cbot I3) = Some x
            /\ x =1 lfp cbot 6 (FS Sy).
Proof. exact: k10_jacobi. Qed.

(* ---- 3. solver vectors, via the proved certificate checker --------------- *)

Definition c2n i := match i with C0 => 0 | C1 => 1 | C2 => 2 end.
Definition ord3 n := match n with 0 => C0 | 1 => C1 | _ => C2 end.

Definition sys_of (seeds : seq cells) (es : seq (seq (nat * transform * mask))) : system I3 :=
  System (fun i : I3 => nth (c2n i) seeds cbot)
         (fun i : I3 => map (fun e => let '(c, t, m) := e in Edge (ord3 c) t m) (nth (c2n i) es nil)).
Definition fn (l : seq cells) : I3 -> cells := fun i => nth (c2n i) l cbot.

Definition vector_ok (v : vector) :=
  let '(seeds, es, jac, col) := v in
  let Sy := sys_of seeds es in
  forallb (fun e => let '(c, _, _) := e in Nat.ltb c 3) (concat es)
  && chain_ok Sy ords3 (fun _ => cbot) (map fn jac)
  && chain_ok (collapsed Sy) ords3 (fun _ => cbot) (map fn col).

Theorem vectors_match_rust : forallb vector_ok rust_vectors.
Proof. by vm_compute. Qed.

(* What that buys, stated: for every exported vector, the Rust Jacobi answer
   (last of the chain) is the least fixpoint of the ROCQ model, for the
   system and for its collapse. *)
Corollary rust_answers_are_rocq_lfps seeds es jac col :
  In (seeds, es, jac, col) rust_vectors ->
  (forall i, lfp cbot 6 (FS (sys_of seeds es)) i = fn (last jac nil) i)
  /\ (forall i, lfp cbot 6 (FS (collapsed (sys_of seeds es))) i = fn (last col nil) i).
Proof.
move=> /(proj1 (forallb_forall _ _) vectors_match_rust) /andP[/andP[_ okj] okc].
have lastfn l i : fn (last l nil) i = last (map fn l) (fun _ => cbot) i.
  elim: l => [|x l IH]; first by case: i.
  by case: l IH.
split=> i; rewrite lastfn; [exact: (chain_lfp ords3P okj) | exact: (chain_lfp ords3P okc)].
Qed.
