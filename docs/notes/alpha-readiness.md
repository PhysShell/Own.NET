# "Delicious .NET alpha" — the showable-to-people gate

Working note. The strategy is **not** "spread across stacks" — it is *"make one
stack delicious, and architecturally prove the core isn't bolted to it."* Concretely:
**80% of effort → .NET to "damn, it actually found a leak in my project,"** **20% →
one tiny spike in another stack** to back the platform-agnostic story (P-017/P-020).
A zoo of half-built frontends is cute until you have to deploy it.

This note answers one recurring question — **"are we ready to show people yet?"** —
by pinning a concrete gate and the *honest* current status against it. It is an
assessment, not a promise; status reflects a read of the repo on 2026-06-27.

## The wedge (what we sell, what we refuse to)

Do **not** pitch as: a static analyzer / AI code reviewer / SAST / borrow checker
for C# / multi-language bug finder. That arena belongs to Sonar/CodeQL/Semgrep/Snyk
and their sales teams; see
[ROADMAP — Positioning against the competition](../ROADMAP.md#positioning-against-the-competition-not-another-sast).

Sell the narrow clin:

> **Own.NET finds .NET lifetime/resource bugs: event leaks, timer leaks, missing
> `Dispose`, DI lifetime capture, and pooled-buffer misuse** — the class of bug that
> sends people to dotMemory to argue with their monitor.

Slogans on record (for posts, README, talks):
- *Find leaks before the profiler.*
- *GC collects unreachable objects; Own finds objects that should have become unreachable.*
- *`event +=` is acquire, `-=` is release.*
- *Not all lifecycle bugs leak memory — some leak requests.* (the Cloudflare-style post — P-020)

## The gate (A–G) and where we actually stand

The bar for "showable": a person can reproduce the wow in ~3 minutes
(`install → run → it found my real dirt`).

| | Item | Status (2026-06-27) | Gap to close |
|---|------|--------------------|--------------|
| **A** | `dotnet tool` one-command CLI | ◑ **mostly built** (issue #202) — `OwnSharp.Cli` wraps extractor+core into one `dotnet tool install` → `ownsharp check <path\|.sln>`, proven install→check→findings on a clean ubuntu/windows runner in CI (`ownsharp-cli-smoke`). See [`frontend/roslyn/OwnSharp.Cli/README.md`](../../frontend/roslyn/OwnSharp.Cli/README.md). | Not published to nuget.org yet — today it's build-and-install-from-source only. Publishing (+ a real version scheme beyond `0.1.0`) is the remaining step. |
| **B** | GitHub Action | ✅ **built** — `action.yml`: `path`/`severity`/`format` (`github` / `msbuild` / `human` / `sarif`), purple shield branding. Matches the "stupidly simple YAML" bar. | Publish to Marketplace; pin the 6-line usage in the README. |
| **C** | SARIF / PR annotations | ✅ **built** — SARIF 2.1.0 + GitHub annotations + reachability/evidence (P-015). | — |
| **D** | 5 core diagnostics | ✅ **built, well past** — OWN001/002/003, OWN014, DI001–005, POOL001–005, WPF001–005 (catalog). The comment's `SUB001/SUB002/TMR001/DISP001/DI001` all exist *semantically*; the `SUB/TMR/DISP` catalog rename is the deferred consolidation item, not new work. | (naming only) land the catalog rename with the OwnIR-v1/profile-label work. |
| **E** | 10 bad/ok examples | ✅ **built** — 12 test-pinned gallery cases (`examples/gallery/`, incl. `00_ok_clean`) + extractor samples. `.cs`-native bad/ok pairs now exist for 7/12 (`examples/gallery/cs/`, verified through the real extractor in CI). | The remaining 5 (`04`/`05`/`06`/`08`/`09`) need move/borrow/stack-buffer/unknown-call detectors on the C# side — recorded in `examples/gallery/cs/README.md`, not yet scheduled. |
| **F** | 3 real-world case studies | ✅ **built** — `docs/case-studies/`: `screentogif-videosource.md` (flagship view→view-model handler leak), `screentogif-systemevents.md` (two independent `SystemEvents` leaks), `dispose-agreement-with-codeql.md` (the Dispose/RAII class where Own.NET agrees with CodeQL/Infer#), all `bad → fixed → what others miss → how Own reports it`, linked from the README. | The wider proof (20–50 OSS repos, days 31–60 below) is still open — these three are the *packaged* studies, not the full real-world sweep. |
| **G** | suppression + false-positive policy | ✅ **built** — `docs/suppression-and-fp-policy.md` consolidates the FP policy (`OWN050` honest-skip, "no FP from `using`") with the suppression mechanisms, honestly marking `[OwnIgnore]` (P-004) as designed-not-implemented and project config (P-015) as draft-not-implemented — today's only working lever is `--severity`/`--fail-on-finding`. | — |

**Plus the front door (not in A–G but the real blocker):** ✅ **built** —
`README.md`/`README.ru.md` now open with a 20-second landing (verbatim pitch,
slogans, a 6-line Action quickstart, a local one-liner, one real bad/fixed
example, a "why not Sonar/CodeQL" link) instead of `# OwnLang — PoC`; the prior
research-framed opening moved down rather than being deleted. Per the comment's
own open-source-path list (README-in-20s → copy-paste → bad/ok → Action → SARIF →
suppression → "why not Sonar/CodeQL"), every step of that path now exists.

## Honest verdict

**The engine is past alpha on *capability* (D/E strong, B/C built). F/G, the
front door, and now A have all closed too — what's left is publishing, not
building:**

1. ~~a single `ownsharp check MyApp.sln` tool (**A**)~~ — **built**, not yet published to nuget.org;
2. ~~a wedge landing README + copy-paste quickstart (front door)~~ — **done**;
3. ~~three packaged case studies from finds we already have (**F**)~~ — **done**;
4. ~~one consolidated suppression / false-positive page (**G**)~~ — **done**.

None of those is research; all are the difference between "interesting PoC" and
"people install it." Publishing `OwnSharp.Cli` to nuget.org is now the one item
standing between here and the day 1–30 milestone being *literally* copy-paste
for a stranger.

## The 20% rule (other stacks)

Other stacks are **proof of portability, not a second product.** Sanctioned now:
**at most one rule each**, as experiments — not an OwnTS 1.0.

```
experiments/
  owents-react-effect-cleanup/   # P-020: useEffect listener/effect, the PR/marketing spike
  ownjava-listener-leak/         # P-017: addListener w/o removeListener → same OwnIR, the model proof
```

README framing, and no more: *"Experimental: the same OwnIR model can represent
React effect cleanup and Java listener lifetimes."* Design lives in
[P-017](../proposals/P-017-multi-stack-frontends.md) /
[P-020](../proposals/P-020-ownts-react-effects.md); both stay `horizon`/`draft`
until the .NET alpha above is delicious. Do not let the spike exceed 20%.

## 90-day shape (sequencing, not a schedule)

- **Days 1–30 — make the .NET alpha tasty:** publish `OwnSharp.Cli` to
  nuget.org (A/B/C/D/E/F/G and the README front door are all otherwise done).
  Suppression UX + bad/ok corpus polish continue as bug-driven follow-ups, not
  a blocking gate.
- **Days 31–60 — real-world proof:** run over 20–50 OSS .NET/WPF/Avalonia/WinForms
  repos; table of findings / confirmed / FP / unsupported; 2 case studies; compare
  with CodeQL / NetAnalyzers / Infer# where possible (the oracle, `docs/notes/oracle.md`).
- **Days 61–90 — public launch:** landing README, "WPF zombie ViewModels" post,
  HN/Reddit/dev.to/.NET community, Action on Marketplace, `good first spec` issues,
  feedback from WPF/Avalonia/WinForms maintainers. The React/Java spike runs in
  parallel — capped at 20%.

The standing priority is unchanged: **prove value, don't reshape form**
([consolidation-and-positioning.md](consolidation-and-positioning.md)). This note is
the concrete "what value, packaged how" gate for that.
