# TB-MVP-01 — Typed Builder Order vertical slice: report and verdict

**VERDICT: `GO_TYPED_BUILDER_MVP`.**

| | commit |
|---|---|
| base (`main`, H1 merged, #390) | `877ee69f28ba169c1fd68935b41f4ef26d92f186` |
| preregistration | `cf7eb01` ([`tb-mvp-01-preregistration.md`](tb-mvp-01-preregistration.md)) |
| implementation | `95d811b` |
| gate fix (clean-checkout check only) | `e946d82` |
| official run (PASS) | `e946d82a46a5` |

Sample: [`samples/OrderBackend`](../../samples/OrderBackend). Gate:
`scripts/typed_builder_gate.py`.

## Official runs

1. **Run 1 — FAIL**, at `95d811b`: `--clean-checkout --runs 2 --rust`.
   - Every step of both worktree runs passed, with 0 failures each, and the evidence digests matched across the two runs.
   - The run still failed on the gate's own "no build output in a fresh checkout" check. It reported `rust/crates/own-shadow/src/bin`, which is tracked Rust source, not .NET build output.
   - **Defect in the gate check, not in the slice.** `e946d82` narrows it to `bin/`/`obj/` beside a `.csproj`. It changes no registered expectation, and was committed before the rerun.
2. **Run 2 — PASS**, at `e946d82`: same command. Each of two fresh `git worktree`s of HEAD, with no `bin/`/`obj/`, restores, builds, generates, scans, runs the corpus and runs the acceptance twice.

   | evidence | run 1 | run 2 |
   |---|---|---|
   | `acceptance.txt` | `ba447304cdf957ee` | `ba447304cdf957ee` |
   | `corpus.json` | `62d7b100a2ebd186` | `62d7b100a2ebd186` |
   | `orderbackend.facts.json` | `e9a0c81d941d3b50` | `e9a0c81d941d3b50` |

   Both runs also equal the committed `samples/OrderBackend/evidence/*`. Full sha256:
   - `acceptance.txt` `ba447304cdf957eef3f04adb6d1d5ee7847be3d21262f221101c5e25d9a12cc3`;
   - `corpus.json` `62d7b100a2ebd18605cc121920cab4085505eaea08594c5e633adbb2db520722`;
   - `orderbackend.facts.json` `e9a0c81d941d3b501b85b2123d2383d2d1edcc6e07c690996825f18a30d4f191`;
   - generated `Order.Protocol.cs` `857f02768f6531c7e6e498af5d0528dbdbba435cb610632e2e0c2d65d5f33484`.

**Before the official run.** Three development-time gate failures were fixed in the gate's
own matching. No expectation in the registration changed:
- a comment `Starts a new Order` matched the "no entity created outside `Build()`" regex;
- the compiler names `'Order.Status'` and `'Order.Order()'`, while the gate looked for `'Status'` and `'Order'`.

## Counts

| | |
|---|---|
| generated state types | 4: `DraftOrder`, `SubmittedOrder`, `ApprovedOrder`, `ShippedOrder` |
| generated transitions | 3: `Submit`, `Approve`, `Ship` |
| generated region entries (checked refinement) | 3: `WithDraft`, `WithSubmitted`, `WithApproved` (none for the terminal state) |
| generated builder | `Order.Create().Customer(…).Build()`: 1 required field, 1 step |
| positive fixtures | 8 (P1–P8), all `[]` on both CLIs |
| negative fixtures | 20: 10 compiler, 3 extractor, 7 core (C1–C15 with C7b, C10a–c, C11a–b, C12a–b) |
| stated limits | 2 (K1 `OWN001`, K2 `[]`) |
| HTTP happy-path requests | 5 (create, submit, approve, ship, get) + 1 list |
| HTTP rejected transitions | 9, all `409`; plus 4 `404`, 2 `400` create, 16 `500 corrupt_state`, 1 `400` unknown status |
| EF tracked-identity checks | 3 at run time (`h10-*`) + 1 structural (generated tokens wrap only `order`/`_order`) |
| database persistence checks (raw SQL oracle) | 5 row-content checks (4 happy-path rows + `h11`) + 13 row-unchanged checks (9 × H9, 4 × H8) + `h12` |
| acceptance checks | 44 per run, 2 runs per gate, 2 gates |

## The transitions, with their protocol evidence (P26)

These come from the real sample's facts (`evidence/orderbackend.facts.json`). Verdict `[]` on
Python and Rust, byte-identical CLI output.

| source method | before | transition | after | OwnIR in the region | verdict |
|---|---|---|---|---|---|
| `OrderEndpoints.Create` | (none) | `Order.Create().Customer(c).Build()` | Draft | no region: creation | `[]` |
| `OrderEndpoints.Submit` | Draft | `draft.Submit(now)` | Submitted | `acquire draft`, `call DraftOrder.Submit` | `[]` |
| `OrderEndpoints.Approve` | Submitted | `submitted.Approve(now)` | Approved | `acquire submitted`, `call SubmittedOrder.Approve` | `[]` |
| `OrderEndpoints.Ship` | Approved | `approved.Ship(now, Shipping.TrackingNumber(id))` | Shipped | `acquire approved`, **`proven_call OrderBackend.Shipping.TrackingNumber(int)`**, `call ApprovedOrder.Ship` | `[]` |

**H1 used for real.** `heap_effects` holds the record of
`OrderBackend.Shipping.TrackingNumber(int)` (no writes, no derefs, no calls, inert parameter)
and the record of its call site `site:samples/OrderBackend/OrderBackend/OrderEndpoints.cs:97:36`.
The core admits the site through the unchanged H1 predicate. Nothing in the extractor, the
core or the predicate names the sample.

**Rejected fixtures.** The exact texts are in `evidence/corpus.json`:

| | stage | observed |
|---|---|---|
| C1–C6 | compiler | CS1061: `'DraftOrder'`/`'SubmittedOrder'`/`'ApprovedOrder'` does not contain a definition for the illegal transition |
| C7 | compiler | CS1061: `'ShippedOrder' does not contain a definition for 'Submit'` |
| C7b | compiler | CS0117: `'OrderProtocol' does not contain a definition for 'WithShipped'` |
| C8, C9 | core | `OWN002` |
| C10a | extractor | `'ApplyShip' of 'Order' is not public and belongs to a state protocol` |
| C10b | core | `OWN013` |
| C10c | compiler | CS0272: `'Order.Status' cannot be used in this context because the set accessor is inaccessible` |
| C11a | core | `OWN005` |
| C11b | core | `OWN013` |
| C12a | core | refused: `'…C12aHarmfulHelper.Counter.Next()': writes.static is may` |
| C12b | extractor | `a call to '…LoggerExtensions.LogInformation' inside a protocol region runs code with no stated contract` |
| C13 | compiler | CS1061: `'Order.DraftBuilder.CustomerStep' does not contain a definition for 'Build'` |
| C14 | extractor | `a protocol token 'ApprovedOrder' is created outside the protocol's own types` |
| C15 | compiler | CS0122: `'Order.Order()' is inaccessible due to its protection level` |

## H1–H18

| H | result | evidence |
|---|---|---|
| H1 Draft cannot Approve | PASS | C1 |
| H2 Draft cannot Ship | PASS | C2 |
| H3 Submitted cannot Submit | PASS | C3 |
| H4 Approved cannot Submit | PASS | C5 |
| H5 Shipped has no transition | PASS | C7, C7b |
| H6 stale Draft rejected | PASS | C8 `OWN002` |
| H7 raw Order cannot bypass | PASS | C10a (extractor), C10b `OWN013`, C10c CS0272, C14 |
| H8 invalid DB state never refines | PASS | `h8-corrupt-*` ×4, `h8-storage-strict` |
| H9 wrong HTTP transition writes nothing | PASS | `h9-*` ×9, each with the row byte-unchanged |
| H10 same EF entity tracked | PASS | `h10-same-instance-before/after`, `h10-tracked-change` |
| H11 SaveChanges persists exactly the new state | PASS | `h11-saved-exactly`: raw columns changed = `Status,SubmittedAt` |
| H12 reload refines by the persisted state | PASS | `h12-reload-refine` |
| H13 ordinary LINQ | PASS | P7, `h13-linq-*` (server-side `WHERE "o"."Status" = 'Approved'`) |
| H14 harmless helper via `proven_call` | PASS | P5, P8, the real sample's Ship region |
| H15 harmful/Unknown helper rejected | PASS | C12a (core), C12b (extractor) |
| H16 copy/alias backdoor rejected | PASS | C11a `OWN005`, C11b `OWN013` |
| H17 generator deterministic | PASS | 2 generations per gate run, byte-identical, equal to the committed file |
| H18 full runs deterministic | PASS | digests above |

## The 18 GO conditions

1. **One ordinary EF Order underlies all typed states.** One `Orders` table. Every token wraps the region's own `order` (structural check), and the tracked instance is the one transitioned (`h10-*`).
2. **Valid transitions are typed.** P2–P4, P8.
3. **Invalid transitions are absent before run time.** C1–C7b.
4. **Stale reuse is rejected.** C8, C9.
5. **A runtime-loaded Order refines safely.** P6, `h12`.
6. **Invalid persisted state cannot fabricate a state.** H8. EF Core 8's own string converter would have mapped `'7'` to an undefined value and `'approved'` to `Approved`; the generated strict converter refuses all four.
7. **The ChangeTracker tracks the same entity.** H10.
8. **SaveChanges persists correctly.** H11; `ef-update-emitted`.
9. **DbSet/LINQ stays usable.** H13.
10. **The HTTP happy path passes.** `http-*` and `oracle-*`, with a raw row after each step.
11. **Wrong runtime transitions leave the DB unchanged.** H9.
12. **H1 `proven_call` is exercised.** H14.
13. **Harmful and Unknown calls are fail-closed.** H15.
14. **The independent oracle confirms identity and persisted state.** Raw `Microsoft.Data.Sqlite`, the ChangeTracker, and exact HTTP bodies; none goes through the typed API.
15. **Generator and full runs are deterministic.** H17, H18.
16. **The clean-checkout run passes.** Official run 2.
17. **H1–H18 pass.**
18. **Foundations are unchanged.** `git diff --stat 877ee69f..HEAD -- ownlang rust spec frontend/roslyn/OwnSharp.Extractor docs/evidence/calibration scripts/perf_baseline.py` is empty. On HEAD, `protocol_gate.py --rust` gives 0 failures with 29 documents byte-identical, `heap_effects_gate.py` PASS. `tests/run_tests.py` gave rc 0 at `95d811b`; `e946d82` changes only the gate script.

## What the slice does not claim

- **Concurrency: option A, out of scope.** No concurrency token.
- **K1.** A named terminal token is `OWN001`: tokens are linear, not affine (P-010, case G6). The handlers discard the terminal token as an expression statement. Affine tokens are foundation work, not done here.
- **K2.** `ExecuteUpdate`, metadata writes, raw SQL, reflection and other processes are outside the claim, as in the profile.
- **The diagnostics' wording** is the core's generic resource wording (`IDisposable local 'draft' is used after it is disposed`). The codes are right. The words are a UX item, not changed here (foundation).
- **No BCL or logger summaries and no typed write targets were needed.** Logging and the clock stay outside the region: the clock is read before it, and nothing is logged.

**After this verdict: STOP.** No BCL summaries, typed write targets or second aggregate are
started.
