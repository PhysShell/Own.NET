# Owen diagnostics: the model already exists (OX-01, P8)

**Question.** Is the renderer so tied to CLI strings that the extension substrate needs a new
internal diagnostic model before `msbuild`, `github`, `sarif`, a future Visual Studio host or a
future LSP can be served?

**Answer: no.** The model exists, it is the authoritative core's, and every surface is
already one function of it. OX-01 adds **no** diagnostic layer. It consumes the existing one.

## The model

`own_bridge::verdict::Finding` (Rust, authoritative since the P-022 Stage 3 cutover; the Python
reference mirrors it field for field):

| field | the brief's concept |
|---|---|
| `code` | code (`OWN001` …) |
| `severity` (+ `advisory`) | severity. The host's `--severity` changes only how a finding is **shown**, never the verdict |
| `message` | message |
| `file`, `line`, `column` (optional) | file, start line, start column |
| `related: Vec<Step>`, `flow: Vec<Step>` | related locations and the witness path |
| `kind` (`[resource: …]`), `component`, `event`, `handler` | the resource the finding is about |
| `ignore_reason` | suppression (`// own:ignore` …) |

**Renderers,** each a pure function of a `Finding`:

| function | output |
|---|---|
| `own_bridge::render_finding(f, "human" \| "github" \| "msbuild", severity)` | one line per surface |
| `own_bridge::build_sarif` | a SARIF 2.1.0 log |

`own-cli ownir --format {human,github,msbuild,sarif}` exposes all four. `BR-V9` pins the
bytes, and the CLI ledgers pin both engines.

## How OX-01 uses it

The build host (`owen build-check`) asks the core for `--format msbuild` and passes the lines
through. It changes exactly one thing: it makes the **origin path** absolute against the project
directory, so Visual Studio's Error List never has to guess a base. No message, code or
severity is re-rendered by the host.

The host's own conditions are the `OWENB` codes (spec/OwenExtension.md §4):
- a descriptor rejected;
- no engine for the platform;
- a refusal.

They are rendered by the host in the same canonical MSBuild shape. They are host
diagnostics, not analysis findings, and they never reuse an `OWN` code.

## Gaps, recorded and not changed here

- **No column on the `msbuild` line.** `render_msbuild` prints `file(line)` although `Finding` carries an optional `column`.
  - **Effect:** the Error List navigates to the line, not the column.
  - **Why not here:** changing the line is a change to the core's pinned bytes (BR-V9, the CLI ledgers), which is foundation work.
- **The line and the wording of state-protocol findings.** A stale state token is reported at the region entry, and in the generic resource wording ("IDisposable local … disposed"). This is issue **#393**, unchanged here.
- **For a future IDE host or LSP:** both consume the same `Finding`. `--format sarif` already carries everything they need: code, level, message, region, related locations, code flows. A future `Owen.VisualStudio` or language server should read SARIF, or a structured JSON of the same `Finding`, from the one core, and never re-derive a finding.
