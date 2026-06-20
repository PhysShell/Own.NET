# Inter-procedural ownership handoff (consume)

**Pattern:** one method takes *ownership* of a disposable — it consumes the
resource and is responsible for releasing it (`Archive(Stream source)` copies,
then `Dispose()`s). Callers hand the resource over. Two real bugs cluster around
this shape:

1. **use-after-handoff** — the caller touches the resource after passing it to
   the consumer, which has already disposed it (`Run`).
2. **leak** — a resource is acquired but neither disposed nor handed to a
   consumer on some path (`Leak`).

This is the everyday version of Rust's *move*: passing an owned value to a
function that takes it by value. It shows up wherever a method's contract is
"give me this and I'll own it" — `Stream`/`HttpContent` consumers, builders that
take ownership of their inputs, `IDisposable` sinks.

**What the checker says (on `case.own`):**

- `archive(s: Stream)` — a resource-typed by-value parameter is a **consume**
  contract: the obligation to `release` moves *into* `archive`, which discharges
  it. Clean.
- `leak()` — owned but never released or handed off → **OWN001**.
- `run()` — `s` is used after `archive(s)` consumed it → **OWN002**
  (use-after-consume).
- `run_ok()` — the same handoff, with nothing touching `s` afterwards. Correctly
  **silent**: `run_ok` never calls `release`, yet it does not leak, because the
  obligation travelled to `archive` via its *contract*. This no-false-positive
  on a legitimate handoff is the point — the caller is verified against the
  callee's signature, not its body.

```text
$ python -m ownlang check corpus/real-world/ownership-handoff-consume/case.own
case.own:22:7: error: [OWN001] 's' is owned but not released at end of function (leaks on at least one path)
case.own:28:7: error: [OWN002] use 's' after it was consumed
2 errors.
```

**Why it matters / the honesty caveat:** this is the **compositional /
inter-procedural island** in miniature. The cross-procedure proof — "acquire in
the caller, release in the consumer, never use after the move" — composes two
*intra-procedural* checks glued at `archive`'s contract. No whole-program
points-to is involved: the signature `consume Stream` is the cut point, exactly
as Rust's borrow checker is modular against function signatures.

As with every corpus case, `case.own` is a faithful hand reduction of the C#
pattern in `before.cs` / `after.cs`, **not** C# the `.own` checker ingested —
OwnLang has no C# front-end. The corpus shows the ownership *logic* maps onto
real bugs, not that the `.own` tool scanned real C#.

**Extractor status (real C#, the `corpus-benchmark` path).** The benchmark now
catches the **leak arm** (`Leak` → `OWN001`) end-to-end: `IsOwningFactory`
recognises `File.OpenRead` as an *owned acquire* (a factory, not `new`), so the
un-disposed stream is flagged exactly as a `new`'d one would be, and the
`using var` fix stays silent. The **use-after-handoff arm** (`Run` → `OWN002`) is
still extractor-future — it needs the inter-procedural *consume* contract:
recognise that `Archive` disposes its by-value parameter, then model `Archive(s)`
as a *release* of `s` so the later `s.Length` is a use-after-release. The `.own`
reduction proves both arms today; the C# front-end catches the leak.
