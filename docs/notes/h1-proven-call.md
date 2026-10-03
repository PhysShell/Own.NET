# H1 — proven calls in a state-protocol region (OwnIR v2)

Status: **landed** (owner ruling: OwnIR v2 and T0 Amendment 2 approved for H1).
Base: `main` = `1c70e867eb408d931ae3dfffd8c0b351190f6547`. Follows
[`h1-transport-stop.md`](h1-transport-stop.md), which found that the only
fail-loud transport is a version bump, and [`heap-effect-summaries.md`](heap-effect-summaries.md)
(H0), whose summaries this slice consumes.

## What changes for a C# user

```csharp
static int Twice(int x) => x * 2;

Protocol.WithApproved(order, approved =>
{
    var n = Twice(21);   // before H1: refused. Now: admitted, clean.
    approved.Ship();
});
```

| Call inside a region | Before H1 | With H1 |
|---|---|---|
| direct call, touches no entity or token, proven harmless | refusal (extractor) | **admitted** |
| same, but not proven harmless (a write, an escape, a global, Unknown anywhere) | refusal (extractor) | refusal (**core**, exit 2), naming the clause |
| a call handed the borrowed entity (`Mutates(order)`) | `use` → verdict | unchanged |
| an external, virtual, delegate or local-function call (`Console.WriteLine`) | refusal (extractor) | unchanged, same text |

## The transport

- **`proven_call`** (`site`, `callee`, `line`): a new flow op, so `OWNIR_VERSION` 1 → 2 (spec/OwnIR.md §2, §5.4).
- **`heap_effects`:** a top-level section holding the H0 source facts. It holds one record per call site (the call expression walked like a body, every variable from outside it read as `heap`) and the records of the methods those sites reach through `direct` edges.
- **The frontend decides nothing.** It emits a `proven_call` only for a call the summary layer could prove at all, meaning a call whose H0 dispatch is `direct`. The same shared classifier (`HeapEffectFacts.Dispatch`) produces both that decision and every H0 call fact.
- **Fail-loud.** A v1 core refuses a v2 document on the stamp (IR1). With the stamp stripped it refuses on the unknown op (IR4). C1 below runs the real v1 core to show both.
- **No compatibility shim** in either direction: a v2 core refuses v1 facts.

## The decision

The decision is made in the core and only there: `_admit_proven_calls` in `ownlang/ownir.py`, ported in `own-bridge/src/proven.rs`.

1. **When:** at the head of `to_module` / `lower_full`, before any function is lowered. The pass walks every function body through `then`/`else`/`body`, so no lowering path can carry a `proven_call` past it.
2. **The predicate:** `heap_effects.site_verdict` / `harmless`. It lives in the shared summary layer, not in typestate code.
3. **Strict on purpose:** a reference returned without an alias is still refused (`returns == []`). Unknown fails every clause it reaches.

Predicate v1. A site is admitted iff all of these hold:

- the site record exists and calls `callee` directly;
- every call in the site is `direct` to a summarized method, and each such method is harmless;
- the site's own solved summary is harmless.

A summary is harmless iff:

- every parameter and the receiver are at most `borrow`;
- `writes.instance`, `writes.static` and `writes.indirect` are all `none`;
- `returns` is `[]`.

Refusals are `OwnIRError`, with identical text in both engines, in this order (spec/Bridge.md BR-L14):

1. a malformed `site` or `callee`;
2. a `proven_call` outside a region;
3. no `heap_effects` section;
4. a malformed section;
5. no site record;
6. a site that is not proven harmless.

## Evidence

**Kill fixtures.** Real C# files in `frontend/roslyn/protocol-samples/cases/H1*.cs`; the facts are committed as `typestate_cs_h1*`.

| Case | Result |
|---|---|
| `Twice(21)` | admitted, clean |
| A → B → pure | admitted, clean |
| pure SCC (`Even` ⇄ `Odd`) | admitted, clean |
| `TouchesGlobalState()` | refused: `writes.static is may` |
| A → B → global | refused: `writes.static is may` |
| polluted SCC (`Ping` ⇄ `Pong` writes) | refused: `writes.static is may` |
| A → `Console.WriteLine` | refused: `writes.instance is unknown` |
| `Fill(buffer)`, outer array | refused: `parameter 0 is borrow_mut` |
| `Mutates(order)` / `Escapes(order)` | OWN013, as before H1 |
| R9 backdoor (`Backdoor.AnnotateLast()`) | refused, by the core now: `writes.instance is may` |
| R18 `Console.WriteLine`, R19 interface call | refused by the extractor, unchanged |

**Compatibility controls** (`tests/test_proven_call.py`):

- **C1, old core on new facts.** `ownlang/` at `1c70e867` is taken out of git history and run on the extractor's v2 facts. It exits 2 on `schema v2, but this core understands v1`. With the stamp stripped it exits 2 on `unknown OwnIR flow op 'proven_call'`.
- **C2/C3, missing or malformed evidence.** Eleven documents, each derived from the real H1a facts by one corruption, are refused. The Layer 2 goldens pin each text, and Rust replays them byte for byte. The corruptions:
  - no section;
  - no site record;
  - `site` is not a string;
  - empty `callee`;
  - the op outside the region;
  - a malformed section;
  - the wrong callee;
  - no callee record;
  - an Unknown callee;
  - an Unknown site;
  - a virtual call inside the site.
- **C4, Unknown is poison.** A predicate that reads Unknown as harmless admits the transitive-Unknown fixture and both Unknown-derived documents. The real predicate refuses all three, so the pinned refusals go red under the mutant. The same mutant in the Rust port turns the Layer 2 replay red.
- **C5, the op cannot be dropped.** Dropping the admission pass, or dropping the op from the facts, turns the four refused kill fixtures clean. Both differ from the pinned ledgers. The Rust mutant with no `admit` call is caught by the replay.

**Parity.**
- The protocol gate's 29 C#-derived documents are byte-identical on both public CLIs.
- The Layer 2, summaries, verdict, CLI, repro and validation ledgers are regenerated at v2 by their own writers and replayed by Rust.
- The H0 sidecar goldens are unchanged.

## Not in this slice

- logger, BCL or annotation summaries: `Console.WriteLine` stays refused;
- devirtualization;
- property getters, constructors and operators inside a region: still refused by the extractor;
- typed write targets, which would be needed to admit a write to state that is provably not the entity's type family;
- DB-side mutation gaps.
