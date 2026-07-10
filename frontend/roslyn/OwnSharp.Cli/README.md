# ownsharp — the single command (alpha gate A, issue #202)

`ownsharp check <path|.sln|.csproj>` wraps the two existing pipeline stages —
the Roslyn extractor (`OwnSharp.Extractor`, P-013) and the Python core
(`ownlang/`) — into **one `dotnet tool install`**. Same pipeline
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
  process (`dotnet exec <bundled>/OwnSharp.Extractor.dll ...`).
- **The core is unmodified**, vendored as loose `*.py` content (see the
  `.csproj`) and unpacked to `~/.ownsharp/core/<version>/` on first run —
  never into the analyzed repo. It runs on the machine's own Python; nothing
  is embedded, compiled, or downloaded.
- **Python resolution**: `OWN_PYTHON` env var (used exactly as given, no
  fallback — an explicit override that fails is a config error, not a
  "keep guessing" case), else `py -3` (Windows) / `python3` (elsewhere),
  version-checked to be `>=3.11`. No Python found → a fast, one-line,
  actionable failure (`winget`/`apt`/`brew`/python.org, per OS) — **never**
  an auto-download.
- **Rejected alternatives** (embedding a CPython runtime, self-contained
  PyInstaller binaries as the default, waiting for the Rust core, porting the
  core to C#) are on the record in the issue; do not re-litigate them here.

## Build & install locally

Not published to nuget.org yet (P-013's Non-goals) — build and install from
source:

```bash
dotnet pack frontend/roslyn/OwnSharp.Cli/OwnSharp.Cli.csproj -c Release -o /tmp/ownsharp-nupkg
dotnet tool install --global OwnSharp.Cli --version 0.1.0 --add-source /tmp/ownsharp-nupkg

ownsharp check MyApp.sln                                    # human output
ownsharp check . --format github --fail-on-finding           # PR annotations, non-zero on a leak
ownsharp check . --format sarif > own.sarif                  # feed github/codeql-action/upload-sarif
```

Uninstall/upgrade: `dotnet tool uninstall --global OwnSharp.Cli`, then reinstall
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

Exit codes (same contract as `own-check.sh`/`.ps1`): the extractor stage's own
exit code propagates on a hard failure there; otherwise `0` clean / `1`
findings (only surfaced when `--fail-on-finding`) / `>=2` a core hard error
(bad facts, a drifted contract) always propagates; `3` is `ownsharp`'s own —
no usable Python was found.

## Guardrails this project honors (no behaviour change, packaging only)

- **No changes to `OwnSharp.Extractor`** — it is referenced, not edited.
- **No changes to `ownlang/`** — vendored byte-identical; "one checker" holds
  literally, since the exact same core source renders every verdict.
- **`scripts/own-check.sh`/`.ps1` and `action.yml` are untouched** and keep
  working exactly as before — this tool is a third surface alongside them, not
  a replacement (P-013 §Scope).

## CI proof

`ownsharp-cli-smoke` in `.github/workflows/ci.yml` (matrix: `ubuntu-latest` +
`windows-latest`) proves, on a clean runner: pack → `dotnet tool install
--global` → `ownsharp check` finds a real leak (`--fail-on-finding` exits 1,
`OWN001` in the output) → the timed install-to-findings window stays under a
regression ceiling → the no-Python path fails fast with the actionable
message. Both platforms matter here specifically, not just "more coverage": a
`dotnet tool` shim is a native apphost on Windows and a shell script on Unix —
genuinely different process-launch mechanics, so ubuntu-only would not have
proven the Windows path.
