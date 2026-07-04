# Building & running the adapter spike

> **Authored, not compiled here.** This spike was written in a network-restricted
> sandbox with no wasm target and no crate downloads (`static.crates.io` egress
> was policy-blocked), so it has **not** been run through `cargo`. Treat the
> wasmtime/cargo-component API calls as "correct against the documented API,
> version pins may need a nudge" — the two most likely spots are flagged as
> **§bindings** and **§versioning** below. Everything compiles in a normal
> environment with the toolchain in step 1.

## 1. Toolchain (one time)

```bash
rustup target add wasm32-wasip2          # component target
cargo install cargo-component            # builds WIT components
cargo install wasm-tools                 # inspect/validate components (optional)
```

## 2. Build the adapter components

```bash
# real transform (Infer#)
(cd components/infersharp && cargo component build --release \
  && cp target/wasm32-wasip2/release/adapter_infersharp.wasm ../infersharp.wasm)

# passthrough (Roslyn, CodeQL — validate + normalize already-SARIF output)
(cd components/passthrough && cargo component build --release \
  && cp target/wasm32-wasip2/release/adapter_passthrough.wasm ../passthrough.wasm)
```

## 3. Build the host

```bash
cd ../../host
cargo build --release
# -> target/release/own-adapter-host
```

## 4. Run it — happy path

```bash
cd ..
./host/target/release/own-adapter-host \
  --component components/infersharp.wasm \
  --tool infersharp \
  --artifact report.json=tests/infersharp/report.json \
  --base-uri 'file:///repo/sts' \
  --exit-code 0 \
  | python -m json.tool
```

Expect a SARIF 2.1.0 document: one run, `tool.driver.name = "Infer#"`, two
distinct rules (`NULL_DEREFERENCE`, `RESOURCE_LEAK`), three results with
`level` mapped from severity, `region` line/column, logical locations from
`procedure`, `inferHash/v1` fingerprints, and a
`runs[0].properties.adapterComponentSha256` provenance stamp.

## 5. Run it — the point of the exercise (adversarial)

```bash
./host/target/release/own-adapter-host \
  --component components/infersharp.wasm \
  --tool infersharp \
  --artifact report.json=tests/infersharp/adversarial.json \
  --base-uri 'file:///repo/sts'
# stdout: empty
# stderr: NO-TOOL: adapter-fault: adapter rejected input: parsing Infer# report.json: ...
# exit:   1  (nothing ingested, host intact)
```

## 6. Run the passthrough (native-SARIF tools take the same path)

```bash
./host/target/release/own-adapter-host \
  --component components/passthrough.wasm \
  --tool roslyn \
  --artifact roslyn.sarif=tests/passthrough/roslyn.sarif \
  --base-uri 'file:///repo/sts' \
  | python -m json.tool
```

Expect the same SARIF back, but normalized (`version` canonicalized from
`2.1.0-rtm.6` to `2.1.0`, `$schema` filled in) and carrying the same
`adapterComponentSha256` provenance stamp — proof that Roslyn/CodeQL flow
through the identical validated, sandboxed path as Infer#. See `UNIFIED.md`.

## 7. Resource-limit paths (the spike's real claim)

- **Fuel:** `--fuel 100000` on a large report → `component trapped (fuel/epoch/memory?)`.
- **Memory:** feed a multi-hundred-MB `report.json` → the guest hits the 256 MiB
  linear-memory cap and traps; the host does not OOM.
- **Epoch:** `--epoch-ms 50` against a pathological input → epoch deadline trap.

In every case: stdout stays empty, the fault is surfaced as an honest skip, the
orchestrator keeps running. That containment is the whole reason this is WASM
and not an in-process parser.

## §bindings — if `cargo component build` disagrees on paths

`components/infersharp/src/lib.rs` imports `bindings::Guest` and
`bindings::ownaudit::adapter::types::RawInput`. cargo-component's generated
module layout occasionally differs by version. If it fails to resolve, run
`cargo component build` once, open `target/.../bindings.rs` (or `cargo expand`),
and adjust the two `use` lines to the generated paths. The host side uses the
`wasmtime::component::bindgen!` macro against the same WIT — if the generated
`RawInput`/`NamedBlob` path differs, fix the `use ownaudit::adapter::types::...`
line in `host/src/main.rs` the same way.

## §versioning — evolving the ABI without breakage

Adding a field to a WIT `record` is a **breaking** ABI change. So:

- Route most tuning through `raw-input.options: list<u8>` (opaque bytes the host
  passes through) — no ABI churn.
- When a field is genuinely needed, bump the package minor
  (`ownaudit:adapter@0.2.0`) and have the host accept both worlds for a
  deprecation window.
- There is one canonical `wit/world.wit`. Both the host (`bindgen!`) and the
  component (`[package.metadata.component.target] path = "../../wit"`) point at
  it — no copy to keep in sync.

## Wiring into `aggregate` (next step, not in this spike)

`aggregate` calls `own-adapter-host` per non-SARIF tool, reads SARIF on stdout,
and feeds it to the existing `parse_sarif`. The `adapters.toml` entry supplies
the component path and per-tool caps.
