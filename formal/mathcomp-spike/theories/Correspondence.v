(* The drift seam: the Rocq model of P037.v against the Rust kernel's own
   outputs (RustTables.v, generated from formal/p037-kernel by export/).

   1. Every finite operation is equal to the Rust one on its WHOLE domain:
      each exported row agrees with the Rocq function, and every input of the
      domain has its Rocq row in the export (so no row is missing or stale).
   2. The height constants agree, so the proved pass bound is Rust's.
   3. For 300 seeded random SCCs, Rust's Jacobi chain (produced by the
      kernel's `System::step`) and the chain of `sys.collapsed()` are
      accepted by the proved certificate checker of P037.v: the Rust answers
      ARE the Rocq model's least fixpoints (chain_lfp).
   Regenerate RustTables.v after any kernel change; a divergence fails here. *)

From HB Require Import structures.
From mathcomp Require Import boot.
From P037Spike Require Import Lfp P037 RustTables.

Set Implicit Arguments.
Unset Strict Implicit.
Unset Printing Implicit Defensive.

(* ---- 1. finite operations, extensionally --------------------------------- *)

Definition join_ok :=
  all (fun r => let: (a, b, c) := r in tjoin a b == c) rust_join
  && all (fun a => all (fun b => (a, b, tjoin a b) \in rust_join) tall) tall.
Definition fin_lower_ok :=
  all (fun r => let: (a, f, l) := r in (fin a == f) && (lower a == l)) rust_fin_lower
  && all (fun a => (a, fin a, lower a) \in rust_fin_lower) tall.
Definition collapse_ok :=
  all (fun r => let: (c, t) := r in collapse c == t) rust_collapse
  && all (fun c => (c, collapse c) \in rust_collapse) call.
Definition contribute_read_ok :=
  all (fun r => let: (t, m, c, d) := r in contribute m (read t c) == d) rust_contribute_read
  && all (fun t => all (fun m => all (fun c =>
       (t, m, c, contribute m (read t c)) \in rust_contribute_read) call) mall) xall.
Definition apply_ok :=
  all (fun r => let: (sh, c, sel, l) := r in apply sh c sel == l) rust_apply
  && all (fun sh => all (fun c => all (fun sel =>
       (sh, c, sel, apply sh c sel) \in rust_apply) sall) call) [:: Uncond; Split].

Theorem tables_match_rust :
  [&& join_ok, fin_lower_ok, collapse_ok, contribute_read_ok & apply_ok].
Proof. by vm_compute. Qed.

(* ---- 2. constants --------------------------------------------------------- *)

Theorem constants_match_rust :
  [/\ rust_cells_height = 6, rust_transfer_height = 3
    & rust_max_passes_cells = (#|'I_rust_max_coords| * rust_cells_height).+1].
Proof. by rewrite card_ord. Qed.

(* So for the Rust bound (3 coordinates), N_.+1 of P037.v IS max_passes. *)
Corollary k10_rust_bound (S : system 'I_3) :
  jacobi (FS S) rust_max_passes_cells (sbot cbot 'I_3) = Some (lfp cbot 6 (FS S)).
Proof. by case: constants_match_rust => _ _ ->; exact: k10_jacobi. Qed.

(* ---- 3. solver vectors, via the proved certificate checker --------------- *)

(* Literal ordinals: `inord` goes through the opaque `idP` and would block
   vm_compute. *)
Definition ord3 n : 'I_3 :=
  match n with 0 => @Ordinal 3 0 isT | 1 => @Ordinal 3 1 isT | _ => @Ordinal 3 2 isT end.
Definition ords3 := [:: ord3 0; ord3 1; ord3 2].
Lemma ords3P i : i \in ords3.
Proof.
by case: i => [[|[|[|n]]] lt]; rewrite ?inE -?val_eqE //=.
Qed.

Definition sys_of (seeds : seq cells) (es : seq (seq (nat * transform * mask))) : system 'I_3 :=
  System (fun i : 'I_3 => nth cbot seeds i)
         (fun i : 'I_3 => [seq let: (c, t, m) := e in Edge (ord3 c) t m | e <- nth [::] es i]).
Definition fn (l : seq cells) : 'I_3 -> cells := fun i => nth cbot l i.

Definition vector_ok (v : vector) :=
  let: (seeds, es, jac, col) := v in
  let S := sys_of seeds es in
  (all (fun c => c < 3) [seq let: (c, _, _) := e in c | e <- flatten es])
  && chain_ok S ords3 (fun _ => cbot) (map fn jac)
  && chain_ok (collapsed S) ords3 (fun _ => cbot) (map fn col).

Theorem vectors_match_rust : all vector_ok rust_vectors.
Proof. by vm_compute. Qed.

(* What that buys, stated: for every exported vector, the Rust Jacobi answer
   (last of the chain) is the least fixpoint of the ROCQ model, for the
   system and for its collapse. *)
Corollary rust_answers_are_rocq_lfps seeds es jac col :
  (seeds, es, jac, col) \in rust_vectors ->
  (forall i, lfp cbot 6 (FS (sys_of seeds es)) i = fn (last [::] jac) i)
  /\ (forall i, lfp cbot 6 (FS (collapsed (sys_of seeds es))) i = fn (last [::] col) i).
Proof.
move=> /(allP vectors_match_rust) /andP[/andP[_ okj] okc].
have lastfn l : fn (last [::] l) =1 last (fun _ => cbot) (map fn l).
  by case: l => [|x l] i //=; [rewrite /fn nth_nil | rewrite (last_map fn)].
split=> i; rewrite lastfn; [exact: (chain_lfp ords3P okj) | exact: (chain_lfp ords3P okc)].
Qed.
