//! own-adapter-host — run one `ownaudit:adapter` component over one tool
//! invocation and emit validated, provenance-stamped SARIF on stdout.
//!
//! The security contract (see ../README.md):
//!   * the component has ZERO imports  -> zero ambient authority;
//!   * we cap it with fuel, an epoch deadline, and a memory ceiling;
//!   * its OUTPUT is NOT trusted either — we schema-check and size-cap the
//!     returned SARIF before anything downstream (`parse_sarif`) sees it.
//!
//! Usage:
//!   own-adapter-host --component <path.wasm> --tool <id> \
//!     [--artifact name=path]... [--stdout-file f] [--stderr-file f] \
//!     [--exit-code N] [--base-uri URI] [--options-file f] \
//!     [--fuel N] [--epoch-ms N] [--max-bytes N] [--max-results N]

use std::path::PathBuf;
use std::time::Duration;

use anyhow::{anyhow, bail, Context, Result};
use sha2::{Digest, Sha256};
use wasmtime::component::{Component, Linker};
use wasmtime::{Config, Engine, Store, StoreLimits, StoreLimitsBuilder};

// Generated from the WIT world. `RawInput` / `NamedBlob` land under the
// package/interface path; if a wasmtime version shifts the module path, adjust
// the `use` below (BUILD.md notes this).
wasmtime::component::bindgen!({
    path: "../wit/world.wit",
    world: "sarif-adapter",
});
use ownaudit::adapter::types::{NamedBlob, RawInput};

/// Host store state: just the resource limiter (no WASI, nothing else).
struct HostState {
    limits: StoreLimits,
}

#[derive(Default)]
struct Args {
    component: Option<PathBuf>,
    tool: Option<String>,
    argv: Vec<String>,
    exit_code: i32,
    stdout_file: Option<PathBuf>,
    stderr_file: Option<PathBuf>,
    artifacts: Vec<(String, PathBuf)>,
    base_uri: String,
    options_file: Option<PathBuf>,
    fuel: u64,
    epoch_ms: u64,
    max_bytes: usize,
    max_results: usize,
}

fn parse_args() -> Result<Args> {
    let mut a = Args {
        // Defaults tuned for "a parser over one tool's output": generous but
        // finite. Override per-tool via adapters.toml / flags.
        fuel: 2_000_000_000,
        epoch_ms: 5_000,
        max_bytes: 64 * 1024 * 1024,
        max_results: 200_000,
        ..Default::default()
    };
    let mut it = std::env::args().skip(1);
    while let Some(flag) = it.next() {
        let mut next = || it.next().ok_or_else(|| anyhow!("{flag} needs a value"));
        match flag.as_str() {
            "--component" => a.component = Some(PathBuf::from(next()?)),
            "--tool" => a.tool = Some(next()?),
            "--argv" => a.argv.push(next()?),
            "--exit-code" => a.exit_code = next()?.parse().context("bad --exit-code")?,
            "--stdout-file" => a.stdout_file = Some(PathBuf::from(next()?)),
            "--stderr-file" => a.stderr_file = Some(PathBuf::from(next()?)),
            "--artifact" => {
                let kv = next()?;
                let (name, path) = kv
                    .split_once('=')
                    .ok_or_else(|| anyhow!("--artifact expects name=path, got {kv}"))?;
                a.artifacts.push((name.to_string(), PathBuf::from(path)));
            }
            "--base-uri" => a.base_uri = next()?,
            "--options-file" => a.options_file = Some(PathBuf::from(next()?)),
            "--fuel" => a.fuel = next()?.parse().context("bad --fuel")?,
            "--epoch-ms" => a.epoch_ms = next()?.parse().context("bad --epoch-ms")?,
            "--max-bytes" => a.max_bytes = next()?.parse().context("bad --max-bytes")?,
            "--max-results" => a.max_results = next()?.parse().context("bad --max-results")?,
            other => bail!("unknown flag: {other}"),
        }
    }
    Ok(a)
}

fn read_opt(p: &Option<PathBuf>) -> Result<Vec<u8>> {
    match p {
        Some(path) => std::fs::read(path).with_context(|| format!("reading {}", path.display())),
        None => Ok(Vec::new()),
    }
}

fn main() {
    if let Err(e) = run() {
        // Any failure — trap, invalid output, IO — becomes an honest skip.
        eprintln!("NO-TOOL: adapter-fault: {e:#}");
        std::process::exit(1);
    }
}

fn run() -> Result<()> {
    let args = parse_args()?;
    let component_path = args.component.clone().ok_or_else(|| anyhow!("--component required"))?;
    let tool = args.tool.clone().ok_or_else(|| anyhow!("--tool required"))?;

    let wasm_bytes = std::fs::read(&component_path)
        .with_context(|| format!("reading component {}", component_path.display()))?;
    let component_sha = hex(&Sha256::digest(&wasm_bytes));

    // --- Engine: component model + fuel + epoch interruption ---------------
    let mut config = Config::new();
    config.wasm_component_model(true);
    config.consume_fuel(true);
    config.epoch_interruption(true);
    let engine = Engine::new(&config)?;
    let component = Component::from_binary(&engine, &wasm_bytes)?;

    // No imports in the world => an empty linker is the whole host surface.
    let linker: Linker<HostState> = Linker::new(&engine);

    let limits = StoreLimitsBuilder::new()
        .memory_size(256 * 1024 * 1024) // hard ceiling on guest linear memory
        .instances(1)
        .build();
    let mut store = Store::new(&engine, HostState { limits });
    store.limiter(|s| &mut s.limits);
    store.set_fuel(args.fuel)?;

    // Epoch backstop: one deadline tick, bumped after epoch_ms of wall-clock,
    // so a component that busy-loops without burning fuel (unlikely, but the
    // belt to fuel's suspenders) still gets interrupted.
    store.set_epoch_deadline(1);
    let engine_for_timer = engine.clone();
    let epoch_ms = args.epoch_ms;
    std::thread::spawn(move || {
        std::thread::sleep(Duration::from_millis(epoch_ms));
        engine_for_timer.increment_epoch();
    });

    // --- Build the pure input ---------------------------------------------
    let mut artifacts = Vec::new();
    for (name, path) in &args.artifacts {
        artifacts.push(NamedBlob {
            name: name.clone(),
            bytes: std::fs::read(path).with_context(|| format!("reading {}", path.display()))?,
        });
    }
    let input = RawInput {
        tool: tool.clone(),
        argv: args.argv.clone(),
        exit_code: args.exit_code,
        stdout: read_opt(&args.stdout_file)?,
        stderr: read_opt(&args.stderr_file)?,
        artifacts,
        base_uri: args.base_uri.clone(),
        options: read_opt(&args.options_file)?,
    };

    // --- Instantiate and call ---------------------------------------------
    let bindings = SarifAdapter::instantiate(&mut store, &component, &linker)
        .context("instantiating component")?;

    let out = match bindings.call_to_sarif(&mut store, &input) {
        // Trap: fuel exhausted, epoch deadline, memory cap, or panic. The
        // WASM boundary contained it — surface as a fault, don't ingest.
        Err(trap) => bail!("component trapped (fuel/epoch/memory?): {trap:#}"),
        // Adapter-reported error (bad tool output it chose to reject).
        Ok(Err(msg)) => bail!("adapter rejected input: {msg}"),
        Ok(Ok(bytes)) => bytes,
    };

    // --- Output is NOT trusted: validate + cap BEFORE anyone parses it -----
    if out.len() > args.max_bytes {
        bail!("SARIF output {} bytes exceeds --max-bytes {}", out.len(), args.max_bytes);
    }
    let mut sarif: serde_json::Value =
        serde_json::from_slice(&out).context("component returned bytes that are not JSON")?;
    validate_sarif(&sarif, args.max_results)?;

    // --- Provenance stamp: reproducible + auditable ------------------------
    if let Some(runs) = sarif.get_mut("runs").and_then(|r| r.as_array_mut()) {
        for run in runs {
            let props = run
                .as_object_mut()
                .ok_or_else(|| anyhow!("run is not an object"))?
                .entry("properties")
                .or_insert_with(|| serde_json::json!({}));
            props["adapterComponentSha256"] = serde_json::json!(component_sha);
            props["adapterHost"] = serde_json::json!(env!("CARGO_PKG_VERSION"));
            props["adapterTool"] = serde_json::json!(tool);
        }
    }

    serde_json::to_writer(std::io::stdout(), &sarif)?;
    Ok(())
}

/// Minimal, defensive SARIF shape check — enough to refuse garbage, not a full
/// schema validator (that lives downstream in `parse_sarif`).
fn validate_sarif(v: &serde_json::Value, max_results: usize) -> Result<()> {
    let ver = v.get("version").and_then(|s| s.as_str()).unwrap_or("");
    if !ver.starts_with("2.1") {
        bail!("not SARIF 2.1.x (version = {ver:?})");
    }
    let runs = v
        .get("runs")
        .and_then(|r| r.as_array())
        .ok_or_else(|| anyhow!("missing runs[]"))?;
    let mut total = 0usize;
    for run in runs {
        if run.get("tool").and_then(|t| t.get("driver")).is_none() {
            bail!("run missing tool.driver");
        }
        if let Some(results) = run.get("results").and_then(|r| r.as_array()) {
            total += results.len();
        }
    }
    if total > max_results {
        bail!("{total} results exceeds --max-results {max_results}");
    }
    Ok(())
}

fn hex(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push_str(&format!("{b:02x}"));
    }
    s
}
