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
Infer#'s `PULSE_RESOURCE_LEAK` vs CodeQL's `cs/local-not-disposed` & friends):

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
  build failure still yields a partial report. (For Infer#, the workflow prefers
  the product library — a unique `<repo>.csproj` outside the
  test/benchmark/sample/example trees — over the whole solution, since building
  the solution often drags in test projects that won't build bare; it falls back
  to a single root `*.sln`/`*.slnx`, then a single solution anywhere, then the
  dir. The `build` input overrides. The shallow clone is deepened first, since
  version tools like Nerdbank.GitVersioning need history.)
- **All three are compared on the *product* code by default.** Infer# only builds
  the product project (above), so own-check / CodeQL — which scan the whole source
  tree — would otherwise count test/benchmark leaks the others never saw. The
  comparator drops findings under `test` / `benchmark` / `sample` / `example`
  paths (`--exclude-tests`, the workflow default); set `include_tests` to compare
  across everything. Doing it in the comparator keeps one uniform rule for all
  tools (CodeQL's `paths-ignore` is unreliable for compiled C# with
  `build-mode: none`).
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
        include_tests = false (default: compare product code only; true keeps tests/benchmarks)
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

## What the first Dapper three-way showed (a worked example)

Running all three on Dapper's **product code** (commit `72a54c4`; `--exclude-tests`
dropped 165 test/benchmark findings) gave **Own.NET 0 · Infer# 3 · CodeQL 2**
leak-class, `agree 0`, and **`own-only 0`** (no false positives from us). The five
oracle-only findings are both classes we deliberately don't model — and one of them
is arguably a *precision win for us*:

- **Infer# ×3** — all `WrappedBasicReader` / `DbWrappedReader` in `SqlMapper`
  (`SqlMapper.cs:1952`, `:3294`, `SqlMapper.IDataReader.cs:118`): "resource
  allocated … is not closed." But that wrapper is Dapper's **caller-owned disposal
  handle** — `ExecuteReader*` does `return DbWrappedReader.Create(cmd, reader)`
  (ownership handed to the caller), and the `GetRowParser`/`GetDbDataReader` adapter
  wraps the *caller's own* reader (disposing it would close the caller's reader).
  `WrappedBasicReader.Dispose()` simply forwards to `_reader.Dispose()` — it exists
  precisely so the **holder** disposes it. So these are Infer# **over-reports on the
  returns-`IDisposable` pattern** — exactly the escape / ownership-transfer case
  Own.NET treats as *not a leak*. Our `0` is the right verdict here; Infer#'s `3`
  look like false positives. (Verified against `WrappedReader.cs` and the
  `ExecuteReader` return; the two `SqlMapper.cs` sites match the same direct-return
  and adapter shapes.)
- **CodeQL ×2** — `cs/dispose-not-called-on-throw` at `SqlMapper.cs:1242/1333`: a
  disposable local may leak *only if* an exception is thrown mid-method. We don't
  model exceptional CFG edges, so this is an honest recall gap **by design**, not a
  logic bug.

Caveat: `own-only 0` also reflects **coverage** — Dapper's core is heavily async and
interprocedural, which we under-analyse, so "found nothing" partly means "didn't
reach it." Telling the two apart needs the extractor's `--stats` (analysed vs
skipped) — the missing signal this run made concrete.

Net: the oracle did its job. It turned "are we behind?" into a precise map —
precision held (0 FPs; we look *more* correct than Infer# on ownership transfer),
and the recall gap is two named, roadmapped classes (interprocedural escape
tracking, exception-path disposal).

## Honest gaps (v1)

- **No tool versions pinned in the report yet.** `microsoft/infersharpaction@v1.5`
  and `github/codeql-action@v3` float on tags; the report header names the tools
  but not exact analyser versions. A later pass can stamp them.
- **CodeQL runs the `security-and-quality` suite, filtered in the comparator**
  (rather than a single-query pack). This matters: the dispose/leak queries
  (`cs/local-not-disposed` & friends) are *quality* queries, **absent from the
  default code-scanning (security) suite** — without the suite, CodeQL silently
  contributes zero. The filter keys on the dispose/leak rule family; robust to
  version drift.
- **One target, by hand.** Same discipline as mining: a deliberate spot-check,
  not a crawler. Be a good citizen (shallow, read-only).
- **Agreement is necessary, not sufficient.** Two tools can share a blind spot.
  The oracle raises confidence; it does not prove soundness (that is the Boogie/
  Dafny backend's job, still roadmap).
