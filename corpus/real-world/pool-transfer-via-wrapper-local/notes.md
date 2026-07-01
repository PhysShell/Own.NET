# pool-transfer-via-wrapper-local

A rented `ArrayPool<T>` buffer handed to a **wrapper object bound to a local**, where that local
then **leaves the method** — `var w = new Wrapper(buf); return w;` / `Sink(m, w);` — is an ownership
**transfer** (the wrapper carries the buffer out and is responsible for `Return`), not a leak here.
Generalises the existing direct `return new Wrapper(buf)` / `_field = new Wrapper(buf)` transfer to
the one-extra-hop case an intermediate local introduces.

Mined on **StackExchange.Redis** (2026-07-01 oracle sweep):

- `Lease<T>.Create` — `var arr = ArrayPool<T>.Shared.Rent(length); var lease = new Lease<T>(arr,
  length); … return lease;`
- `RedisServer` scan — `keys = ArrayPool<RedisKey>.Shared.Rent(count); … var r = new ScanResult(
  cursor, keys, count, true); SetResult(message, r);`

Both were false `OWN001` "rented but never returned" — the buffer is transferred to `Lease`/
`ScanResult`, which owns the `Return`.

- **before.cs** — the buffer is wrapped into a **method-scoped** `Holder` that is dropped (never
  disposed / returned / handed out) → the buffer genuinely leaks → `OWN001` (the bug is caught; the
  transfer exemption must **not** cover a wrapper that never leaves the method).
- **after.cs** — the `Holder` local is **returned** → the buffer transfers out with it → **clean**.

## Recognition rule

`PassedToEscapingCtor` already exempts a pooled buffer passed to a constructor whose result is the
direct `return` value or is assigned to a real field. `WrapperLocalEscapes` adds the one-extra-hop
case: the `new Wrapper(buf)` is bound to a **local** `w`, and `w` provably leaves the method —
`return w`, `<field> = w`, or `w` handed as a **call argument**. The Codex one-level rule is
preserved for the non-escaping case: a wrapper local that stays method-scoped is a borrow and the
buffer still leaks.

## Honesty caveat

Precision-first, mirroring the direct-transfer rule: we cannot prove the wrapper actually `Return`s
the buffer, so a wrapper that escapes but silently drops the buffer would be a (rare) missed leak.
The `w`-as-call-argument signal is the loosest — a `Sink(w)` that merely reads `w` and drops it would
be exempted — but handing a buffer-owning wrapper to a call is a transfer in idiomatic pooling code,
and erring toward no-false-positive matches the existing transfer stance.

To stay sound against a **reused local** (Codex P2), the exemption is bound to the **declaration
form only** (`var w = new Wrapper(buf)`) and **bails if `w` is reassigned anywhere** — otherwise
`var w = new Wrapper(buf); w = other; return w;` (or `Sink(w); … w = new Wrapper(buf);`) would let a
`return`/call of a *different* value untrack `buf`, missing a real leak. A reused wrapper local keeps
the buffer flagged.
