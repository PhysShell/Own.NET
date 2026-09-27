(* Election reuse gate for #369: the G-S1 election pre-solver (K10e) as an
   INSTANCE of the unchanged generic solver theory Lfp.v.

   Rocq side: an unbounded theorem about the transcribed Election semantics
   (formal/p037-kernel/src/lib.rs `Election`, `import`, `ElectionSystem::step`)
   over ANY guard type with decidable equality. The actual Rust code is still
   checked by Kani (bounded); no Rust<->Rocq refinement is claimed here. *)

From Corelib Require Import ssreflect ssrfun ssrbool.
From Stdlib Require Import List Lia.
From PlainSpike Require Import Lfp.

Set Implicit Arguments.
Unset Strict Implicit.

Section Election.
Variables (G : Type) (geqb : G -> G -> bool).
Hypothesis geqP : forall g h, reflect (g = h) (geqb g h).

Lemma geqxx g : geqb g g. Proof. exact/geqP. Qed.

(* ---- the flat election lattice (G-S1) ----------------------------------- *)

Inductive election := ENone | One of G | Conflict.

Definition ejoin a b :=
  match a, b with
  | ENone, x | x, ENone => x
  | Conflict, _ | _, Conflict => Conflict
  | One g, One h => if geqb g h then One g else Conflict
  end.
Definition eeqb a b :=
  match a, b with
  | ENone, ENone | Conflict, Conflict => true
  | One g, One h => geqb g h
  | _, _ => false
  end.
Definition erank a := match a with ENone => 0 | One _ => 1 | Conflict => 2 end.

Lemma eeqP a b : reflect (a = b) (eeqb a b).
Proof.
case: a b => [|g|] [|h|] /=; try by constructor.
by apply: (iffP (geqP g h)) => [-> | [->]].
Qed.

Lemma ejoinC a b : ejoin a b = ejoin b a.
Proof.
case: a b => [|g|] [|h|] //=; case: (geqP g h) => [-> | ne]; first by rewrite geqxx.
by case: geqP => // /esym /ne.
Qed.
Lemma ejoinA a b c : ejoin a (ejoin b c) = ejoin (ejoin a b) c.
Proof.
case: a b c => [|a|] [|b|] [|c|] //=; try by case: ifP.
have F g h : g <> h -> geqb g h = false by case: geqP.
case: (geqP a b) => [<- | nab]; last by case: ifP => //= _; rewrite (F _ _ nab).
by case: (geqP a c) => [<- | nac]; rewrite /= ?geqxx /= ?geqxx // (F _ _ nac).
Qed.
Lemma ejoinxx a : ejoin a a = a. Proof. by case: a => //= g; rewrite geqxx. Qed.
Lemma ejoin0x a : ejoin ENone a = a. Proof. by []. Qed.

Notation ele := (le eeqb ejoin).

(* HEIGHT = 2, strict. *)
Lemma erank_lt a b : ele a b -> ~~ eeqb a b -> erank a < erank b.
Proof.
rewrite /le; case: a b => [|g|] [|h|] //=; try by intros; lia.
by case: (geqP g h) => [<- | _]; rewrite ?geqxx.
Qed.
Lemma erank_h a : erank a <= 2. Proof. case: a => /= *; lia. Qed.

(* ---- the stage-2 import (G-S1) ------------------------------------------ *)

(* How a call binds the callee's guard parameter: (callee guard, caller guard). *)
Inductive binding := BId of G & G | BNeg of G & G | BConst | BOpaque.

Definition import e b :=
  match e, b with
  | One h, (BId c g | BNeg c g) => if geqb h c then One g else ENone
  | One _, _ => ENone
  | x, _ => x
  end.

(* All the solver needs: import is monotone (K4). *)
Lemma import_mono a b bd : ele a b -> ele (import a bd) (import b bd).
Proof.
have eeqxx z : eeqb z z by case: z => //= g; exact: geqxx.
have top z : eeqb (ejoin z Conflict) Conflict by case: z.
rewrite /le; case: a b => [|g|] [|h|] //= H; rewrite ?eeqxx ?top //.
by move: H; case: (geqP g h) => [<- _ | //]; rewrite ejoinxx eeqxx.
Qed.

(* Pins (K4 / F3): exactly the bound guard is imported, and import is NOT a
   join morphism, so nothing may distribute it over joins. *)
Lemma import_bound h g : import (One h) (BId h g) = One g /\ import (One h) (BNeg h g) = One g.
Proof. by rewrite /= ?geqxx. Qed.
Lemma import_unbound h c g : h <> c -> import (One h) (BId c g) = ENone /\ import (One h) (BNeg c g) = ENone.
Proof. by rewrite /=; case: geqP. Qed.
Lemma import_not_join_morphism h h' g : h <> h' ->
  import (ejoin (One h) (One h')) (BId h g) = Conflict
  /\ ejoin (import (One h) (BId h g)) (import (One h') (BId h g)) = One g.
Proof.
move=> ne /=; case: (geqP h h') => // _; rewrite geqxx.
by case: (geqP h' h) => // e; case: ne.
Qed.

(* ---- the election system: ANY size, ANY number of edges ----------------- *)

Record esys (I : finIx) := ESys { eseed : I -> election; eedges : I -> list (I * binding) }.

Section Instance.
Variables (I : finIx) (S : esys I).

(* `ElectionSystem::step`: the seed joined, left to right, with every import. *)
Definition estep (x : I -> election) i :=
  fold_left (fun acc e => ejoin acc (import (x e.1) e.2)) (eedges S i) (eseed S i).
Definition EF (x : I -> election) : I -> election := fun i => estep x i.

Lemma estep_mono x y : sle eeqb ejoin x y -> sle eeqb ejoin (EF x) (EF y).
Proof.
move=> xy i; rewrite /EF /estep.
suff gen es a b : ele a b -> ele (fold_left (fun acc e => ejoin acc (import (x e.1) e.2)) es a)
                                 (fold_left (fun acc e => ejoin acc (import (y e.1) e.2)) es b).
  by apply: gen; exact: (le_refl eeqP ejoinxx).
elim: es a b => [|e es IH] a b ab //=; apply: IH.
exact: (le_join2 eeqP ejoinC ejoinA ejoinxx ab (import_mono _ (xy _))).
Qed.

(* K10e, unbounded: Kani checks these at n = 3 / 2 edges (Jacobi) and
   n = 2 / 1 edge (chaotic). Pass bound: |I| * HEIGHT + 1 with HEIGHT = 2. *)
Theorem k10e_jacobi :
  exists x, jacobi eeqb EF (Nat.succ (length (ix_enum I) * 2)) (@sbot _ ENone I) = Some x
            /\ x =1 lfp ENone 2 EF.
Proof. exact: (jacobi_is_lfp eeqP ejoinC ejoinA ejoinxx ejoin0x erank_lt erank_h estep_mono). Qed.

Theorem k10e_least y : sle eeqb ejoin (EF y) y -> sle eeqb ejoin (lfp ENone 2 EF) y.
Proof. exact: (lfp_least eeqP ejoinA ejoinxx ejoin0x 2 estep_mono). Qed.

Theorem k10e_chaotic sched : (forall i, In i sched) ->
  exists x, chaotic eeqb EF sched (Nat.succ (length (ix_enum I) * 2)) (@sbot _ ENone I) = Some x
            /\ x =1 lfp ENone 2 EF.
Proof. exact: (chaotic_is_lfp eeqP ejoinC ejoinA ejoinxx ejoin0x erank_lt erank_h estep_mono). Qed.

(* Same counterexample class as the transfer solver: an unfair schedule. *)
Lemma k10e_unfair_returns_bot :
  chaotic eeqb EF nil (Nat.succ (length (ix_enum I) * 2)) (@sbot _ ENone I) = Some (@sbot _ ENone I).
Proof. by []. Qed.

End Instance.
End Election.
