# #400 dictionary-ref pilot — bounded Roslyn PoC

**Verdict: `KILL-DICTIONARY-REF-PILOT`.** Owner ruling: `ACCEPT KILL / ARCHIVE AS SEPARATE RESEARCH PR`, outcome
`STOP-PRODUCTION / KEEP-EVIDENCE`.

The pre-registered precision gate (≥ 80 %) failed on both independent samples:
- round 1, probe v1: 64 %;
- round 2, probe v2: 73 %.

The two confirmed real defects were found, and the controls passed. Both are kept as positive research evidence.
They do not authorise a production implementation.

No production code, OwnIR, CI or golden file was changed. No implementation PR exists. A third round is not
authorised (§7).

Context: the research report and the decision `GO-400-DICTIONARY-PILOT` are in
[`../next-bug-class-2026-10/REPORT.md`](../next-bug-class-2026-10/REPORT.md) (PhysShell/Own.NET#412).

## 1. What was tested

A ref from `CollectionsMarshal.GetValueRefOrAddDefault` or `GetValueRefOrNullRef` into dictionary `D` becomes stale
when `D` is structurally mutated while the ref is live. A resize moves the entries, and the ref still points into
the old array. The PoC targets only this mechanism. It does not target the second Meziantou defect (default left
inserted when the factory throws).

The probe is a standalone Roslyn console app, outside Own.NET production code. It uses
Microsoft.CodeAnalysis.CSharp 4.9.2 on net8.0, with the running runtime's assemblies as references.

It warns when the ref local is read or written after a hazard event. A write in `x = f()` counts, because the
location of `x` is evaluated before `f` runs. Matching is by symbol.

| Hazard event | Condition |
|---|---|
| direct | `Add`/`TryAdd`/`Remove`/`Clear`/`EnsureCapacity`/`TrimExcess` on the same `D`, an indexer write, or another `GetValueRefOrAddDefault(D, …)` |
| delegate | a delegate invocation, when code outside the method can reach `D`: `D` is a field, property or parameter, or a local that escaped (v1: anywhere in the method; v2: before the event) |
| callee | a first-party method or constructor in the analysed file (depth ≤ 4) whose body has a direct or delegate event on the same field or property `D` |

Not hazards:
- metadata (BCL) calls;
- constructors and first-party callees without events;
- mutation of a different dictionary;
- an event on a branch exclusive with the use;
- a ref re-bound with `x = ref …`;
- v2 only: an event followed by `return`/`throw` in its own block that does not contain the use.

## 2. Frozen artifacts

| Artifact | Identity |
|---|---|
| Probe v1, round 1 | [`probe-v1/Program.cs`](probe-v1/Program.cs), sha256 `cd49e9a5…` |
| Probe v2, round 2 (final) | [`probe-v2/Program.cs`](probe-v2/Program.cs), sha256 `536762c6…` |
| Controls | [`controls/Controls.cs`](controls/Controls.cs), sha256 `444f2bb2…`. N8 and N9 were added with v2 |
| Pre-registration | [`PRECISION-PREREG.md`](PRECISION-PREREG.md) (verbatim). Round-1 rules were written before the round-1 sample was fetched. The round-1 result and the round-2 rules were written before the round-2 sample was fetched |
| Targets | meziantou/Meziantou.Framework `7addb26c` (buggy) and `cf82931e` (fixed); dotnet/maui `7b051d1b` (buggy) and `2db8b6af` (fixed). One file each, fetched by commit SHA |
| Samples | [`data/r1/index.tsv`](data/r1/index.tsv): 429 files, 183 repos. [`data/r2/index.tsv`](data/r2/index.tsv): 252 files, 189 repos. Pinned by blob SHA. Raw search hits are in `raw.tsv`/`all.tsv`; the derivation is in `scripts/make_index.py` |

Full hashes are in [`SHA256SUMS`](SHA256SUMS). No third-party source is committed.

## 3. Gates

| Gate | v1 | v2 |
|---|---|---|
| Meziantou buggy: `DictionaryExtensions.cs:31` (`GetOrAdd`) and `:56` (`TryUpdate`) | found | found |
| MAUI buggy: `BindableObject.cs:793`, chain `CreateContext → defaultValueCreator(this)` | found | found |
| Meziantou fixed (2 sites) | 0 warnings | 0 warnings |
| MAUI fixed | 0 sites: the fix removes the API from that method, so "clean" is trivial | same |
| Positive controls P1–P4 | 4/4 | 4/4 |
| Mandatory negative controls: N1 no mutation; N2 a different dictionary; N3/N3b/N1 safe factory (constructor, pure first-party, BCL); N4 ref used only before the mutation | silent | silent |
| Further negatives: N5 local dictionary; N6 exclusive branches; N7 fresh ref | silent | silent |
| Round-1 FP shapes: N8 `return`/`throw` after the mutation; N9 a local that escapes later | **N8 flagged** (the shape v2 fixes); N9 silent | silent |
| Precision ≥ 80 % on an independent sample | **FAIL** (64 %) | **FAIL** (73 %) |
| Third-party analyzers (Meziantou.Analyzer, Roslynator, ErrorProne.NET) | NOT_TESTED: package download not authorised. This is not a MISS | — |
| Built-in NetAnalyzers (`AnalysisMode=All`, #412) | no rule fires on these shapes | — |
| OwnIR reuse | not attempted: the relation "a mutation invalidates the borrow" has no OwnIR form today, and `release`/`use` would be a false semantic claim | — |

N9 is silent under v1 too, so this control does not separate v1 from v2. The evidence for v2 change (b) is the two
round-1 false positives F17/F18 themselves.

Outputs: [`data/targets.v1.out`](data/targets.v1.out), [`data/targets.v2.out`](data/targets.v2.out),
[`data/controls.v1.out`](data/controls.v1.out), [`data/controls.v2.out`](data/controls.v2.out).

## 4. Precision, as measured

Labelling rules were fixed before each sample was fetched:
- **TP**: on some execution the event can structurally mutate the same dictionary while the ref is live.
- **FP**: the event provably cannot.
- **UNCLEAR**: this cannot be decided from the file.

Precision = TP / (TP + FP). Conservative precision counts UNCLEAR as FP.

| Round | Probe | Files / repos | Sites | Warnings | TP | FP | UNCLEAR | Precision | Conservative | TP repos |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | v1 | 429 / 183 | 274 | 18 | 9 | 5 | 4 | **64 %** | 50 % | 6 |
| 2 | v2 | 252 / 189 | 290 | 14 | 8 | 3 | 3 | **73 %** | 57 % | 7 |

These are the measurements as taken:
- no warning was relabelled after the fact;
- v2 was not re-scored on the round-1 sample;
- round 1 is not discounted because v2 fixed some of its causes.

Every warning, with its blob SHA, lines, event, label and reason, is in [`data/r1/findings.tsv`](data/r1/findings.tsv)
and [`data/r2/findings.tsv`](data/r2/findings.tsv). The labels as written during labelling are in `data/r*/labels.tsv`.

Causes:
- Round-1 FP (5):
  - an event followed by `return`/`throw` (3: F11, F14, F15);
  - a method-local dictionary that escapes only after the event (2: F17, F18).
- Round-2 FP (3):
  - a callee's delegate mutates a different, passed-in dictionary (G1);
  - an indexer write to the key just added, which is not structural (G2);
  - an event followed by `continue` (G7).
- UNCLEAR (4 + 3): opaque non-factory delegates such as a TTS callback, an account getter, a logger provider, a
  terrain query or an AABB extractor.

### Contract violation vs observable defect

[`data/effect.tsv`](data/effect.tsv) splits the 17 TPs. It was written after the owner ruling, from the reasons
recorded at labelling time. No label changed.

| Class | Count | Meaning |
|---|---:|---|
| PROVEN | 0 | none of the sample TPs was reproduced at runtime |
| CONTRACT_ONLY | 3 (F5, G9, G11) | the ref contract is broken, but no observable effect on the current runtime: a read of an unchanged reference slot; `Remove` of another entry, which does not move entries; a lost cache write that only causes a recompute (dotnet/runtime `RegexNodeConverter`) |
| PLAUSIBLE | 14 | an effect needs a factory, loader or callback that reaches the same dictionary. That is possible from the code but not demonstrated. 8 of the 14 are generic `GetOrAdd(factory)` helpers whose defect depends on the caller |

Observable defects proven at runtime exist only for the two targets: #412,
[`../next-bug-class-2026-10/data/c_runtime_dictionary.out`](../next-bug-class-2026-10/data/c_runtime_dictionary.out).

## 5. Limitations

- **Symbol resolution.**
  - Each file is compiled alone, with SDK implicit usings and runtime references only.
  - Types from the file's own project or packages are often unresolved.
  - When the arguments do not bind, a single `CollectionsMarshal` candidate is accepted by name. Without this, the
    MAUI target had 0 sites.
  - Unresolved dictionaries and receivers can hide sites and events.
  - The `sites` counts are counts of what resolved, not of what exists.
- **Callee analysis.**
  - Only methods and constructors whose body is in the same file are followed, to depth 4.
  - Only events on a field or property `D` are propagated.
  - Partial classes, base classes, other files, interface and virtual dispatch are not seen.
- **Unknown calls.**
  - Metadata calls are never events, by design (precision-first).
  - A BCL or package call that reaches `D` through a callback is missed.
  - Delegates are treated by reachability alone; an opaque delegate is either flagged (UNCLEAR) or not, never
    analysed.
- **Sample.**
  - GitHub code search returns at most 100 hits per query, over default branches, ranked by GitHub. It is not a
    random sample of C#.
  - The query sets differ between rounds and are biased toward files that name the API.
  - Search results drift, so `scripts/search.sh` will not reproduce the lists; the committed `index.tsv` files are
    the samples.
  - The two target repos and the #412 development sample are excluded; round 2 also excludes round 1.
- **Labelling.**
  - One researcher labelled every warning by reading one file.
  - There was no second labeller and no blind control.
  - Labels are judgements about reachability, not runtime results.
- **Silence is not safety.** A file without a warning is not shown to be free of stale refs. The probe measures
  precision only; recall outside the two targets and the controls was not measured.

## 6. Plausible hazards found (not reported upstream)

- uno.extensions `StateStore` (G8);
- CalcpadCE `MathParser.CustomFunction` (G12, G13);
- dotnet/runtime `RegexNodeConverter` (G11, benign).

They are recorded here as labels only. Nothing was reproduced or reported.

## 7. Post-hoc observation — not evidence, no further work authorised

In both samples, warnings of the exact form `ref = factory(…)` were labelled TP in nearly every case: the ref
written with the result of a delegate, as in Meziantou. The FP and UNCLEAR cases came from other event kinds.

This subset was selected after labelling, on the test data. It was not pre-registered and was not measured on an
unseen sample. It is not a precision claim.

Per the owner ruling, a third round, including a test of this hypothesis, is **not authorised**. No implementation
or measurement of it was made.

## 8. Reproduce

Needs the .NET 8 SDK (or later), Python 3 and an authenticated `gh`.

```bash
sha256sum -c SHA256SUMS
bash scripts/fetch.sh            # samples/ and targets/ by pinned SHA (gitignored)
bash scripts/verify_blobs.sh     # every sample file = its blob SHA (r1 429/429, r2 252/252)
bash scripts/run.sh              # builds v1 and v2, regenerates data/, prints the tally
python scripts/make_index.py ../next-bug-class-2026-10/data/sample-index.tsv --check
```

`run.sh` ends with the two tally lines of §4:

```text
r1: sites=274 warnings=18 files=429 repos=183 TP=9 FP=5 UNCLEAR=4 precision=64% conservative=50% TP repos=6
r2: sites=290 warnings=14 files=252 repos=189 TP=8 FP=3 UNCLEAR=3 precision=73% conservative=57% TP repos=7
```
