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
  ```
  Included frontend:
    .NET / C# (.cs, .csproj, .sln)
  ```
  No plugin framework and no speculative TypeScript mention were added —
  the help text does not claim support that doesn't exist yet.
- **Unsupported input fails explicitly.** Before this rebrand, pointing
  `check` at a `.ts` file or an empty/non-C# directory silently printed
  "0 findings" — indistinguishable from a genuinely clean C# scan.
  `CheckCommand.HasSupportedInput` now checks every given path resolves to
  something the included frontend can read (a `.cs`/`.csproj`/`.sln` file,
  or a directory containing at least one `.cs` file anywhere under it)
  *before* running the extractor, and exits **4** with an explicit message
  if none do. This is a new, additive exit-code tier — it does not change
  any of the existing 0/1/`>=2`/3 contract.
- **`OWEN_PYTHON`** is the preferred env var; the legacy **`OWN_PYTHON`**
  name is still accepted as a temporary compatibility fallback (so existing
  internal use — CI, scripts, muscle memory — doesn't break outright) and
  prints a one-line deprecation note to stderr every time it's the variable
  actually used to resolve Python. `OWEN_PYTHON` takes priority when both
  are set.
- **Cache directory** moved to `~/.owen/core/<version>/`. `CoreVendor` reads
  a plain existence check against the previous `~/.ownsharp/core/<version>/`
  location first — if that exact version was already unpacked there by an
  older install, it's reused in place rather than re-copied. This is a
  fallback read, not a migration subsystem: the old location is never
  written to, moved, or deleted by the new code.

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
