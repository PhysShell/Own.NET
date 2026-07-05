# P-026 — Project resource model files (declarative acquire/release/capture)

- **Status:** draft
- **Depends on:**
  - [P-001](P-001-csharp-extractor.md) — the Roslyn extractor → OwnIR seam this
    proposal feeds; it adds a new *fact producer*, not a new fact shape.
  - [P-014](P-014-semantic-resolution.md) — the project-local `SemanticModel`
    resolution this proposal reuses verbatim: a model entry is bound to a real
    symbol the same way a bare `+=` is bound to a real `IEventSymbol` today, with
    the same honest-skip discipline (unresolved → **OWN050**, never a guess).
  - `ownlang/ownir.py` `_prelude_resources()` (the built-in `Subscription` /
    `Timer` / `Disposable` / `PooledBuffer` table, lines ~801-821) — the existing,
    but **compiled-in**, form of exactly this idea. This proposal externalizes the
    *extractor-side* half of that table (which real C# call sites feed a kind),
    not the core lowering, which is untouched.
  - [P-015](P-015-configuration-surface.md) — the sibling config surface
    (check on/off, severity). Deliberately **not the same file**: see
    *Relationship to P-015* below.
  - [P-024](P-024-security-audit-profile.md) — the precedent this proposal must
    not repeat. See *Relationship to P-024* below.
- **Strategy hub:** [`docs/ROADMAP.md`](../ROADMAP.md).

## Motivation

Every resource kind Own.NET knows about today — `Subscription` (`event +=`/`-=`),
`Timer` (`DispatcherTimer.Start`/`Stop`), `Disposable` (`new` / `Dispose`),
`PooledBuffer` (`ArrayPool.Rent`/`Return`) — is recognised by a **hardcoded C#
syntax classifier** inside `frontend/roslyn/OwnSharp.Extractor/Program.cs` (a
single ~4,400-line file; see the split deferred in
[`consolidation-and-positioning.md`](../notes/consolidation-and-positioning.md)).
The mapping from "this call is an acquire of that kind" to an OwnIR fact lives in
C# `if`/`switch` logic, not in data.

That is fine for patterns common enough to justify a core classifier (an `event`,
`ArrayPool<T>`). It breaks down for the pattern every real codebase has at least
one of: an **in-house** acquire/release pair that is semantically identical to
`Subscribe`/`Dispose` but syntactically invisible to the extractor —
`ConnectionFactory.Open()` / `Connection.Close()`, `Registry.RegisterCallback()` /
the returned token's `.Unregister()`, a legacy `EventBus.Subscribe(...)` that
predates `IObservable<T>`. Today the only way to catch a leak of *that* resource
is to add a new hardcoded classifier to the extractor and cut a new Own.NET
release — the exact "teach the analyzer your project's `OpenDbConnection()`
convention" capability Coverity ships as **custom models**, which Own.NET has no
equivalent of.

This is a real gap, not a nice-to-have: the fleet's own real-world corpus already
has cases whose bug class (a project-local `Close`/`Dispose` convention Own.NET
doesn't know) would be a model-file entry rather than a new core classifier, if
this surface existed.

## Scope

A discovered, versioned, project-local file — working name `own.models.yaml`
(location/format TBD, see *Open questions*) — that declares **additional**
acquire/release/capture sites for the existing OwnIR resource vocabulary, in
terms of real bound symbols, not source-text patterns:

```yaml
resources:
  DbConnection:
    kind: "db connection"                     # the [resource: ...] tag on a finding
    acquire:
      - method: "MyApp.Data.ConnectionFactory.Open"
    release:
      - method: "MyApp.Data.Connection.Close"
      - method: "System.IDisposable.Dispose"  # already-known BCL release still allowed

  LegacyBusToken:
    kind: "subscription token"
    acquire:
      - method: "MyApp.Messaging.EventBus.Subscribe"
    release:
      - method: "MyApp.Messaging.SubscriptionToken.Unregister"
```

Two shapes only, each mapping onto a fact the core already understands (no new
`ownlang` code path — this is purely a new fact *producer* at the extractor
edge, exactly like adding one more entry to `_prelude_resources()`, but sourced
from a project file instead of compiled in):

1. **Paired method acquire/release** — `method:` names a call by its canonical
   Roslyn symbol display string. The extractor resolves it through the same
   project-local `CSharpCompilation`/`SemanticModel` P-014 already builds (plus
   `--ref-dir` for third-party assemblies); a call site binding to that exact
   symbol emits an `acquire`/`release` OwnIR record tagged with the declared
   `kind`, indistinguishable from a hardcoded one downstream.
2. **Event-shaped add/remove pair** — for project APIs that mimic `+=`/`-=`
   semantically (a custom `Subscribe`/`Unsubscribe` pair) without being a real
   C# `event`, reusing the existing subscription-fact shape.

## Non-goals

- **Not a detection language.** Every entry is a **symbol reference resolved by
  the compiler**, never a regex or glob over source text or identifier names. An
  unresolved entry (typo, renamed method, unreferenced assembly) is skipped with
  the same **OWN050**-style advisory P-014 already uses for an unresolved event —
  never a silent guess, never a string-match fallback. This is the line that
  keeps this proposal apart from the *Own.SecurityChecks* idea P-024 permanently
  rejected — see below.
- **Not a new severity/config surface.** A project resource kind reuses the
  existing generic families (**OWN001** leak, **OWN002** use-after-release,
  **OWN003** double-release, **OWN014** region escape) with its own
  `[resource: <kind>]` tag, exactly as WPF/DI/Pool do today. No per-kind custom
  diagnostic codes, no new severity tier — that axis is P-015's.
- **Not a replacement for the built-in kinds.** `Subscription`/`Timer`/
  `Disposable`/`PooledBuffer` and the DI registration graph stay first-class,
  shipped-by-default core classifiers. Model files are strictly **additive**,
  for the project-specific long tail the fleet cannot pre-populate.
- **Not a registry or marketplace.** One file, local to the repo, under version
  control — the `.editorconfig` model, not an npm-style package ecosystem.
- **Not general aliasing or a new lifetime-ordering DSL.** No way to declare a
  custom region ladder (that stays the built-in `OWN014` ordering); the only
  expressiveness added is *which symbols count as acquire/release/subscribe* for
  a kind, not new semantics for what "leak" or "escape" means.

## Relationship to P-015

P-015 is the sibling axis, not the same file: it turns existing findings
on/off and reweights severity per **category** (`.ownrc`/`own.toml`, format TBD)
and explicitly disclaims being "a query/policy language — it is a settings
file." This proposal is squarely that disclaimed territory, deliberately kept in
its **own** file: `own.models.yaml` declares *what counts as a resource fact* (an
extractor-input concern), while P-015 decides *what to do with a fact once
emitted* (a core-output concern). They compose — a project-declared kind is just
another category name in P-015's vocabulary — but conflating the two files would
turn the settings file into exactly the policy language P-015 rejects. If P-015
ships first, unifying discovery (one nearest-config walk-up) is worth revisiting;
until then they are independent, optional files.

## Relationship to P-024 (why this is not the rejected DSL)

P-024 permanently rejected *Own.SecurityChecks* — a custom YAML DSL of
request/response matchers over banners/config, because its checks were
"regex-over-config" and "regex-over-banner": free-text pattern matching with no
semantic grounding, which is an intrinsic false-positive/false-negative
generator (a version regex misses `1.1.0`, over-fires on backports, etc.) and a
second, competing decision-maker outside the one core.

This proposal's model entries are the opposite shape: they name a symbol, which
the Roslyn `SemanticModel` either **resolves to one real, unambiguous method /
event** or does not — there is no partial match, no pattern language, no text
scanning. Precision is inherited from the same binder P-014 already trusts for
the built-in kinds; a project model entry is exactly as sound (or as silently
skipped) as a hardcoded classifier would be for the same symbol. The verdict
authority stays exactly where P-013's "one checker" discipline puts it — the
Python core, deciding leak/escape over OwnIR facts — this proposal only widens
which C# call sites *produce* those facts. Nothing about severity, wording, or
the leak/escape verdict itself is decided in the model file.

## Sketch

```text
own.models.yaml (project root)
     │ discovered + parsed by the extractor at startup
     ▼
ModelLoader: for each declared `method:` / event pair,
  resolve via the SAME project-local SemanticModel P-014 builds
  (framework refs + --ref-dir) — unresolved entry -> OWN050-style warning, skip
     │ resolved entries behave exactly like a built-in classifier hit
     ▼
existing acquire/release/capture OwnIR fact emission (unchanged)
     │
     ▼
ownlang core (unchanged): OWN001/002/003/014 over the widened fact set,
  `[resource: <declared kind>]` tag on the finding
```

No change to `ownlang/`, `spec/OwnIR.md`, or the JSON schema — a project kind is
indistinguishable, downstream of fact emission, from a built-in one. The only
new component is a small loader in the Roslyn extractor that turns YAML entries
into the same internal classifier shape `Program.cs`'s hardcoded ones already
use (a natural companion to the extractor split noted as deferred in
`consolidation-and-positioning.md` — this is one more reason that split earns
its keep once this lands).

## Open questions

1. **File location & format.** Repo-root `own.models.yaml` discovered
   independently (v0), or folded into P-015's future `.ownrc`/`own.toml` once
   that ships? Leaning: ship independently now (P-015 is still a draft stub),
   revisit unification later.
2. **Overload granularity.** Does `method: "T.M"` mean the whole method group or
   one exact overload? Real conventions (`Open()` vs `Open(string)`) may need a
   parameter-list suffix; start with "whole group," add signature narrowing if a
   real corpus case needs it.
3. **Cross-type acquire/release.** `ConnectionFactory.Open()` returns a
   `Connection`, but `release` is a method *on the returned type*, not on the
   acquiring type — same shape the built-in `Disposable` kind already handles
   (`new` on one type, `Dispose` on the value). Confirm the schema states
   acquire/release independently (as sketched above) rather than requiring a
   `release_on:` cross-reference; the built-in table's precedent says
   independent declarations are enough.
4. **Scope of the WPF component heuristic.** Do project-declared kinds
   participate in the `ViewModel`/`View`-shaped component detection P-004 uses,
   or are they type-agnostic (fire anywhere a resolved acquire/release pair is
   unbalanced, regardless of enclosing class shape)? Leaning: type-agnostic —
   the WPF heuristic is specific to the *subscription-outlives-source* escape
   judgment (OWN014), not to the ordinary leak judgment (OWN001) a custom
   resource kind mostly needs.
5. **Silent staleness.** A renamed method quietly drops its model entry to
   "always unresolved." Should the extractor emit one summary warning per run
   listing every model entry it could not bind (so CI catches drift), the same
   way an unresolved `--ref-dir` DLL is reported today?
