# Oracle comparison — validating the leak check against Infer# and CodeQL

We are **not** the first resource-leak detector for C#. Infer# (Microsoft, on
Facebook Infer) and CodeQL (`cs/local-not-disposed`) are mature, interprocedural,
battle-tested. That is precisely what makes them useful here: run all three over
the **same** repo and diff the leak-class findings. Cross-tool agreement is a
strong correctness signal; disagreement points straight at our precision or
recall gaps. This is evaluation tooling — a companion to corpus mining
([`mining.md`](mining.md)), with an external reference instead of just our own
verdict.

## The three buckets

Restricted to the comparable class — *resource leak / not disposed* (OWN001 vs
Infer#'s `DOTNET_RESOURCE_LEAK` vs CodeQL's `cs/local-not-disposed` & friends):

| bucket | meaning | what to do |
|---|---|---|
| **agree** | a `(file, line)` flagged by Own.NET **and** an oracle | high confidence — nothing, this is the win |
| **own-only** | flagged by us, by no oracle | triage: a candidate **false positive** to harden, *or* a real catch the oracle's leak query can't express |
| **oracle-only** | flagged by an oracle, not by us | our **recall gap** — reduce to a minimal `.cs`, then model it or record it as a known limitation |

Two classes sit **outside** the three-way diff and are reported separately:

- **Own.NET-only defect classes** — `OWN002` (use-after-dispose) and `OWN003`
  (double-dispose). The oracle *leak* queries have no equivalent, so counting
  them as "own-only leaks" would be misleading. They are a feature, not noise.
- **Oracle findings outside our scope** — Infer#'s `NULL_DEREFERENCE`,
  thread-safety, taint, etc. Listed as context (counts by rule), not a gap.

## Why this is a fair-but-honest comparison

- **Own.NET needs no build.** The Roslyn extractor reads a best-effort
  `SemanticModel` without `dotnet restore`/build (unresolved externals become an
  honest `OWN050`, not a guess). **Both oracles need the target to build**:
  CodeQL constructs a database (here via `build-mode: none`, from source), Infer#
  analyses compiled `.dll`+`.pdb`. So the oracle run can fail where ours doesn't
  — that asymmetry is the point, and each oracle step is `continue-on-error` so a
  build failure still yields a partial report.
- **Path/line matching is deliberately loose.** Tools disagree on the exact line
  (allocation site vs declaration) and on path prefixes. The comparator matches
  on **basename + a line window** (`--line-tol`, default 3). Robust to prefixes;
  same-named files in different dirs can theoretically collide (rare — the line
  disambiguates). The file-level overlap is the most robust signal.

## Run it

In CI (no local Infer#/CodeQL/Docker needed) — Actions tab → **oracle
(cross-tool)** → *Run workflow*. The report lands in the run summary and as an
artifact (`report.md`, `report.json`, plus each tool's raw output):

```text
inputs: repo = DapperLib/Dapper   ref = (optional)
        paths = (optional own-check subdir)   build = (optional proj/sln for Infer#)
```

The diff core runs anywhere on already-produced outputs (this is what `--selftest`
exercises, and it gates CI):

```sh
python scripts/oracle_compare.py \
  --own own.txt \
  --infersharp infer-out/report.sarif \
  --codeql codeql-out/csharp.sarif \
  --strip "$PWD/target" \
  --target DapperLib/Dapper --commit "$SHA" --json report.json
```

`--own` is `own-check`'s human output (same format the miner reads). The two
oracle inputs are SARIF — Infer# and CodeQL both emit it, so one parser handles
both. Extra SARIF oracles can be added with `--sarif tool=path`.

## What "agree" buys us, concretely

The first mine of Dapper found **zero** real leaks (a well-disciplined library).
A clean run is a precision signal — but on its own it can't tell "we correctly
found nothing" from "we silently skipped everything". The oracle closes that:

- if the oracles also find ~nothing → genuine agreement, the codebase is clean;
- if the oracles find leaks we missed → **oracle-only**, a concrete recall target
  (likely interprocedural, a field, or a `for`/`do`/`try` shape we honestly skip);
- if we flag something they don't → **own-only**, either a precision bug to fix or
  a defect class (double-dispose) they don't model.

Pair this with the extractor's planned `--stats` coverage (methods analysed vs
skipped) and the picture is complete: how much we looked at, and how our verdicts
line up with two independent engines.

## Honest gaps (v1)

- **No tool versions pinned in the report yet.** `microsoft/infersharpaction@v1.5`
  and `github/codeql-action@v3` float on tags; the report header names the tools
  but not exact analyser versions. A later pass can stamp them.
- **CodeQL runs the default suite, filtered in the comparator** (rather than a
  single-query pack). Simpler and robust to suite/version drift; the filter keys
  on the dispose/leak rule family.
- **One target, by hand.** Same discipline as mining: a deliberate spot-check,
  not a crawler. Be a good citizen (shallow, read-only).
- **Agreement is necessary, not sufficient.** Two tools can share a blind spot.
  The oracle raises confidence; it does not prove soundness (that is the Boogie/
  Dafny backend's job, still roadmap).
