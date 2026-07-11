# Suppression & false-positive policy

One consolidated, user-facing answer to "I got a finding I don't agree with —
what do I do?" This page doesn't introduce anything new; it collects what's
already designed (P-004), drafted (P-015), and observed in practice
(`docs/notes/real-world-mining.md`, `docs/notes/oracle.md`) into one place.

## The policy: a false positive is worse than a miss

This is the project's prime directive for shipped tooling
([`docs/notes/strictness-and-fitness.md`](notes/strictness-and-fitness.md)) —
and it drives a concrete design choice: when the C# extractor can't *prove* a
fact (an external type it has no reference for, a construct it doesn't model
yet), it emits an honest **`OWN050`** ("unresolved" / "skipped"), never a
guessed leak. Silence-by-default, not confidence-by-default.

This is why **`using` never produces a false positive**: the extractor models
`using` as a release, full stop — it is not a heuristic that occasionally
misses. Every real-world mining run to date confirms the policy holds in
practice, not just on paper: triaging by hand across `Dapper`, `CsvHelper`, and
`ScreenToGif` turned up zero false positives from `using`-scoped locals
(`real-world-mining.md`), and the cross-tool oracle runs against `Dapper` and
`App-vNext/Polly` both closed at **`own-only 0`** — nothing Own.NET flagged
turned out to be wrong (`oracle.md`). Where the extractor *did* have a
precision gap (self-owned WPF controls built via `ref`/`out` construction,
template parts from `GetTemplateChild`/`FindName`), it was fixed, not
suppressed — see the self-owned-control fix in `real-world-mining.md`.

**A narrower, separate point about the core.** The `.own` DSL's ownership
dataflow (`ownlang/analysis.py`) is *intentionally conservative* in the
Rust-borrow-checker sense: it proves soundness over an idealized closed-world
program, and would rather reject a technically-fine `.own` program (a
"maybe"-tier `OWN009`/`OWN010`) than silently accept an unsound one — see the
README's ["An important turn on false positives"](../README.md#an-important-turn-on-false-positives).
That is a *different axis* from the policy above: it is about the core
prover's soundness on a small formal language, not about the real-C# extractor's
UX. The two are compatible, not in tension — the extractor's honest-skip
(`OWN050`) is exactly what lets the ambiguous, can't-prove-it-either-way case in
real C# stay silent instead of forcing the core's conservative "maybe" tier to
fire on unprovable input.

## What you can do about a finding today

| Lever | Status | Scope |
|---|---|---|
| `--severity warning` | **works today** (P-013) | Global: downgrades every error-tier finding for that run to advisory. Per-run, not per-finding — an escape hatch for "show me everything, but don't fail the build yet," not a way to silence one specific site. |
| `--fail-on-finding` set to off | **works today** (P-013) | Global: findings still print/annotate, but the process/step exit code stays 0. The CLI (`own-check.sh`) is off by default — you must pass the flag to make findings fail the shell. The GitHub Action inverts that for safety: its `fail-on-finding` input defaults to `"true"` (fails the step on a finding), so to get the "annotate but don't fail" behavior in CI you must explicitly set `fail-on-finding: "false"`. |
| `[OwnIgnore("reason")]` | **works today** on `IDisposable` fields (P-004, #209) | Inline, per-site suppression attribute — the fine-grained escape hatch for a specific site the checker can't see enough context to clear. Put `[OwnIgnore("reason")]` on the field; the finding is then **silent-but-counted** — kept out of the exit code and the human findings stream, but tallied in the run summary and carried in SARIF `suppressions` (`kind: "inSource"`, your reason as the `justification`) so nothing is lost and a consumer can audit it. The **reason is mandatory**: a reason-less `[OwnIgnore]` (or an empty `[OwnIgnore("")]`) does **not** suppress — a suppression is a documented decision, never a silent accept. The attribute is matched by simple name, so you can declare your own `OwnIgnoreAttribute`. Currently reads on `IDisposable` **field** declarations (the clearest attribute site); other sites (subscriptions, timers) are follow-up increments. |
| Project-wide config (`.ownrc`/`own.toml`) | **draft, not implemented** (P-015) | Per-check-category enable/disable + severity + per-path overrides (e.g. relax a category under `tests/`). Stub status — format (TOML vs INI vs JSON) and enforcement point are still open questions in the proposal. |
| `corpus/oracle-fp-baseline.txt` | **exists, but not a user-facing suppression tool** | An allowlist the *oracle comparator* (`scripts/oracle_compare.py`, a dev/maintainer tool) uses to keep already-triaged false positives out of the `own-only` bucket on re-runs. It doesn't change what `own-check`/the Action reports — it only keeps the oracle's own triage queue from re-showing confirmed noise. |

So today: you **can** suppress one specific finding with an inline
`[OwnIgnore("reason")]` on the field it fires on (shipped, #209) — the finding
goes silent but stays counted (summary tally + SARIF `suppressions`). The
project-wide counterpart (`.ownrc`/`own.toml`, P-015) is drafted, not shipped.
Together with the global severity dial and the extractor's own honest-skip
behavior, that covers per-site and per-run; the per-*category*, per-*path*
config is the remaining gap. The precision bar above still matters as much as
the suppression surface — the fewer false positives reach you, the less
suppression UX has to carry.

## The full shape (`[OwnIgnore]` shipped; config still to come)

Precedence (P-015's draft order — the inline attribute half is shipped, #209;
the config-file half is still draft):

```text
CLI flag  >  inline [OwnIgnore]  >  config file  >  built-in default
```

`[OwnIgnore("reason")]` (P-004, **shipped** #209) is a per-site attribute — the
*reason* string is mandatory by design, so a suppression is a documented
decision, not a silent one. It is consumed **core-side** (the extractor emits
the finding fact with the reason marker; the core decides the verdict, keeps it
out of the exit code, and stamps SARIF `suppressions`), so a suppression is
counted, never a silent drop. Project config (P-015, draft) is the
per-category, project-wide counterpart — "treat subscriptions as warnings, keep disposables as errors,
skip pool checks under `tests/`" — discovered by walking up from the scanned
path, the same convention as `.editorconfig`/`ruff.toml`. Both are consumed
**core-side** ([P-013](proposals/P-013-distribution-surface.md)'s "one
checker" rule): the extractor may skip emitting a fact for a disabled category
as an optimization, but the core is the sole authority on what a finding says,
so config can never become a second, disagreeing checker.

## Reporting a false positive

If you hit one in real code: that is exactly the signal the project runs on.
Reduce it to a minimal repro if you can, and it becomes either a precision fix
(the self-owned-control fix above is the template) or a documented, deliberate
by-design skip recorded in
[`docs/notes/field-notes-patterns.md`](notes/field-notes-patterns.md) — the
living map of what Own.NET has seen and why it stays silent on it.
