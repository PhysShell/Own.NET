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
| **A** | `dotnet tool` one-command CLI | ◑ **partial** — the *extractor* is `PackAsTool` (`ownsharp-extract`, P-013); the core is Python. The delightful `ownsharp check MyApp.sln` single tool isn't packaged. | Wrap extractor+core into one `dotnet tool` (or a self-contained CLI) that takes a `.sln`/dir and prints findings. |
| **B** | GitHub Action | ✅ **built** — `action.yml`: `path`/`severity`/`format` (`github` / `msbuild` / `human` / `sarif`), purple shield branding. Matches the "stupidly simple YAML" bar. | Publish to Marketplace; pin the 6-line usage in the README. |
| **C** | SARIF / PR annotations | ✅ **built** — SARIF 2.1.0 + GitHub annotations + reachability/evidence (P-015). | — |
| **D** | 5 core diagnostics | ✅ **built, well past** — OWN001/002/003, OWN014, DI001–005, POOL001–005, WPF001–005 (catalog). The comment's `SUB001/SUB002/TMR001/DISP001/DI001` all exist *semantically*; the `SUB/TMR/DISP` catalog rename is the deferred consolidation item, not new work. | (naming only) land the catalog rename with the OwnIR-v1/profile-label work. |
| **E** | 10 bad/ok examples | ✅ **built** — 12 test-pinned gallery cases (`examples/gallery/`, incl. `00_ok_clean`) + extractor samples. | Add `.cs`-native (not `.own`) bad/ok pairs for the C# audience. |
| **F** | 3 real-world case studies | ◑ **partial** — one honest mining write-up (`real-world-mining.md`: Dapper, CsvHelper, **ScreenToGif** flagship `VideoSource` + two `SystemEvents` leaks, all TPs, clean on disciplined libs) + a 20-case `corpus/real-world/`. Raw material for 3 studies exists; the *packaged* studies don't. | Write 3 `bad → fixed → what others miss → how Own reports it` studies from existing finds. |
| **G** | suppression + false-positive policy | ◑ **partial** — `[OwnIgnore("reason")]` designed (P-004), project-wide config is P-015 (draft); precision behaviour is strong & documented ("no FP from `using`"). | One consolidated user-facing page: suppression mechanism + explicit FP policy. |

**Plus the front door (not in A–G but the real blocker):** `README.md` is now
bilingual (English default + a `README.ru.md` variant), but still `# OwnLang — PoC` —
deep, research-framed, no wedge landing. There is **no 20-second landing /
copy-paste install / Action quickstart** at the top. Per the comment's own
open-source-path list (README-in-20s → copy-paste → bad/ok → Action → SARIF →
suppression → "why not Sonar/CodeQL"), this is the highest-leverage missing piece.

## Honest verdict

**The engine is past alpha on *capability* (D/E strong, B/C built). The gap to
"showable" is *packaging and presentation*, not analysis power:**

1. a single `ownsharp check MyApp.sln` tool (**A**);
2. a wedge landing README + copy-paste quickstart (front door);
3. three packaged case studies from finds we already have (**F**);
4. one consolidated suppression / false-positive page (**G**).

None of those is research; all are the difference between "interesting PoC" and
"people install it." That ordering *is* the day 1–30 milestone.

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

- **Days 1–30 — make the .NET alpha tasty:** close A, the README front door, F, G
  (B/C/D/E already done). Suppression UX + bad/ok corpus polish.
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
