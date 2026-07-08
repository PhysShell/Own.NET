# Design note: agent capability & policy layer («Owen Gate»)

> Design note / RFC. Working codename **Owen Gate**. Sibling of the Sandboy
> isolation direction ([`sandboy-isolation-adr.md`](sandboy-isolation-adr.md)):
> Sandboy is the *process* cage; this note is the *tool/capability + policy*
> layer that sits with it. Not normative; options for tomorrow.
>
> Origin: an external proposal («make the agent reach the world only through
> WIT gateways» + a canonical policy that replaces the ignore-file zoo),
> critiqued and landed against what already exists in this branch.

---

## 0. Thesis (accepted, with one correction)

**ADOPT** — WIT/Component Model as a **capability boundary for tools**, not as a
sandbox for the agent. Isolate `repo.read` / `verify.run` / `memory.search` as
capability-scoped components with explicit WIT contracts; the host mediates every
call against policy. This is consistent with the whole branch: WASM can't cage a
native agent (bash/git/compilers), but WIT is right for tool components.

**CORRECTION the source proposal underplays** — the «safe vs sticky-note» line
runs at the **process boundary, not the WIT boundary**:

- A WIT gateway is a *safe* only for tools funnelled through it.
- For anything the agent does **around** it (raw shell), WIT policy is a *note*:
  `cat ~/.ssh/id_rsa` via bash obeys no WIT contract.

So «agent reaches the world only through WIT» is true **only if the agent has no
raw shell** — which forks the whole design (§1).

---

## 1. The load-bearing fork: (A) tools-only vs (B) full-freedom + sandbox

| | (A) Tools-only agent | (B) Full-freedom agent + process sandbox |
|---|---|---|
| Raw shell | removed | kept |
| Enforcement | WIT gateway + `[exec]` allowlist **bite** | **Sandboy** (Landlock/seccomp/worktree) is the boundary |
| WIT role | the agent's cage | contracts + context-hygiene for **your own tools** |
| `policy [exec]`/`[network]` | enforced | **advisory** unless mirrored by Sandboy at the syscall level |
| Cost | you built a *weaker* agent than stock Claude Code | you keep stock power |

**Recommendation: (B).** Most of the value of Claude Code/Codex is the
full-freedom shell; (A) throws it away. In (B), the capability layer is worth
building **for Owen's own tools** (verifier, memory, secret-scanner) — clean
contracts + untrusted-input containment — **not** as the agent's cage. The
agent's cage is Sandboy.

---

## 2. Half of this already exists in the branch

| Proposal component | Already here | Delta to build |
|---|---|---|
| `owen-capability-host` (WIT host, Wasmtime, cap logging) | `audit/adapters/host` (`own-adapter-host`) | our adapter world has **zero imports** (pure); a tool-world has **imports** (`repo`/`memory`/`verify`) the host satisfies **policy-mediated**. Delta = richer linker + policy check + per-call log. Same runtime. |
| `owen-runner` (claude/codex wrappers + worktree isolation) | `sandboy/` (`sandboy run --policy -- <cmd>`) | wire it to wrap a real gate step. |
| `owen-policy` (canonical policy + gen-ignore) | — | **not built. Highest-ROI new piece (§3).** |
| MCP bridge | — | thin, later (§4 Phase 4). |

So we're not starting from zero — Phases 2–3 are seeded; only Phase 1 is greenfield.

---

## 3. `owen.policy.toml` — single source of truth (the strongest idea)

One canonical policy replaces the zoo (`.agentsignore` / `.cursorignore` /
`.codexignore` / `.claudeignore`). Ignore-files become **generated compatibility
artifacts**, not the source of truth. Shape:

```toml
[repo]
default_read = "deny"
default_write = "deny"
[[repo.read]]  allow = "src/**"
[[repo.read]]  deny  = "**/.env"          # reason = secrets
[[repo.write]] allow = ".owen/runs/**"

[exec]    default = "deny"
[[exec.allow]] cmd = "git"    args = ["status", "--short"]
[[exec.allow]] cmd = "pytest"

[network] default = "deny"
[[network.allow]] host = "docs.rs" profiles = ["research"]

[context] generate_ignore_files = true
```

CLI: `owen policy check <path> --read/--write`, `owen policy explain <path>`,
`owen policy gen-ignore`, `owen context build --profile <p>`.

**Two honest frames (do NOT skip in the docs):**

1. **Ignore-generation is context-hygiene, NOT security.** Generating
   `.claudeignore` from policy buys *consistency* (no drift across N agents), not
   secret protection. Secrets are protected by Sandboy (don't mount / Landlock RO).
   `deny = "**/.env"` in policy is a false safe if read as security.
2. **The generator is a compat-shim and it rots.** `.cursorignore` /
   `.codexignore` / `.claudeignore` have **different semantics** (indexing vs
   context vs tool-access, different glob rules). The generator must model each
   target's semantics, not assume they're identical — ongoing maintenance as
   targets drift.

**`[exec]` allowlist caveat:** it bites **only in mode (A)** (no raw shell). In
(B), `bash -c` bypasses argv-matching; real exec control is Sandboy at the
syscall/reachable-binary level. Two different enforcement models — don't conflate.

---

## 4. Phased plan (для-души filter: would I use it? is it fun?)

| Phase | What | Verdict |
|---|---|---|
| **1. Policy engine** | `owen-policy`: parse `owen.policy.toml`, `policy check/explain`, `gen-ignore` | **Do.** Daily use, zero risk, not built. 80% of daily value. |
| **2. Runner enforcement** | wrap agent in worktree + Sandboy | **Spiked** (`sandboy/` — authored, not yet compiled; acceptance gate: `cargo build` + `tests/demo.sh`, see `sandboy/README.md`). Wire to a real gate step. |
| **3. WIT tool components** | move tools to capability-scoped components | **Selective.** WIT only where input/author is untrusted: `secret-scanner`, `patch-analyzer`, `verifier-adapter` (parse untrusted output) — yes. `memory-search` over **your own** data — plain code, WIT buys nothing. |
| **4. MCP/WIT bridge** | `owen-mcp` tools backed by policy + components | Thin, later. |

---

## 5. Non-goals (what NOT to do)

- **NOT** compile Claude Code/Codex to Wasm (native workload; established across the branch).
- **NOT** add Extism — a Wasmtime Component-Model host already exists
  (`own-adapter-host`); a second plugin runtime is fragmentation. One runtime.
- **NOT** build wasmCloud / a container runtime / a distributed scheduler — for
  N=1 self-use that's over-engineering. Take wasmCloud's capability-mediation
  *philosophy*, not the platform.
- **NOT** blanket-wrap every tool in WIT — only untrusted-input ones (§4 Phase 3).
- **NOT** let an LLM auto-apply policy changes. The LLM may *propose*; a human /
  deterministic CLI *applies*. «Agent granted agent read-secrets because it was
  useful for the task» is a real failure mode — an open door to the datacenter.

---

## 6. Where each concern lands (summary)

```
canonical policy      owen.policy.toml                     (Phase 1 — build)
context hygiene       generated ignore + filtered packs    (hygiene, NOT security)
tool isolation        WIT + Wasmtime (own-adapter-host+)   (Phase 3 — selective)
native isolation      worktree + Sandboy                   (spiked: sandboy/)
agent integration     mode (B): agent-with-shell in the    (Sandboy is the cage,
                      Sandboy cage, Owen tools on top       WIT tools are contracts)
memory / verifier     only through policy-mediated ifaces
```

The point of the whole layer: `.agentsignore`/`.cursorignore`/`.codexignore`
stop being a manual hell not because they vanish, but because they become
generated output of one policy engine, not your architecture.

---

## 7. Open questions

1. **A vs B for the actual harness** — do you want a full-freedom Claude Code in
   a Sandboy cage (B), or a restricted tools-only agent (A)? The whole layer's
   shape hangs on this. (Recommendation: B.)
2. **Per-agent ignore semantics** — how far do `.cursorignore` vs `.codexignore`
   vs `.claudeignore` actually diverge in 2026? Determines gen-ignore effort.
3. **Policy ⇄ Sandboy overlap** — how much of `[exec]`/`[network]` should be
   *compiled down* into a Sandboy policy (real enforcement) vs stay advisory
   context? Ideally `owen policy` emits a `sandboy` policy for mode (B).

---

## 8. Addendum (2026-07-05): authoring language for `owen.policy` — CUE, not TOML

§3 sketched `owen.policy.toml` as a single flat file. That's fine while there is
one profile. It stops being fine the moment there is more than one — `no-net`,
`worktree-only`, a `windows`-tagged exec profile, a `trusted-repo` vs
`untrusted-repo` split — because those need to **compose** ("inherit the base,
add these steps"), and TOML has no merge semantics of its own. Composing TOML by
hand means copy-pasting the base into every profile, and a copy that forgets
`network.default = "deny"` is precisely the failure mode this whole layer exists
to prevent — a config bug that reads as a permission grant.

**Decision: author `owen.policy` in [CUE](https://cuelang.org).** The reason to
prefer it over "TOML + a templating layer" is CUE's *unification* model: a
parent and a child don't override each other, they unify, and unification is a
**compile error** if they disagree. A leaf profile that tries
`network: "allow"` against a base that says `network: "deny"` doesn't silently
win — it fails to build. That is a materially different guarantee than
inheritance-with-override (Terragrunt-style merge, Jsonnet `+`), where the leaf
always wins and a mistaken override ships silently.

```text
policies/
  no-net.cue             # network: "deny" — the floor, never overridden
  worktree-only.cue      # repo.read/write confined to the worktree
  default-processes.cue  # exec allowlist
gates/
  own-net.cue            # unifies the policies above + step list
  own-net.windows.cue    # must *explicitly* switch to a different process
                         # profile to add e.g. `powershell` — can't inherit a
                         # denylist that silently forgot it
```

Compiled down to flat artifacts for whatever actually enforces it at runtime —
rendered TOML for the per-step Sandboy policy (`cue export --out toml`, see
`sandboy/README.md`), flat JSON for the gate manifest / `owen policy check`
consumer — the authoring layer is for
humans; the enforcement point should stay a boring, strict parser with no CUE
evaluation at run time.

Runner-up: **Nickel** (`import` + record merge via `&`, typed contracts) — a
reasonable second choice if the policy ever wants functions or generated
defaults; picked CUE first specifically because a security floor benefits more
from "conflicts are hard errors" than from programmability.

**Rejected for this use** (fine tools, wrong fit for a security source of
truth): **Jsonnet** (`+`/`super` composition is generative — right for stamping
out many manifests, wrong posture for policy, and a silent-override bug is just
as easy as in TOML with fancier syntax); **Dhall** (safe and total, but more
ergonomic weight than this scale needs — CUE gets the same "disagreement is an
error" property more cheaply); **HCL/Terragrunt** (`include` + `merge_strategy`
gives structural inheritance, but drags in Terraform's whole tooling/mental
model for a project that has nothing to do with infrastructure deployment).

**This does not change §0/§1.** WIT/Wasmtime stays the *execution* boundary for
tool components that parse untrusted input (already spiked as `audit/adapters`,
per `sandboy-isolation-adr.md` §6's update) — it is not a candidate for policy
*authoring*. The two axes stay separate: CUE composes the data, WIT/Sandboy
enforce it. See `007/docs/zero-trust-framework.md` for how 007 concretely
consumes a CUE-authored policy as `.007/gate.lock.json`.
