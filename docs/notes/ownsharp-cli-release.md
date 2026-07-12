# OwnSharp.Cli release readiness (P-013 / issue #202, alpha gate A)

This note is the release-process companion to
[`frontend/roslyn/OwnSharp.Cli/README.md`](../../frontend/roslyn/OwnSharp.Cli/README.md)
(which documents the packaging *shape*). This one documents *how a release
happens*: versioning, the pipeline, what was verified, and the checklist for
whoever actually runs a release. No production package has been published as
part of writing this note — see "Boundaries" at the end.

## Versioning policy

**Single source of truth: `<Version>` in
`frontend/roslyn/OwnSharp.Cli/OwnSharp.Cli.csproj`.** Nothing else computes
or infers a version — no `Directory.Build.props` version, no
`Nerdbank.GitVersioning`, no build-number suffix. `ownsharp --version`
reads it directly (`ToolVersion.cs`, via the assembly's own version, which
MSBuild derives from this `<Version>`).

- **SemVer, pre-1.0 during alpha.** `0.1.0` today. Per alpha-gate discipline
  already in `docs/notes/alpha-readiness.md`, a `0.x` version carries no
  backward-compatibility promise — this note does not invent one beyond what
  the repo already signals.
- **Tag format: `ownsharp-cli-vMAJOR.MINOR.PATCH`** (prefixed, not a bare
  `vX.Y.Z` — this repo may eventually version other release surfaces, e.g.
  the GitHub Action in Phase 4, under the same tag namespace, and a shared
  bare `v*` would collide).
- **The release workflow (`ownsharp-cli-release.yml`) enforces the tag
  matches the csproj `<Version>` byte-for-byte** before it will pack for
  publish — a mismatch fails the build loudly instead of silently shipping
  the wrong version under either name. Bump `<Version>` in a normal PR
  first, merge, *then* tag `main` at that commit.
- No auto-bump, no floating `-preview`/`-ci` suffixes on release builds.
  (CI-only smoke packs in `ci.yml`'s `ownsharp-cli-smoke` job use the
  as-committed `<Version>` too — there is exactly one version number in
  play at any time, never a synthetic CI-only one.)

## Deterministic `dotnet pack` — verified locally

Added `<Deterministic>true</Deterministic>` and
`<ContinuousIntegrationBuild Condition="'$(GITHUB_ACTIONS)' == 'true'">true</ContinuousIntegrationBuild>`
to the csproj. Verified locally (`dotnet 8.0.422`, this repo's exact source,
`main` + this change): ran `dotnet pack` twice back-to-back into separate
output directories and diffed the unzipped contents.

**Result:** every payload file — `tools/net8.0/any/ownsharp.dll` (the CLI
itself), `tools/net8.0/any/ownsharp-extract.dll` (the bundled extractor),
every bundled `Microsoft.CodeAnalysis*.dll` and satellite resource
assembly, and all vendored `ownlang-core/ownlang/*.py` files — is
**byte-for-byte identical** between the two packs (verified with
`sha256sum` per file, not just eyeballed).

The only files that differ between the two `.nupkg`s are NuGet's own OPC
package-wrapper metadata: `_rels/.rels` and
`package/services/metadata/core-properties/<random-guid>.psmdcp`. This is
`dotnet pack`/NuGet.Client's own packaging step minting a fresh internal
GUID on every invocation — a property of the `.nupkg` container format
itself, not something `Deterministic`/`ContinuousIntegrationBuild` (which
govern the C# compiler's PE output) can or should suppress. **"Deterministic
pack" in this project means the payload is reproducible from source, not
that the outer `.nupkg` zip is byte-identical** — that distinction is worth
keeping precise, since the latter is not an achievable or meaningful goal
for any `dotnet pack`-produced package.

## Package metadata — audited

Added to the csproj: `Authors`, `PackageProjectUrl`, `RepositoryUrl`,
`RepositoryType`, `PackageTags`, `PackageReadmeFile` (packs the existing
`OwnSharp.Cli/README.md` into the package root). `PackageId` (`OwnSharp.Cli`)
and `Description` were already present and accurate.

**Unresolved blocker: no license.** The repository has no `LICENSE` file
(checked: repo root, and no license section in the root `README.md`).
`PackageLicenseExpression`/`PackageLicenseFile` are deliberately **not**
set — guessing a license is not this note's call to make (repository
convention: "do not choose public compatibility promises beyond what the
repository already supports"). `dotnet pack` does not currently hard-fail
without one, but NuGet.org's own publish UI does require a license
declaration (or an explicit "none" acknowledgment) before an *actual*
publish — **a maintainer must pick a license and add
`PackageLicenseExpression` (or a `LICENSE` file +
`PackageLicenseFile`) before this package can really ship.** Tracked as
the first item in the checklist below.

## Release pipeline — `.github/workflows/ownsharp-cli-release.yml`

Three jobs, each gated on the previous succeeding:

1. **`build-test-pack`** (always runs, on a push of an `ownsharp-cli-v*` tag
   or a manual `workflow_dispatch`) — the standard repo gates
   (`run_tests.py`, `ruff`, `mypy`), `dotnet build`, the tag/version-match
   assertion above (skipped on manual dispatch, since there's no tag),
   `dotnet pack`, then **inspects the packed `.nupkg` contents** and fails
   if the bundled extractor DLL or the vendored `ownlang-core/*.py` files
   are missing (catches a packaging regression before it ever reaches a
   consumer). Uploads the `.nupkg` as a build artifact.
2. **`smoke-test`** (matrix: `ubuntu-latest` + `windows-latest`) —
   downloads *only* the artifact from step 1 (no checkout of this repo at
   all on this job), `dotnet tool install --global` from that local feed,
   and runs the installed `ownsharp` command from a scratch directory with
   no Own.NET source anywhere on the runner. This satisfies the **critical
   test rule**: the smoke test executes the installed `.nupkg`, never a
   `ProjectReference` or `dotnet run` — a test that accidentally ran the
   source checkout would prove only that the source compiles, not that the
   package works for an end user. Verifies: `ownsharp --version` reports
   the released version; `ownsharp check` on a seeded leak sample exits `1`
   with `OWN001` in the output; `ownsharp check` on clean code exits `0`;
   `OWN_PYTHON` pointed at a nonexistent interpreter fails fast with exit
   `3` and an actionable per-OS hint (never an auto-download); and a full
   **uninstall → reinstall** cycle reproduces a working install (reinstall
   is the same code path an upgrade takes).
3. **`publish`** — `if: startsWith(github.ref, 'refs/tags/ownsharp-cli-v')`,
   so a `workflow_dispatch` run (no matching tag ref) can never reach this
   job no matter what inputs are given. Additionally targets the
   `nuget-release` GitHub Environment — **a repo admin must configure that
   environment with required reviewers under Settings → Environments before
   this job can run unattended; it does not exist yet.** Reads
   `secrets.NUGET_API_KEY` only as a `dotnet nuget push --api-key` argument
   (never `echo`ed; GitHub Actions also redacts any registered secret value
   that appears in a log line as defense in depth).

`ci.yml`'s existing `ownsharp-cli-smoke` job is untouched and keeps proving
the packaging shape on every push/PR (fast feedback); this workflow is the
release-specific path (slower, gated, gives the "did the *actual release
artifact* survive a clean install on both OSes" answer right before
publish).

## Release checklist

Run through this, in order, for every release:

1. **License.** Confirm `PackageLicenseExpression`/`PackageLicenseFile` is
   set in the csproj (see "Unresolved blocker" above) — do not proceed
   without one.
2. **Version bump.** Bump `<Version>` in `OwnSharp.Cli.csproj` in its own PR;
   merge to `main`.
3. **Package inspection.** Trigger `ownsharp-cli-release.yml` via
   `workflow_dispatch` first (no tag yet) — confirms `build-test-pack`'s
   content-inspection step and both `smoke-test` legs pass *before* a real
   tag exists. Download the `ownsharp-cli-nupkg` artifact and manually spot
   check `dotnet nuget verify` / the `.nuspec` metadata if this is the
   first release or metadata changed.
4. **Install test (both OSes).** Confirmed by the `smoke-test` matrix job
   above — do not skip re-running it right before tagging if any code
   changed since the last `workflow_dispatch` run.
5. **Version check.** Tag `main` at the merged bump commit:
   `git tag ownsharp-cli-v<X.Y.Z> && git push origin ownsharp-cli-v<X.Y.Z>`.
   The pushed tag re-triggers the full pipeline; `build-test-pack`'s
   tag/version-match assertion is the automated form of this check.
6. **Publish.** The `publish` job pauses on the `nuget-release` environment
   gate — a maintainer with repo admin rights approves it manually in the
   Actions UI. This is the one step this note's author (an agent session)
   is explicitly barred from performing or automating past — see
   "Boundaries".
7. **Post-publish smoke test.** *After* a real publish, install from the
   **real** feed on a clean machine — `dotnet tool install --global
   OwnSharp.Cli` with no `--add-source` at all (default nuget.org source) —
   and rerun the same `ownsharp check` smoke scenario as step 4. This is
   the one check nothing in CI can do ahead of time, since it depends on
   nuget.org actually serving the package after indexing (which is not
   instantaneous).

## Boundaries honored in this work

- No package was published to nuget.org.
- No personal API key was requested, stored, or referenced by value —
  the workflow reads `secrets.NUGET_API_KEY` as a repository secret name
  only; nothing about its value is known to or handled outside GitHub's
  own secret store.
- No public compatibility promise was chosen beyond what the repo already
  states (`0.x`, alpha gate A) — no `1.0` claim, no support-window promise.
- No analyzer semantics changed — every change in this batch is packaging
  metadata, build-determinism properties, or CI/release workflow YAML.
- No runtime dependency was bundled or silently introduced — the CLI still
  bundles only the unmodified extractor + vendored core exactly as
  `frontend/roslyn/OwnSharp.Cli/README.md` already documented; this work
  only adds inspection *of* that existing bundle, not new bundled content.
