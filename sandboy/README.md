# sandboy — wrap-the-child confinement (Layer 2 MVP)

**Status: spike.** The Sandboy MVP from
[`docs/notes/sandboy-isolation-adr.md`](../docs/notes/sandboy-isolation-adr.md)
§4 — the least-privilege-per-command layer. It confines one untrusted command
(an `.007/gate.toml` step, an agent tool call) using only **unprivileged Linux
primitives**: Landlock + seccomp. No root, no namespaces, no daemon.

```
sandboy run --policy step.toml -- bash -lc '<a gate step>'
```

The process applies the confinement to itself and then `execve`s the target;
**Landlock and seccomp both survive the exec**, so the wrapped command — and
everything it spawns — inherits the cage.

## What it enforces

| Boundary | Mechanism | Scope |
|---|---|---|
| **Filesystem** | Landlock | read+exec / read+write allowlists of paths; everything else `EACCES` |
| **TCP ports** | Landlock ABI v4 | connect/bind only to allowlisted ports (e.g. 443, 22) |
| **Syscalls** | seccomp-bpf | denylist of dangerous syscalls (ptrace, mount, bpf, kexec, …) → `EPERM`; everything else allowed |
| **Environment** | `env_clear()` + allowlist | wrapped command inherits ONLY the variable names in `env_allow`; everything else (host credentials included) is cleared before exec |

The seccomp model is a **denylist** on purpose: the goal is *broad freedom*
inside a box, so we strip the clearly-dangerous rather than allowlist a minimal
set (which breaks arbitrary toolchains). Landlock is the load-bearing FS/net
boundary; seccomp shrinks host-kernel attack surface behind it.

## What it is NOT (honest scope — ADR §4/§5)

- **Not host-escape resistance.** It shares the host kernel (no VM). A kernel
  LPE reachable through an *allowed* syscall still escapes. True escape
  resistance is **Layer 1 (Firecracker)**, added when an untrusted target repo
  enters scope. Layer 2 is defense-in-depth *inside* that, and the 80/20 MVP.
- **Not host/CIDR/domain egress control.** Landlock scopes *ports*, not
  addresses. `tcp_connect = [443]` means "TCP to port 443 anywhere", not "only
  to github.com". Address/domain egress is **Layer 3** (netns + filtering
  proxy, blanket-UDP-block per ADR §7.3).
- **Not a side-channel defense** (out of the single-tenant threat model).

## Policy

TOML, per step. See [`policy.example.toml`](policy.example.toml):

```toml
fs_ro       = ["/usr", "/bin", "/lib", "/lib64", "/etc"]
fs_rw       = ["/home/user/work/worktree", "/tmp"]
tcp_connect = [443, 22]          # https + ssh; [] = no outbound TCP
tcp_bind    = []
env_allow   = ["PATH"]           # names passed through; [] (default) = fully cleared env
# omit seccomp_deny to use the curated default denylist
```

`env_allow` is a **name** allowlist, resolved against the launcher's own
environment right before `exec`. Omitting it (or leaving it `[]`, the default)
means the wrapped command gets **no** inherited environment at all — the
launcher's environment is exactly where CI/agent credentials
(`GITHUB_TOKEN`, cloud/package-registry secrets, `SSH_AUTH_SOCK`, …) live, so
deny-all is the only safe default for an untrusted command. Allowlist by name
rather than maintaining a denylist of known-bad variables.

This TOML is the file Sandboy actually reads, and it should stay exactly this
plain. Once there's more than one profile (`no-net`, `worktree-only`, a Windows
exec allowlist) to compose without copy-pasting, author the source in CUE and
render it down to this shape (`cue export step.cue --out toml > step.toml`) —
Sandboy's runtime never needs to know CUE exists. Full rationale and the
`#Policy`/`#Base`/`#NoNet` schema this maps onto:
`007/docs/zero-trust-framework.md` §12.

## Build & run

> **Authored, not compiled here.** Written in a network-restricted sandbox
> (no crate downloads: `static.crates.io` egress-blocked), so it has **not**
> been through `cargo`. The `landlock`/`seccompiler` crate API pins may need a
> minor nudge — those two `apply_*` functions are the likely spots.

```bash
cargo build --release        # needs Linux; the crates are Linux-only
./tests/demo.sh              # four probes: 1 allowed, 3 denied
./target/release/sandboy probe   # host capability report (JSON), see below
```

### `sandboy probe`

A second, diagnostic-only subcommand alongside `run`: applies the exact same
enforcement code (`landlock_status`, `apply_seccomp`) against a synthetic
default policy, then prints what THIS host actually did with it as JSON —
Landlock ABI/ruleset status (via the same crate call `run` uses, plus a raw
`landlock_create_ruleset(..., LANDLOCK_CREATE_RULESET_VERSION)` probe syscall
for the kernel's own ABI number), whether seccomp installed, `no_new_privs`,
`close_range`, kernel release, euid/egid, and a couple of cheap
container/VM signals (`/.dockerenv`, first `/proc/self/cgroup` line). `probe`
always exits `0` — finding "Landlock not enforced" is data, not a probe
failure; a caller (a CI gate, `tests/feasibility/run_gate.py`) decides
pass/fail from the JSON. It never applies to or execs a target command, and
never appears in a `sandbox_policy` step — that's `run`.

`demo.sh` shows a write inside the worktree succeeding, and a write to `$HOME`,
a `ptrace`, and a connect to a non-allowlisted port all being denied.

### The audited `unsafe`

Sandboy is the syscall-boundary crate, so — unlike the analyzer core
(`unsafe_code = forbid`) — it permits **two** narrowly-scoped, audited `unsafe`
calls at the syscall seam: `prctl(PR_SET_NO_NEW_PRIVS)` (required before an
unprivileged seccomp install) and `close_range(.., CLOSE_RANGE_CLOEXEC)` (closes
the inherited-fd hole, below). All other unsafe lives inside the
`landlock`/`seccompiler` crates ("берём готовое", ADR §2). Nothing user-derived
reaches either call.

### Inherited descriptors

Landlock scopes *new* opens by path and seccomp filters *syscalls* — **neither
revokes a descriptor that is already open**. If the launcher (gate/orchestrator)
leaks an fd — an open file or a live socket without `FD_CLOEXEC` — it would pass
into the wrapped command and bypass the FS/port allowlists entirely. So before
`execve`, sandboy marks every fd > 2 close-on-exec; stdio (0,1,2) is kept.

## Wiring into 007 (the actual use)

The gate runner wraps each step instead of running it bare:

```
# before:  bash -lc "<step.cmd>"                      (bare, no confinement)
# after:   sandboy run --policy <step-policy> -- bash -lc "<step.cmd>"
```

Per-step policies let a `fmt` step run with no network and RO toolchain, while a
`cargo test` step gets 443 + a writable target dir — least privilege per step,
which is exactly what `007/docs/security-layers.md` marks as the missing layer
in the `run`/gate slot.

The same slot, framed as a loop-engineering design surface (the canvas
**Actions** boundary + **Limits** timeout + **Observability** evidence per gate
step), is in `007/docs/loop-canvas.md`. Two hooks make that real, and **neither
exists yet** — both are Floor-1 work, not current behaviour:

- **007 side — `sandbox_policy` on `GateStep`.** A per-step policy path so the
  gate runner knows to wrap the step. **Not yet added.** The manifest parser
  tolerates unknown fields, but this is a **security control**, so it must
  **fail closed** when it lands: a manifest `schema` bump (or explicit presence
  check) so an older `o7` that can't enforce a `sandbox_policy` **refuses the
  step** rather than silently running it bare and unconfined (the
  `bypassPermissions` mode applies to the agent phase, not gate steps). Relying
  on unknown-field tolerance here would fail *open*. See
  `007/docs/loop-canvas.md`.
- **sandboy side — `--report <json>` on `run`.** A flag emitting per-invocation
  enforcement status / exit code / duration for one wrapped step, the
  machine-readable evidence the Observability field asks for. **Still not
  implemented:** `run` only accepts `--policy <file>` and `--`, so passing
  `--report` is a usage error (exit 2). Enforcement status *is* already
  surfaced, but only to **stderr** (`FullyEnforced` silently / `PARTIALLY
  enforced` warning / `NOT enforced` refusal). This is distinct from the
  `probe` subcommand added for the Sandboy S0 feasibility gate (below):
  `probe` reports host *capability*, once, with no target command; the
  `gate/<step>.sandbox.json` use case here is per-step *outcome*, for every
  wrapped invocation. Wiring `run` --report into 007's gate runner is still
  Floor-1 work, out of scope here.

## Kernel requirements

- Landlock FS scoping: kernel ≥ 5.13.
- Landlock TCP-port scoping: kernel ≥ 6.7 (ABI v4). On older kernels sandboy
  runs **best-effort** and prints a `PARTIALLY enforced` warning; it refuses to
  run only if Landlock is entirely absent (`NOT enforced`).

## Sandboy S0 — GitHub-hosted runner feasibility gate

`tests/feasibility/` is a capability probe, not a repository miner: it proves
(or disproves) that *this* Sandboy commit actually confines a hostile process
tree on a standard `ubuntu-24.04` GitHub-hosted runner — Landlock FS/port
scoping, seccomp, fork/exec inheritance, credential-canary isolation via
`env_allow`, and the two structural network gaps (no UDP coverage; TCP is
scoped by port only, never by destination address, so a policy allowing e.g.
port 443 cannot distinguish a real destination from a cloud metadata
endpoint on the same port — that's the unbuilt Layer 3). It never executes
third-party repository code; every fixture under `tests/feasibility/fixtures/`
is a small first-party Python probe run via a plain argv (never a shell
string).

```bash
cargo build --release
python3 tests/feasibility/run_gate.py \
  --sandboy-bin "$(pwd)/target/release/sandboy" \
  --out-dir /tmp/sandboy-s0-reports
```

Writes `sandboy-host-capabilities.json`, `sandboy-feasibility-report.json`,
`sandbox-enforcement-matrix.json`, and `sandboy-feasibility-summary.md`, and
exits non-zero if the S0 acceptance criteria aren't met (e.g. this host has no
Landlock at all — the case in most container-based dev sandboxes, which is
exactly why this gate targets a real `ubuntu-24.04` runner in CI:
`.github/workflows/sandboy-feasibility-gate.yml`). A gate failure because
Landlock/seccomp is unavailable on the runner is a real finding to report,
not something to route around by weakening `run`'s fail-closed refusal.
