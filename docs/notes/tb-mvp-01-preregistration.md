# TB-MVP-01 — Typed Builder + ASP.NET Core + EF Core Order vertical slice: preregistration

**STATUS: REGISTERED BEFORE ANY PRODUCT CODE.** This commit holds only this document.
Everything below is binding on the implementation commit and on the official run. A
semantic change after this commit is an amendment, committed before the affected rerun.

**Base:** `main` = `877ee69f28ba169c1fd68935b41f4ef26d92f186` (merge of #390: OwnIR v2,
`proven_call`, H0 heap-effect summaries consumed by the core, T0 Amendment 2). H1 is in
`main`: `git merge-base --is-ancestor 450c39b4f79124a7a5ba169868dd768aaab8d37f 877ee69f` holds.

## P0 — accepted gates on the base

Run on `877ee69f` before this document was committed. Results are recorded in
§ *P0 results* at the end.

## P2 — kill-first answers, read off the current codebase

Each answer names the code or a probe run on the base. A probe is a throwaway copy, not part
of the repository.

1. **What Typed Builder / generator / runtime pieces exist?**
   - **The state-protocol profile** (P-010 pillar 9, first slice):
     - `[ProtocolToken]` ref struct tokens and `[ProtocolRegion]` region entries, matched by name;
     - the Roslyn lowering, `frontend/roslyn/OwnSharp.Extractor/ProtocolLowering.cs`, to `borrow_mut`, `move` and `proven_call`;
     - the boundary and admission checks;
     - core verdicts OWN002 (stale), OWN005 (copy) and OWN013 (raw entity in a region) on both engines.
   - **A hand-written EF Core backend**, `frontend/roslyn/protocol-samples/efcore`, pinned by `scripts/protocol_gate.py`.
   - **No generator exists.** P-010 says so: "What the slice does not have: a declared state graph …, a generator for the tokens, the affine view of a token (an unspent one is OWN001 today)". The efcore sample's `OrderProtocol.cs` says "written by hand (a source generator could emit this file; none exists yet)".
   - **No builder exists.**
2. **The accepted protocol annotation and API.**
   - A state is a `readonly ref struct` marked `[ProtocolToken]`, holding the entity.
   - A transition is an instance METHOD on the token. It consumes the token. A property is a read.
   - A region entry is a static method marked `[ProtocolRegion]` taking `(entity, delegate)`. It checks the runtime state, then hands the token to an in-place lambda.
   - The attributes are matched by name (`frontend/roslyn/README.md`, *State protocols*).
3. **Can a typed state view refer to the same entity without copying?** Yes. A token is a `readonly ref struct` with one `private readonly Order _order` field. It is constructed from the region entry's own `order` argument, so a transition writes that instance.
4. **Can EF keep tracking that exact entity?** Yes. The efcore acceptance checks `ef-same-instance`, `ef-change-tracked`, `ef-no-reattach` and `ef-saved` against real SQLite on the base (13/13 checks in `protocol_gate.py`).
5. **Can a valid transition change persisted state and keep the ownership guarantees?** Yes. The token writes the tracked instance, and `SaveChangesAsync` emits an ordinary `UPDATE` (efcore check `ef-update-emitted`). Inside the region, the core holds exclusivity: the `borrow_mut` lowering, OWN013 for a raw mention.
6. **Can an EF-loaded entity be refined from runtime state into a typed state?** Yes, at the region entry: a runtime check of the state, then the token. One defect sits under it, found by a probe:
   - EF Core 8's `HasConversion<string>()` throws on `'Bogus'`;
   - but it maps `'7'` to the undefined value `(OrderStatus)7`;
   - and it maps `'approved'` case-insensitively to `Approved`.

   The last is a fabricated valid state. So the registration below uses a **strict** converter. In the probe, a converter that throws a custom exception propagated **unwrapped** out of `Single`/`SingleOrDefaultAsync`.
7. **Can stale typed state be rejected after a transition?** Yes, statically: the core gives OWN002 for use after a transition (case `L1_stale_capability`) and OWN005 for a copy (`L2_copied_capability`).
8. **Do ordinary DbSet/LINQ queries stay ordinary?** Yes. No custom provider is involved: the efcore check `ef-query-translated` gives a server-side `WHERE`.

**Two facts bind the API shape, both read off the core on the base by probe.** They are
accepted semantics, not things this MVP changes.

- **F1 — tokens are linear, not affine.**
  - A transition result bound to a named local and never spent is OWN001 (case `G6_capability_not_spent`).
  - The same result discarded as an expression statement (`draft.Submit(now);`) is not acquired, so it is clean. The chained form `draft.Submit().Approve()` (case `L6b`) is clean too.
  - `_ = draft.Submit(now);` is **refused** by the lowering: "'_' (Discard) inside a protocol region is not modelled".
- **F2 — H1 works in a real project scan.** In a probe copy of the efcore backend, a pure static `int` helper called inside a region:
  - as a statement, or nested in a transition's argument list (`approved.Ship(Clock.Same(now))`), lowered to `proven_call`;
  - had its site record and callee record in `heap_effects`;
  - was admitted by the core: verdict clean.

**Also read off the extractor**, `Program.cs::IsGenerated`: the input scan **skips** `*.g.cs`,
`*.Designer.cs` and `*.AssemblyInfo.cs`. A Roslyn source generator's output never reaches
the scan at all: it lives in the compilation, not on disk. The profile, though, requires the
protocol in the scan **as source** ("one that arrives only as a compiled reference cannot be
admitted"). This decides the generator policy below.

No question has the answer "impossible". No STOP verdict applies at registration.

## Layout (exact)

```
samples/OrderBackend/
  README.md                         developer workflow (P29)
  nuget.config                      nuget.org only
  .gitignore                        bin/ obj/
  OrderBackend/                     the ASP.NET Core minimal API (Microsoft.NET.Sdk.Web)
    OrderBackend.csproj             net8.0, C# 12, Microsoft.EntityFrameworkCore.Sqlite 8.0.11
    Program.cs                      composition root (`Backend.Build`) + `Program`
    OrderEndpoints.cs               the handlers: no attribute, no reflection
    Shipping.cs                     the harmless helper used inside a region (P19)
    Domain/TypedBuilder.cs          the marker attributes (hand-written, matched by name)
    Domain/Order.cs                 the annotated entity + its state enum (hand-written input)
    Domain/Order.Protocol.cs        GENERATED, committed (see Generator)
    Data/OrdersDb.cs                the DbContext
  Acceptance/                       console runner: real Kestrel + real SQLite + oracles
  corpus/
    positive/<Case>.cs.txt + expected.json
    negative/<Case>.cs.txt + expected.json
    limits/<Case>.cs.txt + expected.json      characterized limits, pinned (not failures)
  evidence/                         written by the gate with --write, verified otherwise
frontend/roslyn/Own.TypedBuilder/   the generator: a console tool (Microsoft.CodeAnalysis.CSharp 4.9.2)
scripts/typed_builder_gate.py       the one gate: every acceptance step below, in order
```

Top-level `samples/` is new. It is not under `examples/`, which the #260 shadow sweep
scans as one document, nor under `frontend/roslyn/samples`, which other gates glob.
`frontend/roslyn/protocol-samples/efcore` stays **untouched**: it is the profile's pinned
fixture, and this is the product sample.

## Domain entity (exact)

One EF entity, `OrderBackend.Domain.Order`: `public sealed partial class`, no base class, no
interface, materialized through a private parameterless constructor.

| member | type | notes |
|---|---|---|
| `Id` | `int` | key, private setter, SQLite autoincrement |
| `Customer` | `string` | **required construction field** (`[BuilderRequired]`), private setter |
| `Status` | `OrderStatus` | **the protocol state** (`[ProtocolState]`), private setter |
| `SubmittedAt` / `ApprovedAt` / `ShippedAt` | `DateTime?` | written by the transitions |
| `TrackingNumber` | `int?` | written by Ship |

`enum OrderStatus { Draft, Submitted, Approved, Shipped }`.

**Persisted state:** column `Status`, `TEXT`, holding the exact member name (`"Draft"` …).
It goes through a **strict** converter, which is generated: `OrderStatusStorage.ToStore`
/ `FromStore`, wired with `HasConversion(...)`.
- `FromStore` accepts the four canonical names only (ordinal, case-sensitive). Anything else throws `CorruptOrderStateException(raw)`: `"Bogus"`, `"7"`, `"approved"`, `""`.
- `ToStore` of an undefined value throws too.
- No member is ever fabricated: no default, no case folding, no numeric parse.

No per-state entity classes, no parallel persistence hierarchy: one `Orders` table, one
identity.

## Declaration (the generator's input, hand-written)

```csharp
[TypedProtocol]
public sealed partial class Order
{
    [BuilderRequired] public string Customer { get; private set; } = "";
    [ProtocolState]   public OrderStatus Status { get; private set; }

    [Transition("Submit", OrderStatus.Draft,     OrderStatus.Submitted)]
    private void OnSubmit(DateTime at) => SubmittedAt = at;
    [Transition("Approve", OrderStatus.Submitted, OrderStatus.Approved)]
    private void OnApprove(DateTime at) => ApprovedAt = at;
    [Transition("Ship",    OrderStatus.Approved,  OrderStatus.Shipped)]
    private void OnShip(DateTime at, int trackingNumber) { ShippedAt = at; TrackingNumber = trackingNumber; }
}
```

A transition's hook writes only the transition's business data. **The state write is the
generator's**: the hook cannot set the wrong next state, because it does not set the state at
all.

## Generated public API (exact)

All of it is in `Domain/Order.Protocol.cs`, namespace `OrderBackend.Domain`. From the
declaration above:

| generated | shape |
|---|---|
| `partial class Order` | `internal void ApplySubmit(DateTime at)` (calls `OnSubmit(at)`, then `Status = Submitted`), likewise `ApplyApprove`, `ApplyShip`; `public static Order.Builder.CustomerStep Create()` |
| `Order.Builder.CustomerStep` | `sealed class`, private ctor: `public Order.Builder.Ready Customer(string customer)` (null → `ArgumentNullException`) |
| `Order.Builder.Ready` | `sealed class`, private ctor: `public Order Build()`, which creates `new Order { Customer = …, Status = OrderStatus.Draft }` |
| `[ProtocolToken] DraftOrder` | `readonly ref struct`, `internal` ctor: `int Id { get; }`; `SubmittedOrder Submit(DateTime at)` |
| `[ProtocolToken] SubmittedOrder` | `int Id`; `ApprovedOrder Approve(DateTime at)` |
| `[ProtocolToken] ApprovedOrder` | `int Id`; `ShippedOrder Ship(DateTime at, int trackingNumber)` |
| `[ProtocolToken] ShippedOrder` | `int Id`; **no method** |
| delegates | `DraftRegion(DraftOrder)`, `SubmittedRegion(SubmittedOrder)`, `ApprovedRegion(ApprovedOrder)` |
| `static class OrderProtocol` | `[ProtocolRegion] WithDraft(Order, DraftRegion)`, `WithSubmitted(Order, SubmittedRegion)`, `WithApproved(Order, ApprovedRegion)`. No `WithShipped`: a state with no outgoing transition gets no region, because its token could never be spent (F1) |
| `InvalidOrderStateException` | `(int Id, OrderStatus Actual, OrderStatus Required)` : `InvalidOperationException` |
| `CorruptOrderStateException` | `(string Raw)` : `InvalidOperationException` |
| `static class OrderStatusStorage` | `ToStore` / `FromStore` (above) |

- **Invalid transitions are absent.** `DraftOrder` has no `Approve` and no `Ship`, and no generated member throws "invalid transition". C1–C7 are C# compiler errors.
- **Transition return.** A transition returns the next token over the **same** `_order`. Linear tokens (F1) fix two consequences:
  - A next token bound to a named local must be spent. A token the handler does not use further is discarded as an expression statement: `draft.Submit(now);`.
  - `ShippedOrder shipped = approved.Ship(…);` is OWN001 under the accepted core. This is pinned as limit **K1**, not "fixed": affine tokens are foundation work (G6), out of scope here.

## Refinement boundary (exact)

The region entries are the only path from a raw `Order` to a token:
1. `OrderProtocol.WithX(order, x => …)` checks `order` is not null;
2. it checks `order.Status == X`, else throws `InvalidOrderStateException(order.Id, order.Status, X)`;
3. it calls the lambda with `new XOrder(order)`.

- **No unchecked cast exists.** A token's constructor is `internal`. Creating one anywhere outside the generated protocol types is refused by the lowering's boundary check (`ForgedToken` shape), and also by the C# compiler from a second assembly.
- **Corrupt persisted state never reaches refinement.** It fails at materialization with `CorruptOrderStateException`.
- **An in-memory undefined value** (`(OrderStatus)7`) never equals a required state, so refinement throws `InvalidOrderStateException`. Never a token.

## Ownership, lifetime, stale state

These are the accepted semantics, unchanged:
- Inside `WithX` the entity is exclusively borrowed (`borrow_mut`).
- The token is a linear capability. A transition moves it: use after a transition is OWN002, a copy is a move (OWN005).
- A token cannot leave the region. It is a ref struct, the C# compiler forbids capture by a nested lambda or a field, and the lowering refuses `return`, helpers that take a token, and local functions.
- There is no runtime "used" flag anywhere: stale use is a static rejection only.

## Raw entity contract (P8): chosen direction

**The raw entity may exist, but every state-changing write is rejected.**
1. **Admission.** Nothing public on `Order` writes the protocol-owned state (`Status`, `SubmittedAt`, `ApprovedAt`, `ShippedAt`, `TrackingNumber`): private setters, `internal` `Apply*`, private `On*` hooks. A public mutator would make the lowering refuse the protocol.
2. **Outside a region.** Calling `Apply*` / `On*` or writing a private setter is refused:
   - by the lowering's boundary check (`'ApplyShip' of 'Order' is not public and belongs to a state protocol`) in the same assembly;
   - and, for private members, by the C# compiler.
3. **Inside a region.** Any mention of the raw entity is OWN013.

**Stated limits, outside the claim** (the same as the profile's):
- writes that bypass the entity's C# surface: `ExecuteUpdate`, `Entry(order).Property("Status").CurrentValue = …`, raw SQL;
- reflection, `unsafe`;
- another process.

`ExecuteUpdate` is pinned in `corpus/limits` as **K2**.

**Threat model (P23).** Ordinary C# in the scanned project, written by a developer who calls
public and internal APIs. Not malicious reflection, IL rewriting, or the database itself.

## EF tracking semantics

Handlers load with an ordinary tracked query, `db.Orders.SingleOrDefaultAsync(o => o.Id == id, ct)`.
The token writes that instance. `SaveChangesAsync` detects the change (snapshot tracking, no
proxies) and writes one `UPDATE`.

**Identity proof (P4, registered equivalent).** The token's field is private and a ref
struct cannot be boxed, so `ReferenceEquals(entity, token._order)` cannot be evaluated by an
oracle that does not breach the API. The registered proof has four parts:
- (a) **structural**: the generated region entry constructs each token from its own `order` argument, and each transition from its own `_order`, never a copy or a new `Order`. The gate checks the generated syntax;
- (b) **behavioural**: `ReferenceEquals(entry.Entity, order)` holds before and after the region, and `ChangeTracker.Entries<Order>().Count() == 1` holds throughout;
- (c) **observed**: `entry.State == Modified`, and exactly the transition's properties are `IsModified`, with `Customer` unmodified;
- (d) **persisted**: after `SaveChangesAsync`, a separate raw SQL connection reads the new state.

## HTTP contract (exact)

| request | success | errors |
|---|---|---|
| `POST /orders`, JSON `{"customer":"…"}` | `201`, `Location: /orders/{id}`, `{"id":N,"status":"Draft"}` | blank or missing customer: `400 {"error":"customer_required"}` |
| `POST /orders/{id}/submit` | `200 {"id":N,"status":"Submitted"}` | see below |
| `POST /orders/{id}/approve` | `200 {"id":N,"status":"Approved"}` | |
| `POST /orders/{id}/ship` | `200 {"id":N,"status":"Shipped","trackingNumber":T}` | |
| `GET /orders/{id}` | `200 {"id","customer","status","submittedAt","approvedAt","shippedAt","trackingNumber"}` | |
| `GET /orders?status=S` | `200 [{"id","customer"}…]`, ordered by id (ordinary LINQ: `Where`/`OrderBy`/`Select`) | `S` not a canonical name: `400 {"error":"unknown_status"}` |

Errors common to every route with `{id}`:
- unknown id: `404`;
- wrong state: `409 {"error":"invalid_transition","id":N,"state":"<actual>","required":"<required>"}`, and nothing is saved;
- corrupt persisted state: `500 {"error":"corrupt_state","id":N}`, and nothing is saved.

Each transition handler does four things in order:
1. a tracked load;
2. `WithX` (refinement);
3. one transition, as an expression statement;
4. `SaveChangesAsync`.

The clock is the DI `TimeProvider`. The acceptance runner substitutes a fixed clock, so its
output is deterministic.

**Database provider:** SQLite (`Microsoft.EntityFrameworkCore.Sqlite` 8.0.11), one file per
run. **Schema:** `EnsureCreated`; there are **no migrations** (P25), and every acceptance run
starts from a fresh file. **Concurrency: OPTION A, OUT OF SCOPE.** No concurrency token. Two
requests racing on one row are not claimed correct. The README says so in its first section.

## H1 used for real (P19)

`OrderBackend.Shipping.TrackingNumber(int orderId)` is a static, pure `int` function. The Ship
handler calls it **inside** the `WithApproved` region, nested in the transition:
`approved.Ship(now, Shipping.TrackingNumber(id))`.
- **Expected facts:** one `proven_call` to `OrderBackend.Shipping.TrackingNumber(int)`, its site record, and its method record in `heap_effects`.
- **Expected verdict:** clean on both engines.

No special case exists for the sample, and no BCL summary is involved.

## Generator (P22)

`frontend/roslyn/Own.TypedBuilder` is a console tool: `dotnet run --project … -- <Order.cs> -o <Order.Protocol.cs>`.
- **Input:** it parses the one input file **syntactically** (no semantic model, no compilation). It refuses (exit 2, one line naming the defect) a declaration that is:
  - not one `[TypedProtocol]` partial class;
  - missing exactly one `[ProtocolState]` property of an enum declared in the same file;
  - holding a transition whose states are not members of that enum;
  - holding a transition name used twice, or a state with two outgoing transitions under one name;
  - holding a `[BuilderRequired]` property that is not `string` or another non-nullable type it can pass through.
- **Output order:** states in enum order, transitions in declaration order, builder steps in declaration order.
- **Output bytes:** `\n` newlines, UTF-8 without BOM, no timestamp, no tool version, no absolute path.
- **File name:** `Order.Protocol.cs`. It is not `*.g.cs`, because the scan skips those and the protocol must be scanned as source. Its header reads "Generated by Own.TypedBuilder from Order.cs — do not edit; regenerate", without the word auto-generated.
- **Policy: the generated file is COMMITTED.** It is inspectable, and the extractor reads it. It is not regenerated at build time: no MSBuild hook, so `dotnet build` stays hermetic.
- **The gate:**
  - generates twice into two clean temporary directories;
  - requires the two outputs byte-identical (H17);
  - requires them byte-identical to the committed file.

## Test mechanisms

**Compile-negative / protocol corpus (P17).** Each `corpus/<kind>/<Case>.cs.txt` is a handler
file. The gate stages it **alone** into a fresh copy of the `OrderBackend` project. Then, by
stage:

- **`compiler`:** `dotnet build` must fail, every error must be the expected `CSxxxx` in the staged file, and the expected member name must be in the message.
- **`extractor`:** the build succeeds, and the real extractor over the project file must exit 2, write no facts, and print the expected text naming the staged file.
- **`core`:** the build succeeds and the extractor writes facts. The verdict of `python -m ownlang ownir` must be the expected code set or refusal text. With `--rust <own-cli>`, the Rust CLI must give byte-identical exit code, stdout and stderr.
- **`clean`** (positive and limits marked accepted): the build succeeds, the extractor writes facts, and the verdict is `[]` on both engines.

| id | case | stage | expected |
|---|---|---|---|
| C1 | Draft → Approve | compiler | CS1061 `Approve` |
| C2 | Draft → Ship | compiler | CS1061 `Ship` |
| C3 | Submitted → Submit | compiler | CS1061 `Submit` |
| C4 | Submitted → Ship | compiler | CS1061 `Ship` |
| C5 | Approved → Submit | compiler | CS1061 `Submit` |
| C6 | Approved → Approve | compiler | CS1061 `Approve` |
| C7 | Shipped → any (`approved.Ship(…).Submit(…)`) | compiler | CS1061 `Submit` |
| C7b | a Shipped region (`OrderProtocol.WithShipped`) | compiler | CS0117 `WithShipped` |
| C8 | stale Draft after Submit | core | `["OWN002"]` |
| C9 | stale Submitted after Approve | core | `["OWN002"]` |
| C10a | raw `order.ApplyShip(…)` outside a region | extractor | `'ApplyShip' of 'Order' is not public and belongs to a state protocol` |
| C10b | raw entity mention inside a region | core | `["OWN013"]` |
| C10c | raw `order.Status = …` | compiler | CS0272 `Status` |
| C11a | token copy, both used | core | `["OWN005"]` |
| C11b | entity alias inside a region | core | `["OWN013"]` |
| C12a | helper writing a static counter inside a region | core | refusal `… writes.static is may …` |
| C12b | logger call inside a region | extractor | `… LoggerExtensions.LogInformation' inside a protocol region runs code with no stated contract` |
| C13 | builder `Build()` without `Customer` | compiler | CS1061 `Build` |
| C14 | forged token `new DraftOrder(order)` | extractor | `a protocol token 'DraftOrder' is created outside the protocol's own types` |
| C15 | `new Order()` | compiler | CS0122 `Order` |

| id | positive case (verdict `[]`, both engines) |
|---|---|
| P1 | create a Draft through the builder, `Add`, save |
| P2 | Draft → Submitted |
| P3 | Submitted → Approved |
| P4 | Approved → Shipped |
| P5 | harmless helper inside the region (`proven_call` present in the facts) |
| P6 | EF tracked load + refinement + transition + save |
| P7 | ordinary LINQ (`Where`/`OrderBy`/`Select`) before refinement |
| P8 | the full chain inside one region, with named intermediate tokens all spent |

| id | limit (pinned so it is stated, not discovered) | expected |
|---|---|---|
| K1 | named terminal token never spent (`ShippedOrder shipped = approved.Ship(…)`) | `["OWN001"]` (linear tokens, G6) |
| K2 | `ExecuteUpdate` writes `Status` past every token | `[]` (outside the claim) |

The case texts are exact as written above. A case whose result differs from its row is an
acceptance failure. It is never re-labelled after the fact.

**The real sample itself.** The extractor runs over `samples/OrderBackend/OrderBackend/OrderBackend.csproj`
with `--flow-locals`:
- the facts must hold a region in each of the Submit, Approve and Ship handlers, plus the Ship `proven_call`;
- the verdict must be `[]` on both engines;
- the facts are pinned, JSON-equal, as `evidence/orderbackend.facts.json`.

**Runtime acceptance (`Acceptance/`).** It runs the real `Backend.Build` on Kestrel at
`127.0.0.1:0`, with a fresh SQLite file and a fixed `TimeProvider`. Its oracles are
independent of the typed API:
- **Persisted state:** a raw `Microsoft.Data.Sqlite` connection reading `SELECT … FROM Orders WHERE Id = $id`. Not EF, not the typed API.
- **Identity:** the ChangeTracker, as in *EF tracking semantics*.
- **HTTP:** status code and response body, compared to the contract above.
- **Database unchanged:** a whole-row snapshot before and after.

Every check prints one line `ok[<id>]: …` or `FAIL[<id>]: …`. The printed text contains no
port, path, time or GUID. Exit 0 only when every check holds.

## Hostile controls H1–H18 (bindings)

| H | bound to |
|---|---|
| H1 | C1 |
| H2 | C2 |
| H3 | C3 |
| H4 | C5 |
| H5 | C7, C7b |
| H6 | C8 |
| H7 | C10a, C10b, C10c (+ C14) |
| H8 | acceptance: raw-SQL `'Bogus'`, `'7'`, `'approved'` rows → every route `500 corrupt_state`, rows unchanged; EF load throws `CorruptOrderStateException` |
| H9 | acceptance: approve Draft, ship Draft, ship Submitted, submit Approved, submit/approve/ship Shipped → `409`, rows byte-unchanged |
| H10 | acceptance: identity proof (b)+(c) on a transition run outside HTTP |
| H11 | acceptance: after `SaveChangesAsync`, the raw row equals the expected one, column by column; the transition's columns change, the others do not |
| H12 | acceptance: a new context reloads the row, `WithX` for the persisted state admits, and `WithX` for any other state throws `InvalidOrderStateException` |
| H13 | P7 + acceptance: `GET /orders?status=Approved`, and `ToQueryString()` holds a server-side `WHERE` on `"Status"` |
| H14 | P5 + the real sample's facts (`proven_call` to `Shipping.TrackingNumber`) + clean verdict |
| H15 | C12a (core refusal), C12b (extractor refusal) |
| H16 | C11a, C11b |
| H17 | generator: two clean generations byte-identical and equal to the committed file |
| H18 | two full gate runs: the acceptance transcript and the gate's evidence files must be byte-identical (sha256 compared) |

**HTTP happy path (P15):**
1. `POST /orders` gives `Draft`;
2. `/submit` gives `Submitted`;
3. `/approve` gives `Approved`;
4. `/ship` gives `Shipped`, with tracking number `Shipping.TrackingNumber(id)`;
5. `GET` gives `Shipped`.

All five run against one database. After each step, the raw SQL oracle must read the state the
response claims.

## Deterministic outputs

The gate's verdict line and three evidence files (written by `--write`, compared otherwise)
are deterministic:
- `evidence/orderbackend.facts.json`;
- `evidence/corpus.json`, one entry per case: stage, expected, observed;
- `evidence/acceptance.txt`, the runner's transcript.

## Official run order (P37) and acceptance verdict

After the implementation commit, `python scripts/typed_builder_gate.py --rust <own-cli> --clean-checkout --runs 2`
does all of the following:
1. creates a `git worktree` of `HEAD` in a temporary directory, with no `bin/`/`obj/` and no generated output;
2. runs every step there: restore, build, generator determinism, positive corpus, negative corpus, real-sample scan, EF + HTTP acceptance with oracles;
3. does it twice from two fresh worktrees;
4. compares the evidence bytes and transcript sha256 across the two runs;
5. prints counts.

The report goes into `docs/notes/tb-mvp-01-report.md`.

**`GO_TYPED_BUILDER_MVP`** iff all 18 conditions of TB-MVP-P38 hold, mapped as follows:
- one entity: *Domain*;
- typed API, invalid absent: C1–C7, C7b;
- stale: C8, C9;
- refinement and invalid state: H8, H12;
- tracking: H10;
- save: H11;
- LINQ: H13;
- happy path: P15;
- wrong transitions: H9;
- H1: H14;
- fail-closed: H15;
- oracle: the persisted-state and identity checks;
- determinism: H17, H18;
- clean checkout;
- H1–H18;
- unchanged foundations: no file under `ownlang/`, `rust/`, `spec/`, `frontend/roslyn/OwnSharp.Extractor/` or `docs/evidence/calibration/`, and not `scripts/perf_baseline.py`, changes in the implementation commit (`git diff --stat 877ee69f..HEAD` shows none).

Otherwise the result is one of the STOP verdicts of TB-MVP-P36. The failing case is preserved, the
reason is classified, and no prerequisite is built inside this slice.

## P0 results

Run on `877ee69f28ba169c1fd68935b41f4ef26d92f186`, a clean tree except for this document, before this commit:

| gate | result |
|---|---|
| `python tests/run_tests.py` | rc 0, zero `FAIL` lines |
| `cargo test --no-fail-fast` (`rust/`) | rc 0, 51 test binaries, 290 passed, 0 failed |
| `python scripts/protocol_gate.py --rust rust/target/debug/own-cli` | 0 failures |
| `python scripts/heap_effects_gate.py` | PASS: samples sidecar, 50 inertness runs |
| `ruff check .` | all checks passed |

The `protocol_gate.py` run covered 28 cases, 19 lowering refusals, 5 compiler rejections, 5 same-assembly programs, 4 unrelated programs, 24 efcore checks, and 29 documents byte-identical on both CLIs.
