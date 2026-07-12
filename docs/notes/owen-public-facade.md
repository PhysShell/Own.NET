# Owen: public facade rebrand

This note records a **public-facing rebrand**, not an internal refactor. The
underlying engine, project names, namespaces, and diagnostic codes are all
unchanged; only what an external user *sees* — the package name, the CLI
command, help/error text, the SARIF tool identity, the cache directory, and
the Action's display name — changed to the public identity **Owen**.

## Why

The project is language-neutral at the OwnIR/core level (`ownlang/` takes
facts from any frontend that can produce them) and may eventually ship a
TypeScript frontend alongside the current C# one. Publishing the first real
package under a C#-specific name (`OwnSharp.Cli`, command `ownsharp`) would
have locked the public identity to a single-language framing the project
doesn't actually have. **Owen** is the product name; **this distribution
currently includes the .NET/C# frontend only** — that framing is stated
explicitly in the CLI's own `--help` output rather than left implicit.

## Public identity implemented

| Surface | Old | New |
|---|---|---|
| Product | (unnamed / "Own.NET" informally) | **Owen** |
| NuGet package ID | `OwnSharp.Cli` | **`Owen.Cli`** (confirmed unclaimed on nuget.org at time of writing — both `owen` and `owen.cli` returned 404 from the v3 flat-container API; still worth a final check immediately before an actual publish, since availability can change) |
| Tool command | `ownsharp` | **`owen`** |
| Action display name | `Own.NET resource-leak check` | **`Owen lifetime/resource check`** |
| SARIF `tool.driver.name` | `Own.NET` | **`Owen`** |
| Cache directory | `~/.ownsharp/core/<version>/` | **`~/.owen/core/<version>/`** |
| Preferred Python env var | `OWN_PYTHON` | **`OWEN_PYTHON`** (`OWN_PYTHON` still works, deprecated) |
| Default Action SARIF filename | `own-net.sarif` | **`owen.sarif`** |

## What deliberately did NOT change (internal names)

Per the guardrail this rebrand was scoped to: no mass rename.

- The `OwnSharp.Cli` **project and namespace** — still `OwnSharp.Cli` in the
  `.csproj`, C# namespace, and `.sln`. Only `PackageId` and
  `ToolCommandName` (the two properties that actually control the public
  package/command identity) changed.
- `AssemblyName` in `OwnSharp.Cli.csproj` stays `ownsharp` — it names the
  internal `.dll` the `owen` shim launches, never typed or seen by a user,
  so renaming it would add no user value (the csproj comment says so
  explicitly, next to `ToolCommandName`).
- **`OwnSharp.Extractor`** (project, namespace, and its real output filename
  `ownsharp-extract.dll`) — completely untouched. `CheckCommand.cs`
  references that literal filename because it is the actual file that ships,
  not a stale pre-rebrand reference.
- **`ownlang`** — the Python package name, its module names, its CLI
  (`python -m ownlang ...`), and its `PYTHONPATH`/working-directory
  conventions are all unchanged. Only the `"name"` string value inside the
  SARIF `tool.driver` object (in `ownlang/ownir.py` and
  `ownlang/diag_sarif.py`) changed from the literal `"Own.NET"` to `"Owen"`
  — a metadata string, not a rename of anything importable.
- **`OwnIR`**, **`OWN001`** and every other diagnostic code, the Rust crates
  under `rust/`, every `frontend/*` directory name, and all historical
  docs/issues — untouched. This note does not retroactively edit history;
  older notes that say "Own.NET" or "ownsharp" describe what was true when
  they were written.
- `scripts/own-check.sh`/`.ps1` and `action.yml`'s internal call to
  `scripts/own-check.sh` — unchanged. The Action's public *display name* and
  *default SARIF filename* changed; what it runs under the hood did not.
- The GitHub repository itself (`PhysShell/Own.NET`) — not renamed in this
  PR. `_SARIF_INFO_URI` in `ownlang/ownir.py`/`diag_sarif.py` still points at
  `https://github.com/PhysShell/Own.NET`, which remains accurate.
- `audit/` and `scripts/{oracle_compare,mine_report}.py` still construct
  synthetic test fixtures with a literal `"Own.NET"` driver name in a few
  places. These are **test input fixtures** for those tools' own aggregation/
  comparison logic (arbitrary strings a fixture author chose), not assertions
  about Owen's real emitted SARIF — `audit/` is explicitly documented
  (`audit/README.md`, `AGENTS.md`) as decoupled from `ownlang` and consuming
  `own-check` only through its CLI/SARIF surface, with active development
  living in a separate repo. Left alone to avoid scope creep into a module
  this PR has no reason to touch.

## CLI contract additions

- **`owen check <path>`** is the public invocation. `--help` is
  language-neutral at the product level ("Owen finds lifetime and
  resource-contract bugs") while explicitly listing what this distribution
  actually wires up today:
  ```text
  Included frontend:
    .NET / C# (.cs, .csproj, .sln)
  ```
  No plugin framework and no speculative TypeScript mention were added —
  the help text does not claim support that doesn't exist yet.
- **Unsupported input fails explicitly.** Before this rebrand, pointing
  `check` at a `.ts` file or an empty/non-C# directory silently printed
  "0 findings" — indistinguishable from a genuinely clean C# scan. The
  explicit-failure behavior now has two layers, split across the two
  components that each know a different half of the answer (review, PR
  #246 round 2): `CheckCommand.HasSupportedInput` does only the CHEAP,
  obvious check — an existing file with a recognized extension, or an
  existing directory — *before* running the extractor at all, catching a
  bare `.ts` file or a nonexistent path for free. `SupportedExtensions` is
  compared with `StringComparer.OrdinalIgnoreCase` (review, PR #246 round
  2: `Foo.CS`/`App.CSPROJ` are the same file kind as their lowercase
  spellings, on Windows/macOS filesystems and to MSBuild itself). The CLI
  does **not** also try to duplicate the extractor's directory-walk skip
  rules to predict whether a directory will actually yield anything — a
  directory containing only `bin/`, `obj/`, or generated (`.g.cs`,
  `.Designer.cs`, `.AssemblyInfo.cs`) files passed the CLI's cheap check
  fine but produced zero real extractor inputs, recreating the exact
  silent-clean-scan bug this exit tier exists to prevent. Duplicating the
  extractor's skip-list in the CLI would just drift from it over time
  (review, PR #246 round 2 explicit instruction: "do not duplicate the
  complete extractor expansion rules in the CLI"). Instead, the extractor
  itself is now the sole authority on "found nothing after expansion":
  `OwnSharp.Extractor/Program.cs` checks `Expand(rawInputs).Distinct()`
  immediately after computing it and returns a new exit code **4** with an
  explicit message if that list is empty — a `.csproj`/`.sln` with no
  usable source resolves the same way, since project/solution resolution
  is text/glob-based, not full MSBuild evaluation (see the `ProjectCsFiles`
  comment). `CheckCommand.RunAsync`'s existing `extractRc != 0` early
  return propagates that 4 unchanged, and `own-check.sh`'s existing `set
  -e` does the same for the script/Action path — no extra code needed on
  either side beyond the extractor's own check. This is a new, additive
  exit-code tier; it does not change any of the existing 0/1/`>=2`/3
  contract.
- **`OWEN_PYTHON`** is the preferred env var; the legacy **`OWN_PYTHON`**
  name is still accepted as a temporary compatibility fallback (so existing
  internal use — CI, scripts, muscle memory — doesn't break outright) and
  prints a one-line deprecation note to stderr every time it's the variable
  actually used to resolve Python. `OWEN_PYTHON` takes priority when both
  are set.
- **Cache directory** moved to `~/.owen/core/<version>/<fingerprint>/`,
  where `fingerprint` is a SHA-256 over every vendored file's name and
  content (length-prefixed encoding, so e.g. name `"ab"` + content `"c"`
  can't collide with name `"a"` + content `"bc"` by bare concatenation).
  **Correction (review, PR #246 round 3):** the round-2 design (a
  version-keyed directory with a separate marker file holding a source
  fingerprint) had a gap the reviewer's reproduction demonstrated directly:
  on a fingerprint mismatch, the fix copied new files over the existing
  destination with `overwrite: true`, then rewrote the marker to match the
  new source — but a file the new source no longer has (e.g. a module
  deleted upstream) was never removed from the destination, so it survived
  as an orphan while the rewritten marker now claimed the (polluted)
  directory was valid. Round 3 removes the marker concept entirely and
  makes cache identity content-addressed: the fingerprint *is* the last
  path segment, so a content change is a different path, never an
  in-place overwrite of an existing one. Publication into a fresh path is
  atomic — build into a `.tmp-<guid>` sibling directory, recompute the
  fingerprint of what was actually written there, confirm it equals the
  source fingerprint, and only then `Directory.Move` it to the final
  fingerprint-named path — so a reader can only ever observe nothing, or a
  fully-written self-verified copy, never a partial one (a crash or a lost
  race with a concurrent `owen` process mid-copy just leaves a harmless
  orphaned temp directory that nothing consults). The previous flat
  `~/.ownsharp/core/<version>/` location (pre-rebrand layout, no
  fingerprint segment) is still checked first and used in place without
  copying — but only after fingerprinting what is *actually on disk* there
  right now and confirming it equals the current source fingerprint; a
  destination with extra, missing, or modified files fails that check and
  falls through to a fresh unpack instead of being trusted or patched.
  This is still a plain fallback *read*: the legacy location is never
  written to, moved, or deleted by this code — content-addressing didn't
  change that guardrail, only how "is this destination actually still
  correct" gets decided.

## Tests

`ci.yml`'s `ownsharp-cli-smoke` job (job key kept as-is; only its *content*
changed — renaming the key isn't part of the public facade and would just
add unrelated churn) now pins, on both `ubuntu-latest` and `windows-latest`:
package ID (`Owen.Cli`), command name (`owen`), `--help` (Owen framing +
explicit included-frontend list + no TypeScript claim), `--version`,
unknown-command prefix (`owen:`), a leak sample and a clean negative control
both run from an installed, checkout-free location, the `Owen` SARIF driver
name, the exit-4 unsupported-input path (explicitly asserting the output
does **not** contain the literal clean-scan phrase `0 findings.`),
`OWEN_PYTHON`'s not-found path, and the legacy `OWN_PYTHON` fallback
(resolved successfully + its deprecation note). Two other pre-existing
`ci.yml` assertions that pinned the literal SARIF driver-name string
(`own-check-codescan`'s local structural-validation job, and
`tests/test_diag_sarif.py`/`tests/test_ownir.py`) were updated from
`"Own.NET"` to `"Owen"` to match — these are follow-on fixes made necessary
by the driver-name change, not scope creep; they were caught by
`python tests/run_tests.py` failing before the fix.

**Added in review round 3** — the reviewer's stated concern was that both
bugs (stale-cache pollution, cheap-preflight/extractor disagreement) were
"sufficiently non-obvious that a future cleanup could reintroduce [them]
while the ordinary fresh-install smoke remains green," so both
reproductions from the review became committed `ci.yml` steps rather than
staying local manual verification. All of the below ran locally first
(pack -> isolated-feed install -> exercise -> confirm exit code/output)
before being encoded as assertions:
- **Matching legacy cache is reused in place** — the legitimate case: a
  byte-for-byte-identical legacy `~/.ownsharp/...` unpack is used without
  copying (`~/.owen` is asserted to *not* get created).
- **Extra (removed-upstream) file in the legacy cache is rejected** — the
  exact reproduction from the review: an old cache holds a file the new
  source no longer has. A fresh, clean `~/.owen` unpack must result, with
  the stale file absent from it.
- **Modified-content legacy cache (same filenames, different bytes) is
  rejected** — same version, same file set, different content: the
  same-version class of bug the fingerprint exists to catch generally, not
  just the removed-file case.
- **Directory containing only skipped files** (`bin/`/`obj/`) and
  **directory containing only generated files** (`*.g.cs`) both assert
  exit 4 with an explicit "no supported input" message — the CLI's cheap
  preflight passes these (a directory that exists), and only the
  extractor's own zero-expanded-input check catches them.
- **Empty `.csproj`** (no `Compile` items resolve to any `.cs` file) and
  **`.sln` with no `Project(` lines** both assert exit 4 the same way.
- **Skipped files alongside one real source file** asserts exit 1 with
  `OWN001` still found — proving the skip rules don't over-reject a
  directory that has genuine content alongside the noise.
- **An inaccessible subtree alongside one readable source file** (`chmod
  000` on a subdirectory, meaningful on the hosted runners' non-root
  accounts unlike this session's root-based local sandbox) asserts no
  crash and the readable source's finding is still reported — the
  `EnumerationOptions { IgnoreInaccessible = true }` tolerance from review
  round 2, now with a real permission-denied subdirectory to exercise it.
- **Uppercase extension (`Leak.CS`)** asserts exit 1 with `OWN001` found —
  the `StringComparer.OrdinalIgnoreCase` fix from review round 3.

## PR separation

This is PR 1 of 3 for the release-readiness work:

1. **This PR** — the public facade rebrand (Owen identity, no publish).
2. Phase 3 (NuGet release/package pipeline) — rebuilt against this PR once
   merged, targeting `Owen.Cli`/`owen` instead of the pre-rebrand
   `OwnSharp.Cli`/`ownsharp` identity its first draft (PR #244) used.
3. Phase 4 (GitHub Marketplace preparation) — rebuilt against this PR once
   merged, targeting the `Owen lifetime/resource check` display name instead
   of the pre-rebrand name its first draft (PR #245) used.

No oracle remeasurement and no analyzer-semantics change are mixed into this
PR — the extractor, the core's detection logic, and every diagnostic
verdict are byte-for-byte unchanged; `python tests/run_tests.py`, `ruff`,
and `mypy` all stay green throughout.
