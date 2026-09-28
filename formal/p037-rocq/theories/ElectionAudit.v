(* Trusted base of the election reuse gate: every line must print
   "Closed under the global context". *)
From PlainSpike Require Import Election.
Print Assumptions k10e_jacobi.
Print Assumptions k10e_least.
Print Assumptions k10e_chaotic.
Print Assumptions estep_mono.
Print Assumptions import_mono.
Print Assumptions import_not_join_morphism.
