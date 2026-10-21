# P-014 bounded design — pre-registration

Written 2026-10-21 07:00 +05, before the source-level audit and before any falsifier run. Base: `main`
`ad17d7b2` (merge of #419). #420 (`bf0b4e0a`, report text only) is read but not merged or changed.

**Budget.** 0.5 agent-day, counted from 06:55. Not extended. When it runs out, I stop and commit whatever evidence
exists, with the verdict `INCONCLUSIVE-P014-DESIGN`.

**Owner mandate.** `GO-P014-BOUNDED-DESIGN / NO-PRODUCTION` (#420 §8.7). This packet is a design only:
- no production, OwnIR, core, extractor, CI or golden change;
- no restore, build or MSBuild evaluation of third-party projects; no package download;
- no re-run of the #419 sweep.

## 1. Question

Can C# semantic binding be made more trustworthy while meeting three conditions?
- foreign references do not leak between projects;
- a partial analysis is not reported as a complete one;
- newly resolved symbols do not turn into a stream of false OWN001/event findings.

## 2. Allowed evidence

- **Source reading** of the extractor, the core, the specs and the docs, at `ad17d7b2`.
- **#419 data as frozen:**
  - R2 counts;
  - the 50-site sample;
  - the R3 triage: 1 actionable TP, 2 minor TPs and 6 FPs;
  - K1–K7.

  Nothing is re-scored.
- **Cheap falsifiers.** Synthetic fixtures only, at most a few files each, written under this folder:
  - run through the frozen #419 instrument (`instrument/`), or through a throw-away Roslyn script in a temp
    folder;
  - read-only inspection of the `project.assets.json` files already on disk for P1–P5 (structure only:
    `targets` keys, `project.frameworks`, `type: project` libraries, RID targets).

  No third-party project is built or restored.
- **Official NuGet/MSBuild/Roslyn documentation**, only for claims about how those tools define things. It never
  replaces our measurements.

## 3. Gates and kill rules (fixed now)

Each gate states a necessary condition, the cheapest falsifier I will try, and a KILL condition. A gate is `PASS`
only if its falsifier was tried and failed to break the condition, or the condition holds by construction and I
cite the code or documentation for it.

| Gate | Necessary condition | Cheapest falsifier | KILL if |
|---|---|---|---|
| **D1 correctness** | For a bounded input class (SDK-style, existing `obj/project.assets.json`, one chosen TFM), a resolver can name the exact reference set from on-disk data | An input from the supported class where the algorithm picks a wrong assembly, or binds a symbol with certainty it should not have | The class shrinks to nothing useful, or excluding wrong picks needs MSBuild evaluation / a project-system clone |
| **D2 isolation** | Project A's references, usings or source cannot change project B's binding | Synthetic: two projects with `Dup.T`; same simple assembly name at two versions; `ImplicitUsings` enable vs disable; `Timer` ambiguity; one project with missing dependencies | The design still merges different projects into one compilation and reports the result as trustworthy |
| **D3 honest coverage** | A deterministic, machine-checkable coverage record with explicit numerators, denominators and scope, in which unsupported and skipped never count as clean | Construct a case where the proposed record reports "resolved" or "complete" while a method was skipped, or a reference was missing | No such record fits the existing `--stats`/OwnIR contract without a new incompatible vocabulary |
| **D4 precision** | New facts reach public verdicts only under a policy that cannot regress true findings or known negative controls | Replay the #419 R3 triage (9 new findings) under each policy; check that the policy does not depend on suppressing the 6 known FPs | Every policy that delivers the 1 actionable TP also activates the 6 FPs in the default mode, and there is no opt-in boundary |
| **D5 cost** | The design runs with no restore, no network, no third-party MSBuild targets and no `MSBuildWorkspace`; it keeps `--ref-dir` and directory mode; it degrades honestly when assets or packs are missing | Name a required input that is only obtainable by a forbidden action within the supported class | Safe resolution needs a forbidden action, or its cost clearly exceeds the measured benefit (1 actionable TP over 5 projects) |

## 4. Verdict rule (fixed now)

- **`GO-P014-TINY-POC`.** D1–D5 are all `PASS`, possibly with a narrowed input class. The recommended
  architecture's PoC contract can be stated with fixtures, an expected manifest, K1–K7, a KILL and a budget.
  - It does **not** authorise production code.
  - It does **not** authorise diagnostic activation.
- **`KILL-P014-DESIGN`.** Any gate meets its KILL condition.
- **`INCONCLUSIVE-P014-DESIGN`.** A gate cannot be decided within the budget, or it depends on an input that is
  not available locally.

Priorities fixed now:
- A narrow, correct mode is preferred over a wide one that sometimes binds the wrong C# semantics.
- A result that keeps public verdicts unchanged ("coverage-only") is allowed to count as the useful outcome. The
  owner's direction (#420 §8.7) puts coverage and the ban on silent wrong binding before new warnings.

## 5. What I will not claim

- Any performance figure that I did not measure.
- Correctness of symbols that were not read.
- That a reference-correct compilation has a complete source set. Implicit usings, `#if` defines, generated
  sources and project references are a separate axis.
