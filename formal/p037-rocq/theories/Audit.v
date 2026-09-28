(* Trusted base of the headline results: prints the axioms each depends on.
   Expected output for every line: "Closed under the global context". *)
From PlainSpike Require Import Lfp P037 Correspondence.

Print Assumptions jacobi_is_lfp.
Print Assumptions chaotic_is_lfp.
Print Assumptions lax_simulation_lfp.
Print Assumptions k10_jacobi.
Print Assumptions k10_chaotic.
Print Assumptions gt2a_lfp.
Print Assumptions chain_lfp.
Print Assumptions tables_match_rust.
Print Assumptions vectors_match_rust.
Print Assumptions rust_answers_are_rocq_lfps.
