# P-022 step 7a (#260) — the sweep: five pinned repositories, large-solution controls, examples, path forms

> **Scope of this note.** It is the record of #260's **final acceptance
> measurement** — the part of its test matrix the acceptance surfaces over the
> committed corpus deliberately did not take: the five pinned OSS repositories
> of #243 at their pinned commits, the large/multi-project solution controls,
> the `examples/` tree, and the Windows path forms. The contract it runs under
> is D-4..D-7, B-2, B-3, R-1 and R-2 in the
> [owner-decision ledger](p022-shadow-infra-owner-decisions.md); this note may
> not reopen any of them. What the committed corpus already proves is
> [the acceptance note](p022-shadow-acceptance.md); this is its §6 first two
> bullets being taken rather than restated.

**Where the numbers are.** Every count this sweep *produced* — documents,
outcomes, denominators per target, byte sizes, wall-clock — lives in
[`docs/generated/p022-shadow-sweep.md`](../generated/p022-shadow-sweep.md),
rendered by `scripts/render_checkpoint_status.py` from the recorded run, and is
reached from here by link. The inventory below is the other kind of number: the
*inputs* measured from the checkouts before anything ran, so that the matrix
this note promises is a matrix somebody measured rather than one somebody
estimated. Those are stated here and also carried as data in
[`docs/evidence/p022-shadow-sweep.json`](../evidence/p022-shadow-sweep.json).

---

## §1 — The targets, the pins, and what this environment can actually do

### 1.1 The five, and the pin rule

The targets and commits are #243's, **reused verbatim** and never re-resolved
against upstream HEAD. They are copied from
[`docs/notes/precision-remeasure-2026-07-12-data/`](precision-remeasure-2026-07-12-data/),
which is the machine-readable record of the last sweep that used them, not from
the prose of the note beside it.

| target | upstream | pinned commit |
|---|---|---|
| ShareX | `ShareX/ShareX` | `0df9ca4d83eed9d2489048c539d7d1fc2860fdec` |
| MahApps.Metro | `MahApps/MahApps.Metro` | `72099e310bac2d12ac98fd7560b69679252519f5` |
| MaterialDesignInXamlToolkit | `MaterialDesignInXAML/MaterialDesignInXamlToolkit` | `ef3a5ea434e39182b1848f5e11aaea6b3890581f` |
| AvalonEdit | `icsharpcode/AvalonEdit` | `ed0bd149059469ac9bd39b13cf8a341b12a6c1da` |
| ClosedXML | `ClosedXML/ClosedXML` | `4e89dcedd83cad553e84d2d97f77fc3d7deb630f` |

**The pin rule.** A checkout is materialized by fetching *the commit itself*
(`git fetch --depth 1 origin <sha>`, then `git checkout --detach FETCH_HEAD`),
so what lands is the pin rather than a branch tip that happens to contain it.
Before anything else runs, `git rev-parse HEAD` is compared with the pin. **A
mismatch is a hard failure of that target, not a warning and not a newer
measurement.** A target that moved has not been measured; it has been replaced.

The same rule applies to the *port's* half. The adapter is named in every
recorded comparison by `sha256` and byte length as well as by path, and
`OWN_SHADOW_ENGINE` is always set explicitly — a driver that found
`rust/target/debug/own-shadow-engine` because the environment was unset
compared *an* engine, not *the* engine.

### 1.2 What this environment is

This environment **can** run the whole matrix, so it does: the G.0 fallback
(take the measurement through the workflow and read its artifacts back) is not
used, and the recorded run is a local one whose commands, commits and artifact
identities are on the record. What made that possible, measured rather than
assumed:

| capability | what is present |
|---|---|
| .NET SDK | 10.0.400 — builds the extractor's pinned `net8.0` target |
| .NET runtimes | `Microsoft.NETCore.App` 8.0.30 and `Microsoft.WindowsDesktop.App` 8.0.30 |
| Roslyn | pinned by the extractor itself (`Microsoft.CodeAnalysis.CSharp` 4.9.2), so the SDK version does not move the parse |
| Rust | 1.98.1 (`x86_64-pc-windows-msvc`), installed for this work; MSVC 14.44 + Windows SDK 10.0.26100 were already present |
| host | Windows 11 — which is why the path-form leg of the matrix is a *local* measurement here and a `windows-latest` job in CI |

The reference pack is materialized exactly the way `ci.yml`'s
`corpus-benchmark` job does it — a scratch `net8.0-windows` project with
`UseWPF` / `UseWindowsForms` / `EnableWindowsTargeting`, `dotnet restore`, then
the resolved `ref/net8.0` directory exported as `OWN_EXTRA_REF_DIRS`. It
resolves to `microsoft.windowsdesktop.app.ref` **8.0.30** here; the 2026-07-12
remeasure resolved **8.0.28**. Both carry 47 DLLs. That difference is recorded
rather than pinned away because **it cannot bias this measurement**: whatever it
does to a facts document, both engines receive that document as the same
bytes. It would matter to a precision remeasure; this is not one.

### 1.3 The disk and wall-clock the matrix costs

Measured on this machine before the matrix was promised, one target extracted
first (AvalonEdit, the smallest) and then the rest:

| item | measured |
|---|---|
| the five checkouts, on disk | ~147 MB total (AvalonEdit ~3 MB, ClosedXML ~26 MB, MahApps.Metro ~32 MB, ShareX ~41 MB, MaterialDesign ~45 MB) |
| extraction, all ten documents | ~98 s total; the slowest single document is ShareX's directory walk at ~20 s |
| the ten facts documents | ~1.1 MB total; the largest is ~250 KB |
| compare, per document | well under a second — the committed-corpus gate runs 104 documents in ~0.7 s |

The consequence for the timeout policy is in §2.4: nothing here is near the
driver's default, and the default is therefore kept and *recorded* rather than
raised on a guess.

---

## §2 — The matrix, exactly as it will be run

### 2.1 Which targets carry a solution — measured, from the checkout

Counted by resolving each `.sln`'s `Project(...)` entries to `.csproj` members
that exist on disk, and counting the `.cs` files under those members:

| target | solutions found | member projects | `.cs` under members |
|---|---|---|---|
| ShareX | `ShareX.sln` | 13 | 1126 |
| | `ShareX.ImageEditor.sln` | 2 | 433 |
| ClosedXML | `ClosedXML.sln` | 6 | 921 |
| MahApps.Metro | `src/MahApps.Metro.sln` | 4 | 328 |
| AvalonEdit | `ICSharpCode.AvalonEdit.sln` | 3 | 248 |
| | `ICSharpCode.AvalonEdit.Documentation.sln` | 1 | 214 |
| MaterialDesignInXamlToolkit | **none** — `MaterialDesignToolkit.Full.slnx` only | — | — |

**MaterialDesignInXamlToolkit has no classic solution at its pinned commit.**
It carries the XML solution format (`.slnx`), and the extractor's solution
resolver reads the classic `Project("{...}") = "name", "path"` form only. That
is a *measured gap*, recorded here and nowhere else acted on: teaching the
extractor `.slnx` would be a production change, and this task changes no
production behaviour. The target is therefore covered by its directory walk
alone, and the record says so per target rather than averaging it away.

### 2.2 The large-solution controls taken

#260 asks for "selected large/multi-project solutions" and this task's brief for
"at least the two largest". Taken: **the largest solution of every target that
has one** — `ShareX.sln` (13 members), `ClosedXML.sln` (6), `MahApps.Metro.sln`
(4), `ICSharpCode.AvalonEdit.sln` (3). The two largest are the first two; the
other two are nearly free and make the mode's coverage per-target rather than
per-sample. `ShareX.ImageEditor.sln` and the AvalonEdit documentation solution
are proper subsets of the solutions already taken and are skipped for that
reason, which is a choice on the record rather than a silent omission.

The solution documents are **not** the directory-walk documents under another
name. Measured on ShareX: the two documents carry the same 106 components and
74 functions, in a **different order** — the fan-out enumerates the source set
project by project, the walk enumerates it in directory order — so they have
identical byte length and different digests, and they are two documents, not
one. That is exactly the property a large-solution control is for: a different
extractor path, a differently ordered document, and per-layer ordering
semantics that are *declared* rather than normalized away.

### 2.3 The ten documents, and the commands, verbatim

Ten documents, each extracted **exactly once**. `scripts/own-check.sh` runs the
extractor once into a temporary file and `--emit-facts <path>` persists exactly
that file; stage 2 (`python -m ownlang ownir`) is the reference's *verdict* path
and is neither a second extraction nor the comparison. The comparison is the
driver's, taken from the emitted bytes.

```bash
# per document, with <REFDIR> the materialized WindowsDesktop ref pack (§1.2)
OWN_EXTRA_REF_DIRS=<REFDIR> scripts/own-check.sh \
    --format sarif --severity warning \
    --emit-facts <FACTS> -- <INPUT>
```

| document | mode | `<INPUT>` |
|---|---|---|
| `ShareX.repo` | directory walk | `<checkout>/ShareX` |
| `MahApps.Metro.repo` | directory walk | `<checkout>/MahApps.Metro` |
| `MaterialDesignInXamlToolkit.repo` | directory walk | `<checkout>/MaterialDesignInXamlToolkit` |
| `AvalonEdit.repo` | directory walk | `<checkout>/AvalonEdit` |
| `ClosedXML.repo` | directory walk | `<checkout>/ClosedXML` |
| `ShareX.sln` | `.sln` fan-out | `<checkout>/ShareX/ShareX.sln` |
| `ClosedXML.sln` | `.sln` fan-out | `<checkout>/ClosedXML/ClosedXML.sln` |
| `MahApps.Metro.sln` | `.sln` fan-out | `<checkout>/MahApps.Metro/src/MahApps.Metro.sln` |
| `AvalonEdit.sln` | `.sln` fan-out | `<checkout>/AvalonEdit/ICSharpCode.AvalonEdit.sln` |
| `examples` | directory walk | `<Own.NET>/examples` |

The driver then runs **once** over a manifest naming all ten:

```bash
cd rust && cargo build --release -p own-shadow --bin own-shadow-engine
OWN_SHADOW_ENGINE=<the adapter just built> \
  python scripts/shadow_compare.py --engine compare \
    --manifest <manifest.json> --out <run dir> --quiet
```

and the Windows path-form leg is the committed-corpus gate, on this host, with
the adapter built on this host:

```bash
OWN_SHADOW_ENGINE=<the adapter just built> \
  python scripts/shadow_compare.py --engine compare --corpus --quiet
OWN_SHADOW_ENGINE=<the adapter just built> OWN_SHADOW_COMPARE_REQUIRED=1 \
  python tests/test_shadow_compare.py
```

### 2.4 What "covered" means here, and the timeout policy

**A repository is not covered because extraction succeeded, and a solution is
not covered because some project inside it emitted OwnIR.** Coverage is a
recorded, non-empty set of OwnIR documents fed byte-identically to both engines
and judged by compare mode — *per target, with the denominator on the record*.
This is the direct descendant of the fifth failure mode in #250: a green gate
over an empty set is worse than a red one, because a red one at least says it
is awake. Hence three rules the driver enforces rather than this note asserting
them:

* a run that compared **zero** documents is a **failure**, never agreement;
* a **target** whose compare-attempted count is zero is a **failed target**,
  never a passed repository;
* every document's `facts_sha256` in the manifest is checked against the bytes
  the driver actually read, and every document is validated **before any engine
  runs**.

**Timeouts.** Explicit per document and recorded per document. §1.3 measured the
whole matrix as sub-second per compare, three orders of magnitude inside the
driver's 120 s default, so the default is what the manifest carries — stated as
a number in the manifest rather than inherited silently, so that raising it for
a future target is a visible edit. A timeout is an **execution failure with a
report** (R-2), never a silent skip.

### 2.5 The sweep ledger schema

Two documents, the same split every campaign in this tree uses — a
**definition** that says what should be measured and a **result** that records
one actual run of it, with one interpreter reading both.

`docs/evidence/p022-shadow-sweep.json` — the definition:

```text
schema, sweep, description
adapter_build_command          how the port's half is produced
driver_version                 the shadow_compare_version this definition expects
timeout_seconds                the default the manifest carries
targets[]  { target, upstream, pinned_commit, solutions[], slnx[], notes }
documents[] { id, target, extraction_mode, extraction_command, input,
              timeout_seconds }
```

`docs/evidence/p022-shadow-sweep.result.json` — one run:

```text
schema, sweep, definition, definition_sha256
source_commit, recorded_at, host, workflow_run_url  (null for a local run)
adapter { path, sha256, bytes }
driver_version
documents[] { id, source, target, target_commit, extraction_mode,
              extraction_command, facts_sha256, raw { digest, bytes },
              canonical { digest, bytes }, outcome, timeout_seconds,
              reduction_outcome, by_kind{}, by_acceptance{},
              derived_outcome, wall_clock_seconds }
targets[]  { target, documents_extracted, compare_attempted, agreed,
             diverged, execution_failures, input_refusals,
             input_disagreements, declared_boundary_observations,
             acceptance_unexplained_observations }
totals     { the same fields, summed }
```

`tests/shadow_sweep.py` is the single interpreter of the pair.
`scripts/render_checkpoint_status.py` renders
`docs/generated/p022-shadow-sweep.md` from it and
`tests/test_checkpoint_status.py` gates that the committed fragment equals the
projection — the same pipeline every campaign count in this repository already
goes through. **A re-run replaces the result whole; it is never patched.**

### 2.6 The churn budget, written before anything moved

* `tests/fixtures/` — **nothing**, unless a divergence produces an artifact
  small enough to be a control, in which case it is added insertion-stable and
  the finding that produced it is on the record with it. The frozen goldens do
  not move for a measurement.
* `docs/evidence/` — gains the sweep definition and one recorded result, plus
  one campaign definition and result over the driver's new pieces.
* `docs/generated/` — gains `p022-shadow-sweep.md` and the campaign fragment
  regenerates.
* **The five repositories' facts documents do not enter the repository.** They
  are large and exactly reproducible from the pins and the commands in §2.3;
  their *identities* (the raw digest and byte length of each, and the canonical
  identity both engines derived) are what the result records.
* **Production behaviour changes nowhere.** Not in `ownlang/`, not in the
  analyses, not in the renderers, not in `own-check.sh`'s verdict path. The
  driver, the adapter, the workflow and the evidence pipeline are dev tooling.
* **The comparison machinery is frozen for the measurement.** The canonical
  form, the artifact verifier, the trace, the reducer, `BOUNDARY_POLICY`, the
  derived-SARIF configuration and the driver's *judgement* do not move while
  the sweep runs. A divergence is a finding first; adjusting a normalizer to
  make one go away is a contract change that waits for the owner.
