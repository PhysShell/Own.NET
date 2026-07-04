# `audit/adapters/` — SARIF adapters as sandboxed WASM components

**Status: spike.** The audit pipeline runs many ready-made analyzers and
normalizes each to SARIF. Some tools don't speak SARIF, so their output goes
through a **thin `raw -> SARIF` adapter** (see `Own.NET/Plan.md`). This is the
first slice of running those adapters as **capability-scoped WebAssembly
components** (`ownaudit:adapter` WIT world) instead of in-process code.

> This is the real, useful home the parked "Sandboy WIT plugin surface" idea
> found (see `docs/notes/sandboy-isolation-adr.md` §0 PARK / §6 trigger-table):
> not "rules in any language", but **containing parsers of untrusted input**.

## Why WASM/WIT here is the right tool, not a bolt-on

An adapter parses **tool output derived from the audited (untrusted, legacy)
code**. A bug in that parser is code execution *inside the orchestrator* — and
`007/docs/verification.md` already flags these parsers as the #1 fuzz target.
Running each adapter as a WASM component changes what a parser bug can do:

1. **Pure compute → zero capability leak.** An adapter is `bytes -> SARIF`. It
   needs no filesystem, no network, no clock. The world has **zero imports**,
   so the component *cannot* reach any of them. This is the rare tool-plugin
   with no legitimate need for native authority — the objection that sinks
   general agent-tool sandboxing ("tools need real caps") simply doesn't apply.
2. **Untrusted input → the boundary is real even at N=1.** You don't need a
   third-party plugin market to justify the sandbox; the *input* is the threat.
   A crafted `report.json` can at worst make the component **trap** — it cannot
   corrupt the run or touch the host.
3. **Polyglot + portable.** Write an adapter in Rust/Go/Python, ship one
   `.wasm`, run it regardless of host language — unifying today's
   Python-aggregate / C#-skeleton / PowerShell-runner mix behind one ABI.
4. **Hot-load.** New analyzer → drop a `.wasm` in, register it in
   `adapters.toml`, no orchestrator rebuild.

## What the sandbox does and does NOT buy you

| Buys | Does **not** buy |
|---|---|
| Memory-safety faults of the parser are contained (trap, not host compromise) | Semantic correctness of the output |
| Determinism (no clock/rand/IO ⇒ same input → same SARIF) | Trust in the returned bytes |

Because the **output is not trusted either**, the host schema-checks and
size-caps the returned SARIF *before* anything downstream (`parse_sarif`) sees
it. The WASM boundary contains the parse crash; the host validates the meaning.

## Layout

```
adapters/
  wit/world.wit                     canonical ownaudit:adapter@0.1.0 world
  host/                             own-adapter-host (Rust, wasmtime component model)
  components/infersharp/            first ported adapter: Infer# report.json -> SARIF
  adapters.toml                     tool id -> component + caps
  tests/infersharp/                 sample report.json + adversarial input
  BUILD.md                          how to build & run (authored, not built in-repo)
```

## Where it plugs into the pipeline

```
tool runs ──▶ host reads stdout/files ──▶ own-adapter-host ──▶ .wasm adapter
                                                │
                                       SARIF bytes back
                                                │
                              host: validate + cap + stamp sha256
                                                │
                                     parse_sarif ──▶ normalize ──▶ score
```

`own-adapter-host` is a standalone binary `aggregate` calls per tool (raw in →
SARIF on stdout), so Python never links wasmtime and the whole thing folds into
the Rust core cleanly when P-022 lands.

**Provenance:** the host stamps the component's `sha256` into each SARIF
`run.properties.adapterComponentSha256`, so a finding is traceable to the exact
adapter build that produced it — reproducible and auditable, in the
evidence/provenance style of the rest of the repo.

See `BUILD.md` to build and run the spike.
