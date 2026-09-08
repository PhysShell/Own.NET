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
(take the measurement through the workflow and read its artifacts back) was not
needed for the FIRST record, a local run whose commands, commits and artifact
identities were on the record; the record now on file is the CI run of §3, which
replaced it whole. What made that possible, measured rather than
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
schema, comment, sweep
driver_version                 the shadow_compare_version this definition expects
default_timeout_seconds        the default a manifest entry inherits
adapter_build_command          how the port's half is produced
driver_command                 how the run is taken
reference_pack, pin_rule       the environment and the drift rule, as prose
targets[]   { target, upstream, pinned_commit, solutions[], slnx[], note }
documents[] { id, target, target_commit, extraction_mode,
              extraction_command, timeout_seconds }
```

`pinned_commit` and a document's `target_commit` are **null** for the one target
whose pin is this repository itself (`examples`): the interpreter then requires
the recorded pin to equal the run's own `source_commit`, which is a check rather
than an exemption.

The **manifest** the driver is actually given is a third document, not
committed: it is the definition's rows joined to the facts files a run produced,
each with the `facts_sha256` of the bytes on disk and the `id` that ties it back
to the definition. It is not committed because it names paths on the machine
that ran, and because regenerating it is how a re-run is taken.

`docs/evidence/p022-shadow-sweep.result.json` — one run:

```text
schema, sweep, definition, definition_sha256
source_commit, recorded_at, host, workflow_run_url  (null for a local run)
adapters[] { sha256, bytes }   (one per leg; CI legs build their own)
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

---

## §3 — What ran, and what it found

One run, taken in CI at `321ab8b` ([run 34186824607](https://github.com/PhysShell/Own.NET/actions/runs/34186824607),
a dispatch of `.github/workflows/shadow-sweep.yml` by the branch ref of
PR #344, after that PR's first commit taught each leg to name its document by
id; every leg on `ubuntu-latest` and the path-form leg on `windows-latest`),
recorded whole in
[`docs/evidence/p022-shadow-sweep.result.json`](../evidence/p022-shadow-sweep.result.json)
and interpreted into
[`docs/generated/p022-shadow-sweep.md`](../generated/p022-shadow-sweep.md),
which is where every count of it lives. Per **document** it names the pin that
was verified, the extraction mode, the raw and canonical identities and the byte
size, the outcome, the derived-SARIF outcome, the wall clock and the timeout
that was in force. Per **target** it names the denominators: documents
extracted, documents compared, and the outcome breakdown — so a target that had
been skipped would appear at zero rather than not appear at all.

It replaces the first record, a local run taken on a Windows host at the branch
commit the note below still describes; a re-run replaces the result whole and
never patches it, and the local run's identities are in the history of this
file, not on it.

**The environment, exactly as §1.2 promised and with the two differences from
the 2026-07-12 remeasure on the record.** The extractor is the pinned
`Microsoft.CodeAnalysis.CSharp` 4.9.2 built by a .NET 10.0.400 SDK against the
8.0.30 runtime (the remeasure used an 8.0.422 SDK), and the reference pack
resolved to `microsoft.windowsdesktop.app.ref` **8.0.30** (the remeasure
resolved 8.0.28) — 47 DLLs either way. Neither can bias this measurement:
whatever they do to a facts document, both engines receive that document as the
same bytes. They would matter to a precision remeasure, and this is not one.

**Extraction is reproducible, and that was checked rather than assumed.** The
ten documents were extracted three times on this host — for §1.3's wall-clock
inventory, and twice more as the recorded run was re-taken at a later commit —
and all ten digests are identical across all three passes.

The commands are §2.3's, verbatim, and they are carried as data in the sweep
definition so the workflow, the note and the record cannot drift into three
readings of one command.

**The campaigns.** Three are recorded on a clean tree, each at the commit it
measured, with no survivor and no missed catcher: the new `p022-shadow-sweep-1` over the driver's
version-2 surfaces and the sweep interpreter, and `p022-shadow-acc-1` and
`p022-shadow-acc-2` re-run because this branch moved both their target and their
catcher files — which is the re-run rule the acceptance note wrote down. Two of
`acc-2`'s mutations were **re-anchored** onto the moved compare path and each
still expresses its own rule: "the driver stops failing the run when an engine
crashes" and "the driver hands the port bytes it did not hand the reference".
Every count is in [the campaign
fragment](../generated/p022-shadow-mutations.md).

## §4 — The differential this run asserts

The gate is a property of a green run, not a number in this note.

* **Every document in the definition is in the result**, measured at the pin,
  in the mode and by the command the definition declares — `tests/shadow_sweep.py`
  refuses a run that is short, a run that is long, and a run that measured
  something else.
* **Every document's outcome is `agreed`**, and no observation is
  acceptance-unexplained — including inside a document recorded as agreed,
  which is checked separately because an outcome that contradicts its own
  observations is a finding rather than a rounding.
* **Every target's compare-attempted count equals its documents-extracted
  count, and neither is zero.**
* **The totals are the sum of the per-target rows**, recomputed rather than
  read.
* **The run names the engine it ran** by `sha256` and byte length, and the
  driver version the definition expects.
* **The run's `source_commit` is an ancestor of HEAD** — the same provenance
  rule every recorded campaign in this tree is held to.

Any one of those failing is a red `tests/run_tests.py`, because the fragment is
rendered from the same interpreter the gate runs.

## §5 — Findings

**No document diverged, so G.4's three resolution paths were not needed: there
is no port bug, no reference question and no new boundary here.** The frozen
comparison machinery — the canonical form, the artifact verifier, the trace,
the reducer, `BOUNDARY_POLICY`, the derived-SARIF configuration and the
driver's judgement — was not touched, and no fixture under `tests/fixtures/`
moved.

What the measurement did find is six defects in the *harnesses*, all six
invisible on the platform CI runs on, and each is a shape worth naming. Three of
them are in the mutation harness, and they compound: together they meant that no
campaign in this repository could be recorded anywhere but Linux, and that the
one which failed loudest failed only after the other two had been fixed.

1. **The driver died on a label.** `os.path.relpath` raises `ValueError` for a
   path on another Windows drive, and the sweep's facts documents live outside
   the checkout by design — so the very first sweep document killed the driver
   before either engine ran, over the string a result records as its `source`.
   The fix is a label that falls back to the absolute path; the shape is worth
   remembering, because the failing code was the one line in the loop that had
   nothing to do with comparing anything.

2. **The timeout was not a timeout.** `subprocess.run(timeout=…)` kills the
   child and then waits for the pipes to close, so a surviving grandchild
   blocks the driver for ever. Owner decision R-2 makes a timeout a run-level
   hard failure the driver has to *report*, which a driver that never returns
   does not do. The adapter starts nothing, which is exactly why this had never
   been hit — the property is about what the driver guarantees, not about what
   today's adapter happens to do. The child now gets its own process group on
   POSIX and is killed as a tree on Windows.

3. **The control group that would have caught it could not run at all.** The
   driver invokes its adapter as one argv entry (R-1: no arguments), and
   Windows cannot start a `.py` — `CreateProcess` does not consult file
   associations. Every double-driven control failed there with `WinError 193`:
   the group whose stated purpose is that it "runs everywhere, including the
   Python-only test matrix" ran nowhere on Windows, and had done since it was
   written. A launcher beside the double fixes it without touching the driver's
   contract. Finding 2 was found five minutes later, by the control that could
   finally execute.

4. **The mutation harness refused its own work and blamed the tree.**
   `run_campaign` restores each target and then compares `git status` with the
   baseline; it read and wrote through Python's text mode, so on a CRLF working
   copy every campaign rewrote its targets' line endings and died with "the
   working tree changed during S01 — the run is void". The tree had changed.
   What changed it was the harness, and no campaign could be recorded on that
   platform at all. Its own "was it restored?" check never saw it, because that
   check compares *text*: it read the rewritten file back through the same
   translation and got the same string. A property about bytes on disk is not
   observable from above them, which is why the control drives `read_source` /
   `write_source` directly.

5. **A catcher's name took the host's spelling, and under-reported rather
   than failed.** cargo prints its test target with the host separator, so on
   Windows a failing test is recorded as `own-shadow/tests\repro.rs::…` where
   every campaign definition and every committed result says
   `own-shadow/tests/repro.rs::…`. Measured on a real re-run of
   `p022-shadow-acc-1`: five of twelve mutations reported "expected catchers
   MISSED" while the catcher list printed beside them named exactly the test
   that had been expected. That is worse than an outright failure, because the
   answer looks like a finding — "a rule went unprotected" — and would have been
   filed as one. A catcher name is an identity; the target is normalized where
   it is parsed, and the control drives the parser with both spellings of one
   cargo run.

6. **A layer's output was decoded with the console codepage.** `_run_layer`
   read its child with `text=True` and no encoding, so Python used the locale
   encoding; on a cp1251 console one non-ASCII byte anywhere in cargo's output
   raised `UnicodeDecodeError` inside `communicate()` and took the campaign with
   it, mid-run, after a production file had already been mutated. The
   finally-block restored the tree, so nothing was left broken — what was lost
   was the run. cargo emits UTF-8 and this repository's own test names contain
   an em dash, so the byte was never going to be exotic. Both subprocess calls
   now decode UTF-8 explicitly with `errors="replace"`: a stray byte costs one
   character rather than the campaign.

Two measured facts about the matrix itself, neither of them a defect:

7. **MaterialDesignInXamlToolkit has no classic solution at its pin.** It
   carries `MaterialDesignToolkit.Full.slnx`, and the extractor's solution
   resolver reads the classic `Project("{…}") = "name", "path"` form only.
   Teaching it `.slnx` would be a production change, which this task does not
   make; the target is covered by its directory walk alone, and the record says
   so per target rather than averaging it away.

8. **A solution document is not a directory-walk document under another name,
   and it is not a different document in the way one might expect either.**
   Measured on ShareX: the two carry the same components and functions in a
   different ORDER — the fan-out enumerates project by project, the walk in
   directory order — so they have equal byte length and different digests. That
   is a better control than a subset would have been: the two engines are
   compared on a reordered document, and per-layer ordering semantics are
   *declared* rather than normalized away.

## §6 — Measured, not claimed

* **Windows path forms.** Measured, on this host, with an adapter built here:
  the committed-corpus gate compares clean over every committed document, the
  driver's own controls run and pass under `OWN_SHADOW_COMPARE_REQUIRED=1`, and
  the sweep's own ten documents were compared on the same host with paths on a
  different drive from the checkout. The `windows-latest` leg of the sweep workflow
  has since run green in the recorded CI run: the committed-corpus gate and the
  driver's controls under `OWN_SHADOW_COMPARE_REQUIRED=1`, with an adapter built
  on that runner.
* **Linux path forms.** Exercised by the recorded CI run: every document leg is
  `ubuntu-latest`, so the ten documents were extracted and compared on Linux
  path forms; the fast gate in `ci.yml` has been `ubuntu-latest` since PR #342.
* **The C# samples.** Not re-measured here: that leg is a CI job fed by the
  `wpf-extractor` job's own OwnIR through one upload-artifact handshake, and it
  compared clean on `main` when PR #342 landed it. This branch's CI re-measures
  it; nothing in this note stands in for that result.
* **The sweep workflow itself.** Executed: the recorded run is run
  34186824607, dispatched by the branch ref of PR #344 at `321ab8b` so that it
  executed the workflow as amended by that PR's first commit; every leg green,
  the aggregation assembled the record from the legs' artifacts and checked it
  against the committed definition, and `workflow_run_url` names it. The
  workflow's first execution, run 34181417914 on `main` at `4520a54`, agreed on
  every document but recorded each document's `source` as the runner's temp
  path — a constant dressed as provenance — and is superseded by the recorded
  run; it is not on file. The first record was a local run, which #260 allowed;
  it was superseded whole. A `workflow_dispatch` workflow is dispatchable only
  once it is on the default branch, which is why the first record could not be a
  CI run; once the file is there, a dispatch by branch ref runs the branch's
  version of it.
* **Precision.** This sweep does not re-measure it. The finding counts the
  extractor produced over the five targets are not compared with #243's, and
  they would not be comparable: many analyses have landed since, and two
  environment components differ (§3). What is compared is one engine against
  the other over one byte sequence.
* **The adapter digest names the BUILD, not the port's source**, and that was
  measured on purpose rather than inferred: `cargo clean --release -p
  own-shadow` followed by the same release build, over a `rust/` tree that did
  not change by one byte, produced a different digest at exactly the same byte
  length (1 614 336). That is what the #342 review asked for — "so a stale build
  can never stand in for the engine that was meant" — and it is emphatically not
  a content hash of the port: two legs of one sweep on two runners will name two
  digests, which is why the record carries the SET of adapters a run executed
  rather than asserting one. The recorded CI run measures the other side of
  that: its `ubuntu-latest` legs each built the adapter independently and
  produced one distinct digest between them, so irreproducibility is a
  property of a build environment rather than of the port.
* **The five repositories' facts documents are not in the repository.** Their
  identities are: the raw digest and byte length of each, and the canonical
  identity both engines derived from it, are in the recorded run. They are
  exactly reproducible from the pins and §2.3's commands.
* **Rendered-byte parity of the three layer surfaces** stays each layer's own
  fixture family, as the acceptance note's §6 already records. The artifact
  carries layer outputs as JSON *values*; the derived SARIF surface is the one
  rendered surface compared byte-exactly, and it was compared on all ten
  documents here.

## §7 — The wording this earns

> **#260 final acceptance reached: dual-engine compare mode reports zero
> acceptance-unexplained over its full test matrix — the committed corpus, the
> C# samples, the examples, the five pinned OSS repositories and the
> large-solution controls — at all three layers and on the derived SARIF, on
> byte-attested same input, with the OD-1 typed-door boundaries declared by
> policy; Python remains the public engine.**

What that sentence rests on, leg by leg, so that it can be checked rather than
believed: the five repositories, the four large-solution controls and
`examples/` are the recorded run in §3, taken locally and gated by
`tests/shadow_sweep.py`; the committed corpus is the `ci.yml` job that has
gated every pull request since PR #342, re-measured here on Windows as well;
the C# samples are the `ci.yml` job fed by the extractor's own OwnIR, which
this branch's CI re-measures (§6). The OD-1 boundaries are the two typed-door
documents of the committed corpus and are unchanged; the sweep's own ten
documents produced **no** boundary observations at all, because nothing in them
reaches that door.

Not "P-022 done". Not "Rust is the default", which is #262's cutover behind
#261 — Python remains the public engine, `own-shadow-engine` is a dev-only
adapter with no command surface to grow out of, and no production behaviour
changed anywhere in this work. Not "parity" as a bare word: what was measured
is compare mode's judgement over a named set of documents, and the set is on
the record with its denominators.

### The commands this note's claims come from

```text
# the adapter, and the sweep over the ten documents of the definition
cd rust && cargo build --release -p own-shadow --bin own-shadow-engine
OWN_EXTRA_REF_DIRS=<WindowsDesktop ref pack net8.0> scripts/own-check.sh \
    --format sarif --severity warning --emit-facts <FACTS> -- <INPUT>   # per document
OWN_SHADOW_ENGINE=<the adapter just built> \
  python scripts/shadow_compare.py --engine compare --manifest <manifest.json> \
    --out <run dir>
python tests/shadow_sweep.py --collect <run dir> \
    --write docs/evidence/p022-shadow-sweep.result.json
python tests/shadow_sweep.py
python scripts/render_checkpoint_status.py

# the Windows path-form leg
OWN_SHADOW_ENGINE=<the adapter just built> \
  python scripts/shadow_compare.py --engine compare --corpus --quiet
OWN_SHADOW_ENGINE=<the adapter just built> OWN_SHADOW_COMPARE_REQUIRED=1 \
  python tests/test_shadow_compare.py

# the sweep in CI (on the default branch)
gh workflow run "shadow sweep (#260)"

# the campaigns re-run in this branch, and the new one
python scripts/mutate_campaign.py --campaign docs/evidence/<name>.json --validate
python scripts/mutate_campaign.py --campaign docs/evidence/<name>.json --run

python tests/run_tests.py
ruff check . && mypy
cd rust && cargo test --workspace --no-fail-fast
```
