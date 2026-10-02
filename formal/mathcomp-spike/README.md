# formal/mathcomp-spike — Rocq + MathComp applicability spike (research only)

This is a kill-first spike. It asks whether Rocq and MathComp give the P-037
kernel (`formal/p037-kernel`) machine-checked guarantees that go beyond its
existing `cargo test` + Kani harnesses. The question, the protocol and the
verdict are in
[`docs/notes/mathcomp-ownnet-spike.md`](../../docs/notes/mathcomp-ownnet-spike.md).

What this directory is **not**: part of the analyzer, part of `rust/`, part of
`formal/p037-kernel`, or part of any CI gate. It changes no verdict.

## Layout

```text
theories/Lfp.v             generic solver theory for ANY finite coordinate set and
                           ANY rank-bounded join-semilattice: Jacobi reaches the least
                           (pre-)fixpoint within n·h+1 passes (the Rust loop, literally);
                           every fair chaotic schedule returns the same; a one-step lax
                           simulation lifts to the lfps
theories/P037.v            the kernel's Transfer/Cells/read/contribute/step/collapsed/
                           apply transposed; K10 (both solvers) and G-T2a at the lfp,
                           unbounded; K6 (as the unsafe-application control's carrier);
                           the fairness non-vacuity lemma; the certificate checker
                           `chain_lfp`
theories/RustTables.v      GENERATED from the Rust kernel by export/ (do not edit)
theories/Correspondence.v  the drift seam: finite ops equal to Rust's on the whole
                           domain; constants; 300 Rust solver traces accepted by the
                           proved checker, i.e. Rust's answers ARE the model's lfps
theories/OrderProbe.v      what MathComp's order hierarchy would add (probe)
theories/Audit.v           Print Assumptions for the headline theorems (all closed)
export/                    Rust exporter: links formal/p037-kernel by path, prints
                           RustTables.v
mutants/run_mutants.py     negative controls: 7 proof-model mutants plus 4 kernel mutants,
                           and every one must be rejected
check.sh                   regenerate the tables, then check everything (~10 s)
```

## Toolchain (pinned)

Rocq 9.2.0 with MathComp 2.6.0. Only `rocq-mathcomp-boot` is needed, plus
`rocq-mathcomp-order` for `OrderProbe.v`. Hierarchy Builder 1.10.3 and
rocq-elpi 3.5.1 are pulled in as dependencies. The build uses OCaml 4.14.2.

```text
opam switch create rocq-spike ocaml-base-compiler.4.14.2
eval $(opam env --switch=rocq-spike)
opam repo add rocq-released https://rocq-prover.org/opam/released
opam install rocq-core.9.2.0 rocq-mathcomp-boot.2.6.0 rocq-mathcomp-order.2.6.0
./check.sh
python3 mutants/run_mutants.py      # expects: every mutant KILLED, exit 0
```

On a normal machine that is the entire recipe; it takes about 10 minutes on 4 cores
and about 1.9 GB of disk. The cloud sandbox this was built in blocks GitHub
archive tarballs, so there MathComp was pinned from a git clone of tag
`mathcomp-2.6.0` (`7cde45afa55ead3410e17081d9ab4bdd53def3e7`) with
`opam pin add -k path`.
