# The unified path: Roslyn + CodeQL + Infer# through one interface

The question this answers: *"will it be convenient to run all of this — Roslyn,
CodeQL, Infer# — through a single interface?"*

Yes — but the single interface is the **SARIF contract**, and the adapter layer
is how every tool *reaches* it. There are two planes; only one is (and should
be) unified.

## Plane 1 — invocation (NOT uniform, modelled as phases)

Each tool runs differently and pretending otherwise is a lie the driver
shouldn't tell:

| tool | phases | native output |
|---|---|---|
| Roslyn | `analyze` (`dotnet build /errorlog`) | SARIF |
| CodeQL | `db-build` → `analyze` | SARIF |
| Infer# | `analyze` (build-free) | `report.json` |

`adapters.toml` captures this per tool: `phases`, `platform`, `build_free`,
`output.kind`, and which `adapter` component normalizes it.

## Plane 2 — normalization + everything after (fully uniform)

Every tool converges on **validated SARIF**, then scoring/dedup/report are
tool-agnostic. The adapter is the on-ramp:

```text
Roslyn   ─analyze──▶ roslyn.sarif   ─▶ passthrough.wasm ─┐
CodeQL   ─db,analyze▶ codeql.sarif  ─▶ passthrough.wasm ─┼─▶ own-adapter-host
Infer#   ─analyze──▶ report.json    ─▶ infersharp.wasm  ─┘   (validate + cap +
                                                              sha256 stamp)
                                                                    │
                                                          validated SARIF
                                                                    │
                                                     parse_sarif ─▶ score ─▶ report
```

**Native-SARIF tools go through a component too** (passthrough), so *all three*
take the identical path: sandboxed parse of untrusted-derived output, uniform
validation, uniform provenance stamp. No "SARIF tools here, non-SARIF there"
split. The host binary is unchanged and tool-agnostic — only the `--component`
differs.

## What the orchestrator loop looks like (in `aggregate`)

```python
# pseudocode — the shape aggregate grows into; not committed here
cfg = toml.load("adapters.toml")
for tool_id, t in cfg["tools"].items():
    if not platform_ok(t.get("platform", "any")):
        record(f"NO-TOOL: {tool_id} skipped (platform)"); continue

    for phase in t["phases"]:                       # honest: CodeQL runs 2, others 1
        run(expand(phase["cmd"], run_vars))

    artifact = expand(t["output"]["artifact"], run_vars)
    sarif = subprocess.check_output([              # one call, same for every tool
        "own-adapter-host",
        "--component", t["adapter"],
        "--tool", tool_id,
        "--artifact", f"report={artifact}",
        "--base-uri", run_vars["base_uri"],
        "--max-results", str(cfg["defaults"]["max_results"]),
    ])                                             # -> validated, stamped SARIF
    parse_sarif(sarif)                             # existing downstream, unchanged
```

That is the "single interface" you run everything through: **one loop, one
`own-adapter-host` call per tool, one SARIF contract.** Invocation heterogeneity
lives in data (`phases`), not in branching code — and CodeQL's two-phase nature
is visible, not hidden.

## What this spike ships toward it

- `components/passthrough/` — the SARIF→validated-SARIF component (Roslyn, CodeQL).
- `components/infersharp/` — the real transform (Infer#).
- `adapters.toml` — the control surface with run recipes + phases.
- The loop above is the remaining wiring in `aggregate` (not in this spike — it
  shells out to real tools, which can't run in the authoring sandbox).
