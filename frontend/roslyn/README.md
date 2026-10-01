# OwnSharp Roslyn extractor (P-001 v0)

The C# half of the [P-001](../../docs/proposals/P-001-csharp-extractor.md)
pipeline: scan **real C#** and emit OwnIR facts that the existing Python core
checks.

```text
*.cs --[OwnSharp.Extractor (Roslyn)]--> facts.json --[python -m ownlang ownir]--> OWN001 @ C# location
```

## What it does (v0)

Type-aware (P-014 Tier A): all inputs are parsed into one `CSharpCompilation` with
the runtime's framework references, and a `target += handler` is an event
subscription only when the `SemanticModel` binds the left side to an event — so
`sum += value` (arithmetic) is not a leak. Each is marked `released` iff a matching
`target -= handler` exists in the same class. When the left side's declaring type
is an unresolved external reference, it surfaces as an OWN050 "leakage analysis
skipped" note, never guessed as a leak. Still fact-only and intraprocedural; the
verdict (OWN001) comes from the core, not from here — there is one checker, not two.

## Run

```bash
dotnet run --project OwnSharp.Extractor -- samples/CustomerViewModel.cs samples/OrdersViewModel.cs -o facts.json
python -m ownlang ownir facts.json
# -> CustomerViewModel.cs:9: error: [OWN001] event 'bus.CustomerChanged' ... (leak)
#    (OrdersViewModel unsubscribes in Dispose -> nothing reported)
```

### Inputs: files, directories, `.csproj`, `.sln`

Inputs may be `.cs` files, directories (walked recursively, skipping `bin`/`obj`/
generated), a **`.csproj`**, or a **`.sln`** — so you can hand the extractor a
project or solution the way the borrowed roslyn-tools CLI shape advertises:

```bash
dotnet run --project OwnSharp.Extractor -- App.csproj -o facts.json     # positional
dotnet run --project OwnSharp.Extractor -- --project App.csproj -o facts.json
dotnet run --project OwnSharp.Extractor -- --solution App.sln -o facts.json
dotnet run --project OwnSharp.Extractor -- extract --project App.csproj --out facts.json  # explicit verb
```

`extract` is an optional leading verb (the tool's one job; the bare form is the
default), and `--out` is the long twin of `-o`. The sibling verbs live where the
architecture puts them — `check` is `scripts/own-check.sh` (which chains this + the
core and accepts a `.csproj`/`.sln`), and `explain` is in the core:
`python -m ownlang explain OWN001` (or `--json findings.sarif` — the checker's
findings/SARIF output — to explain every code a run produced; note `facts.json`
holds extractor facts, not diagnostic codes). One checker: the C# tool only emits
facts.

A `.csproj` resolves to its source set by scanning the project's directory for
`*.cs` (the SDK default-compile-items behaviour) plus any concrete linked
`<Compile Include="..\Shared\Foo.cs" />` outside the project tree — while honouring
the project's explicit compile set: `<EnableDefaultCompileItems>false` switches to
include-driven, and `<Compile Remove="...">` subtracts excluded files (so the
extractor doesn't emit findings from files the project doesn't compile). A `.sln`
fans out over its member projects. This is a **dependency-free** resolution
(text/XML glob matching, no MSBuild evaluation) — enough for the common
Include/Remove forms; full MSBuild evaluation (and the project/package/reference
graph) is the `ProjectDependencies`-category work parked for DI/solution scans, not
the v0 leak extractor — see
[`docs/notes/roslyn-tools-and-cli.md`](../../docs/notes/roslyn-tools-and-cli.md).

When the input is a `.csproj`/`.sln`, the project's built `bin/` output is
**auto-added to the reference set** (the `--ref-dir` you'd otherwise pass by hand),
so a built/restored project's third-party events (WPF/DevExpress) bind to real
symbols instead of surfacing as OWN050. `--no-project-refs` opts out; an unbuilt
project just contributes nothing. Run `dotnet run --project OwnSharp.Extractor -- --help`
for the full option list.

## State protocols (`--flow-locals`, OwnIR v1)

With `--flow-locals` the extractor also lowers a **state-protocol surface** — the
first slice of [P-010](../../docs/proposals/P-010-type-disciplines.md) pillar 9 —
into the OwnIR v1 ops `move` and `borrow_mut` ([OwnIR.md §5.3](../../spec/OwnIR.md)).
(These are *state* protocols — which state an entity is in. The *obligation*
protocols of P-025 / OwnIR §8 are a different mechanism with a similar name.)
It is recognised by two attributes matched by **name**, so a domain carries no
dependency on Own.NET:

```csharp
[ProtocolToken]                                   // a state: a ref struct over the entity
public readonly ref struct ApprovedOrder
{
    private readonly Order _order;
    internal ApprovedOrder(Order order) => _order = order;
    public void Ship(DateTime at) => _order.MarkShipped(at);   // a transition: spends the token
}

public static class OrderProtocol
{
    [ProtocolRegion]                              // a region entry: (entity, callback)
    public static void WithApproved(Order order, ApprovedRegion body) { /* check, then */ body(new ApprovedOrder(order)); }
}

// a handler: no attribute, no base class, no repository — the entity EF tracks
OrderProtocol.WithApproved(order, approved =>
{
    approved.Ship(now);
});
```

Inside the callback the entity is **exclusively borrowed**: only its token may
change it, a token is spent once (use after a transition is OWN002, a copy is a
move — OWN005), and any other mention of the entity is OWN013. The verdicts are
the core's; the extractor only lowers. A complete backend — ASP.NET Core minimal
API, EF Core, SQLite — is in
[`protocol-samples/efcore`](protocol-samples/efcore), and
`python scripts/protocol_gate.py` ties every committed fact back to the C# it came
from.

**What is claimed.** The profile protects the local C# capabilities and aliases of
an entity that already exists. It does **not** protect the persisted row from
other ways of changing it: `ExecuteUpdate`, a change-tracker metadata write, raw
SQL, another process. Those belong to concurrency tokens, constraints and
transactions (two of them are pinned as stated limits under
`protocol-samples/efcore/known-gaps`).

**Refusals.** A recognised protocol construct that cannot be lowered safely is
not skipped: the extractor exits `2` and writes no facts, for the whole scan.

- *Inside a region the rule is default-deny.* Transitions, token reads, `if`,
  locals and built-in operators are read; a call, a constructor, a property
  getter, an indexer, a loop, `return` are refused — nothing states what such code
  does to the entity. Read what you need (`DateTime.UtcNow`, a logger call) before
  the region. Around a region anything goes: `try`/`catch`, `await using`, loops.
- *Admission.* The state a transition writes must have no **public** mutator on
  the entity (a public setter, or a public method reaching the same write): that
  would be a transition nobody declared.
- *Boundary.* Outside the protocol's own types, creating a token (`new`,
  `default`), calling a non-public method of the entity or the protocol, and
  writing their non-publicly-writable state are refused — one assembly or two.
  `nameof`, `typeof` and reads are mentions, not operations.
- *Source.* The protocol and its entity must be in the scan as source; one that
  arrives only as a compiled reference cannot be admitted.
- *Binding.* The scan does not read `obj/`, so usings a project only gets
  **implicitly** are not there. A region whose entity does not bind is refused;
  write the usings out in the files that open regions (or qualify the names).

## Use it on a real repo / in CI (P-013)

The two stages are chained by one orchestrator script, so you don't run them by
hand. It scans a directory (recursively, skipping `bin`/`obj`/generated files):

```bash
# from an Own.NET checkout, scan another repo's C#:
scripts/own-check.sh --format human -- /path/to/some/csharp/repo
scripts/own-check.sh --format msbuild -- .        # VS Error List format
scripts/own-check.sh --fail-on-finding -- src/     # non-zero exit on a leak
```

`--format` is the core's surface selector (the renderer lives in
`ownlang/ownir.py`, not here — one checker):

- `human` — the CLI line (default);
- `github` — `::error file=…,line=…::…` annotations on the PR diff;
- `msbuild` — `file(line): error OWN001: …`, which `dotnet build` and the
  Visual Studio Error List parse, so findings surface in-IDE with no analyzer.

**GitHub Action.** A composite action (`action.yml`) wraps the same script. A
consumer repo adds (see `examples/ci/own-check.yml`):

```yaml
- uses: actions/checkout@v4
- uses: PhysShell/own.net@main
  with: { path: ., format: github, fail-on-finding: "true" }
```

**`dotnet tool`.** The extractor alone is packable
(`dotnet pack` → `dotnet tool install --global OwnSharp.Extractor` →
`ownsharp-extract`). It emits facts only; the verdict still comes from the
Python core, so the script/Action are the complete product. For the single
command that wraps both stages into one install, see
[`OwnSharp.Cli`](OwnSharp.Cli/README.md) (alpha gate A, issue #202) —
`ownsharp check <path|.sln>`.

Why CI/CLI and not a native Roslyn analyzer: a true `DiagnosticAnalyzer` runs
in-process and would force a *second* checker in C# (or shelling out to Python
per keystroke) — a conflict with "one checker", not just effort. See
[P-013](../../docs/proposals/P-013-distribution-surface.md).

**Step-by-step usage** (terminal, Visual Studio Error List, CI) lives in
[`docs/howto-visual-studio.md`](../../docs/howto-visual-studio.md).

## Scope / honesty

This sandbox has no local `dotnet`, so the extractor is built and run only in CI
(the `wpf-extractor` job); the Python bridge + core are tested locally
(`tests/test_ownir.py`) against hand-written facts. Event subscriptions are
resolved type-aware (P-014 Tier A); resolving *external* events (WPF/DevExpress)
needs their references (P-014 Tier B, opt-in) — until then they surface as OWN050
"unchecked" notes. The IDisposable-field / local / pool detectors remain syntactic
for now (P-014 rollout: the event fact goes type-aware first).
