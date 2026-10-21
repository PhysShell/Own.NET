# P-014 PROD0 (coverage only) — pre-registration

Written 2026-10-21 12:40 +05, before any gate run and before any production change. Base: `main` `22b29d5b`
(merge of #422). Owner decision: `GO-P014-PROD0-COVERAGE-ONLY`. PROD1 (diagnostic semantics) stays forbidden.

**Budget.** 0.5 agent-day to the next kill-gate, counted from 12:35. STOP at 16:35, not extended. When the budget
runs out, I commit what exists and the verdict is `INCONCLUSIVE-P014-PROD0`.

## 1. What will be built (only if G0 and G1 pass)

**Flag.** An opt-in extractor flag `--binding-coverage <file>`, for `.csproj` inputs. It writes the deterministic
coverage sidecar of the Tiny PoC (#422) into `<file>`:
- one `CSharpCompilation` **per project**, from the existing `obj/project.assets.json`, local targeting packs and
  the global packages folder, with project references as `CompilationReference`s;
- binding-site counts, unit status, reasons, reference manifest and conflicts;
- the foreign-binding guard.

**The mechanism.** It is the #422 instrument's code, moved into the extractor as one new file (types public so
that the evidence harness can call the same code). Behaviour changes allowed:
- **Fail closed.** `unit_status = COMPLETE` requires all of the following: reference status `COMPLETE`, **and** no
  source-set reason, **and** no unsupported item. Every other case is `UNSUPPORTED`, `REFERENCE_MISSING`
  (including `CONFLICT_UNRESOLVED`) or `SOURCE_SET_INCOMPLETE`.
- **No TPA substitution.** The process TPA is never used as a reference in this mode.
- **Unsupported inputs.** A directory, a `.sln` or a `.cs` input gets a sidecar with a single `UNSUPPORTED` record
  and no measurement.
- **Separate from facts.** The sidecar is computed **after** the facts document is written, from fresh
  compilations, and it never feeds the existing analysis.

**Unchanged:**
- the default behaviour, every existing flag, directory mode;
- OwnIR, OWN001/OWN014/OWN050;
- SARIF and exit codes;
- the facts document: byte-identical with and without the flag;
- the core, the Rust engine, goldens.

A sidecar write failure is reported on stderr and does **not** change the exit code.

## 2. Gates, in order (fixed now)

### G0 — package-vs-package conflict against the SDK oracle (first, before any integration)

**Fixture.** My own synthetic project, `net10.0-windows` with `UseWPF`, referencing `unchihugo.WPF-UI` 4.4.2 and
`WPF-UI.Tray` 4.3.0. These are the packages that produce P5's `Wpf.Ui.dll` conflict: `unchihugo.WPF-UI` 4.4.2,
AssemblyVersion 4.4.1.0, against the transitive `WPF-UI` 4.3.0, AssemblyVersion 4.3.0.0.
- It is restored offline, with the global packages folder as the only source.
- The oracle is `dotnet msbuild -t:FindReferenceAssembliesForReferences -getItem:ReferencePathWithRefAssemblies`.

**PASS.** The #422 instrument's manifest equals the oracle's, compared by path and assembly version, including
which `Wpf.Ui.dll` is chosen.

**Outcomes:**
- **Mismatch.** The resolver is **not** tuned to fit. The supported set is narrowed instead: any package-vs-package
  conflict on the same file name becomes `CONFLICT_UNRESOLVED`, so the unit is not `COMPLETE`. That narrowing is
  then what gets integrated.
- **The fixture cannot restore offline.** G0 is `INCONCLUSIVE`, and the same narrowing applies.

### G1 — the sidecar does not call P4/P5 fully checked

Run on P4 and P5 with the #422 instrument data (`data/real/P*.exact.sidecar.json`).

**PASS.** Every unit has `unit_status != COMPLETE`. Today's output has every unit at `SOURCE_SET_INCOMPLETE` and
reference status `COMPLETE`.

**KILL if** any unit is `COMPLETE` while it has a named source-set reason.

### G2 — compatibility (after integration)

1. **Facts.** For P4 and P5 (`.csproj`, `--flow-locals --no-project-refs`), and for the extractor's sample tree
   `frontend/roslyn/samples` (directory mode), the facts document is **byte-identical** with and without
   `--binding-coverage`. It must also equal the extractor built from `main` `22b29d5b` without the flag.
2. **Controls.** K1, K2, K4, K5, K6, K7, K11, K12, F2.3, F2.4, F2.5 and the guard self-test are run against the
   **production** code: the evidence harness references the built extractor assembly. K3, K8a, K8b, K8c, K9, K10
   and G0 run through the production flag and are compared with the SDK oracle.
   - All results must equal #422's.
   - G0 must equal the oracle, or the narrowed rule must apply.
3. **Isolation.** `foreign_binding = 0` in every control and in P4/P5.
4. **Determinism.** The sidecar is byte-identical across 3 runs for P4 and P5.
5. **Repository gates.**
   - `ruff check .` passes.
   - The repository's Python test suite passes, as far as it runs on this host.
   - The extractor builds with no new warnings.

### G3 — cost (limits not loosened from the Tiny PoC)

- **Where.** P5 and P4, 3 separate processes each, through the production flag.
- **Wall time.** Measured with and without the flag. The added time for the flag must be ≤ **3 ×** the #422
  `legacy-merged` warm median measured in the same session. In practice, the exact-mode warm cost must stay within
  the #422 limit: P5 warm exact ≤ 3 × legacy.
- **Peak working set.** ≤ **2.0 GB**.
- **Reported:** the extractor's total wall time with and without the flag.

## 3. Verdict

- **`PASS-P014-PROD0`.** G0 is PASS, or G0 is resolved by the pre-registered narrowing, **and** G1, G2 and G3 hold.
- **`KILL-P014-PROD0`.** Any of:
  - a facts byte difference;
  - a foreign binding, or a silent false binding;
  - G1 fails;
  - the cost limit is exceeded;
  - a forbidden action is needed.
- **`INCONCLUSIVE-P014-PROD0`.** The budget runs out, or a gate is undecidable because an input is missing.

A PASS allows **only** the opt-in coverage flag. It does not switch the extractor to the new resolver, and it does
not feed any new fact to diagnostics.

## 4. Not done

- Restore or build of third-party projects; any network access.
- MSBuild evaluation of P4/P5.
- Changes to OwnIR, the core, the Rust engine, goldens or SARIF.
- Reopening #407.
- Any change to the lifetime model.
