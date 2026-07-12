# owen — the single command (alpha gate A, issue #202)

Public facade: **Owen**, package **Owen.Cli**, command **`owen`**. The
project/namespace stay `OwnSharp.Cli` internally — this is a public-facing
rename, not an internal refactor; see
[`docs/notes/owen-public-facade.md`](../../../docs/notes/owen-public-facade.md)
for the full rationale and what did/didn't change.

Owen finds lifetime and resource-contract bugs. It is language-neutral at the
OwnIR/core level; **this distribution currently includes the .NET/C#
frontend only** — `owen check <path|.sln|.csproj>` wraps the two existing
pipeline stages — the Roslyn extractor (`OwnSharp.Extractor`, P-013) and the
Python core (`ownlang/`) — into **one `dotnet tool install`**. Same pipeline
[`scripts/own-check.sh`](../../../scripts/own-check.sh) already chains by
hand; this is that, packaged.

```text
*.cs --[bundled extractor, in a child process]--> facts.json --[vendored core, run on system Python]--> findings
```

## Packaging shape (design decision, [issue #202](https://github.com/PhysShell/Own.NET/issues/202))

- **The extractor is unmodified**, pulled in via `ProjectReference` — its
  build output (dll + `.deps.json`/`.runtimeconfig.json` + Roslyn
  dependencies) rides along in this tool's own pack payload because
  `PackAsTool` packs the full publish closure. `check` invokes it as a child
  process (`dotnet exec <bundled>/ownsharp-extract.dll ...` — the extractor's
  own internal filename, unaffected by the public facade).
- **The core is unmodified**, vendored as loose `*.py` content (see the
  `.csproj`) and unpacked to `~/.owen/core/<version>/` on first run (falling
  back to a previous `~/.ownsharp/core/<version>/` if already unpacked there
  by an older install — a plain reuse, not a migration) — never into the
  analyzed repo. It runs on the machine's own Python; nothing is embedded,
  compiled, or downloaded.
- **Python resolution**: `OWEN_PYTHON` env var (used exactly as given, no
  fallback — an explicit override that fails is a config error, not a
  "keep guessing" case); `OWN_PYTHON` is honored as a temporary, deprecated
  fallback (prints a note to stderr when it's the one actually used); else
  `py -3` (Windows) / `python3` (elsewhere), version-checked to be `>=3.11`.
  No Python found → a fast, one-line, actionable failure
  (`winget`/`apt`/`brew`/python.org, per OS) — **never** an auto-download.
- **Unsupported input fails explicitly**: a path that isn't a `.cs`/`.csproj`/
  `.sln` file and isn't a directory containing any `.cs` file exits 4 with an
  explicit message — never a silent "0 findings" clean scan.
- **Rejected alternatives** (embedding a CPython runtime, self-contained
  PyInstaller binaries as the default, waiting for the Rust core, porting the
  core to C#) are on the record in the issue; do not re-litigate them here.

## Build & install locally

Not published to nuget.org yet (P-013's Non-goals) — build and install from
source:

```bash
dotnet pack frontend/roslyn/OwnSharp.Cli/OwnSharp.Cli.csproj -c Release -o /tmp/owen-nupkg
dotnet tool install --global Owen.Cli --version 0.1.0 --add-source /tmp/owen-nupkg

owen check MyApp.sln                                    # human output
owen check . --format github --fail-on-finding           # PR annotations, non-zero on a leak
owen check . --format sarif > owen.sarif                 # feed github/codeql-action/upload-sarif
```

Uninstall/upgrade: `dotnet tool uninstall --global Owen.Cli`, then reinstall
as above (bump `--version` if you rebuilt with a new `<Version>`).

## Flags (mirror `scripts/own-check.sh` 1:1)

| Flag | Default | |
|---|---|---|
| `--format {human,github,msbuild,sarif}` | `human` | finding surface |
| `--severity {error,warning}` | `error` | how findings are shown |
| `--fail-on-finding` | off | exit with the core's code (1 = findings) instead of always 0 |
| `--emit-facts <path>` | — | also write the intermediate OwnIR facts.json |
| `--legacy` | off | flat name-based local-`IDisposable` detector instead of `--flow-locals` |
| `--stats` | off | print flow-locals coverage to stderr |
| `--body-throw-edges` | off | opt-in: flag body-level (no-`try`) dispose-not-called-on-throw |

Exit codes: `0` clean, `1` findings (only with `--fail-on-finding`), `>=2` a
core hard error (bad facts, a drifted contract), `3` no usable Python found,
`4` no supported input found (nothing matching the included frontend).

## CI proof

`ownsharp-cli-smoke` in `.github/workflows/ci.yml` (matrix: `ubuntu-latest` +
`windows-latest`) proves, on a clean runner: pack → `dotnet tool install
--global` → `owen --help`/`--version`/unknown-command → `owen check` finds a
real leak (`--fail-on-finding` exits 1, `OWN001` in the output) and stays
silent on clean code (exit 0) → the SARIF surface carries the `Owen` driver
name → unsupported input fails explicitly (exit 4, never a clean scan) →
`OWEN_PYTHON` (and the deprecated `OWN_PYTHON` fallback, with its
deprecation note) both resolve Python correctly → the no-Python path fails
fast with an actionable message → the timed install-to-findings window stays
under a regression ceiling. Both platforms matter here specifically, not
just "more coverage": a `dotnet tool` shim is a native apphost on Windows and
a shell script on Unix — genuinely different process-launch mechanics, so
ubuntu-only would not have proven the Windows path.
