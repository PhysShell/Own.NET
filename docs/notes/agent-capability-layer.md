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
| **2. Runner enforcement** | wrap agent in worktree + Sandboy | **Built** (`sandboy/`). Wire to a real gate step. |
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
native isolation      worktree + Sandboy                   (built: sandboy/)
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
