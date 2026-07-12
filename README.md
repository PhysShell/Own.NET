**English** · [Русский](README.ru.md)

# Own.NET

> Own.NET finds lifetime/resource bugs that C# cannot express: WPF/event
> leaks, missing `Dispose`, DI lifetime mismatch, and pooled-buffer misuse.

*Find leaks before the profiler.* GC collects unreachable objects; Own finds
objects that should have become unreachable. `event +=` is acquire, `-=` is
release.

## Run it in CI — 6 lines

```yaml
- uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4
- uses: PhysShell/Own.NET@main  # pre-release: no tagged release yet — pin a commit SHA for reproducibility
  with:
    format: github          # inline PR annotations; use "sarif" for the Security tab
    fail-on-finding: "true"
```

Once a release ships, prefer a pinned tag (`@v0.1.0`) or the moving major tag
(`@v0`) over `@main` — see
[`docs/notes/action-marketplace-readiness.md`](docs/notes/action-marketplace-readiness.md)
for the versioning policy.

## Or point it at a repo you already have

```bash
git clone https://github.com/PhysShell/Own.NET && cd Own.NET
scripts/own-check.sh --format human -- /path/to/your/csharp/repo
```

Needs Python 3.11+ and the .NET SDK on `PATH` — nothing to build, nothing to
`pip install`. A packaged single-command CLI (`owen check`, package
`Owen.Cli`) also exists — build-and-install-locally today, not yet published
to nuget.org; see
[`frontend/roslyn/OwnSharp.Cli/README.md`](frontend/roslyn/OwnSharp.Cli/README.md)
and [`docs/notes/alpha-readiness.md`](docs/notes/alpha-readiness.md) gate **A**.

## One it actually found

A real, unmodified file from [`ScreenToGif`](https://github.com/NickeManarin/ScreenToGif) —
a `Window` subscribes to a **static, process-lifetime** event and never
unsubscribes, so the window can never be collected:

```csharp
// bad — GraphicsConfigurationDialog.xaml.cs:35
SystemEvents.DisplaySettingsChanged += SystemEvents_DisplaySettingsChanged;
// ...never `-=`'d

// fixed
SystemEvents.DisplaySettingsChanged += SystemEvents_DisplaySettingsChanged;
Closed += (_, _) => SystemEvents.DisplaySettingsChanged -= SystemEvents_DisplaySettingsChanged;
```

```text
GraphicsConfigurationDialog.xaml.cs:35: error: [OWN001] event
  'SystemEvents.DisplaySettingsChanged' is subscribed (handler
  'SystemEvents_DisplaySettingsChanged') but never unsubscribed — the source keeps
  'GraphicsConfigurationDialog' alive (leak) [resource: subscription token]
```

No `IDisposable` involved, nothing "not disposed" — a defect class Dispose/RAII
checkers (CA2213, CodeQL's `cs/local-not-disposed`, …) have no query for. Three
more real finds, one where Own.NET's verdict lines up with CodeQL/Infer# and one
consolidated suppression/false-positive policy:

- [`docs/case-studies/screentogif-videosource.md`](docs/case-studies/screentogif-videosource.md) — the flagship find, a view→view-model handler leak
- [`docs/case-studies/screentogif-systemevents.md`](docs/case-studies/screentogif-systemevents.md) — the pair above, in full
- [`docs/case-studies/dispose-agreement-with-codeql.md`](docs/case-studies/dispose-agreement-with-codeql.md) — where Own.NET, CodeQL, and Infer# agree
- [`docs/suppression-and-fp-policy.md`](docs/suppression-and-fp-policy.md) — suppressing a finding, and the false-positive policy

## Why not Sonar / CodeQL / Semgrep?

Because they already own "find bugs/vulnerabilities," backed by sales teams —
that is a fight lost to marketing budget, not merit. Own.NET's niche is
narrower and doesn't overlap where it doesn't have to: a **resource / lifetime /
effect contract checker** — who holds whom, who must release, which resource
outlives which. Full positioning, including the "same model, many skins" case
for treating WPF leaks, DI captive dependencies, and pooled-buffer misuse as one
underlying bug class:
[`docs/ROADMAP.md` — Positioning against the competition](docs/ROADMAP.md#positioning-against-the-competition-not-another-sast).

---

Everything below this line is the research-depth documentation: the analysis
model, the ownership core, codegen, and how this maps to the original design
proposals. Start here if you're evaluating the engine itself, contributing, or
just curious how "GC finds unreachable objects; Own finds objects that should
have become unreachable" is actually implemented.

`ownlang/` (the Python core described below) began as a working prototype of
the design documents' idea: a small ownership language with strict Rust-style
ownership discipline that compiles to C#. Not "Rust for C#" — more honestly, **a
static ownership checker for a small resource subset**, with flow-sensitive
analysis, a loans/permissions model, a strict call boundary, and code
generation to C#. This is the **front half** of the whole idea — exactly the
layer document №2 advised building first (annotations/subset → analyzer → IR),
and deliberately **before** a Boogie/Dafny/F\* backend. It is also, today, the
reference implementation the real C# extractor (`frontend/roslyn/`) and the
Rust port (`rust/`) are held to parity against — see
[`corpus/wpf/`](corpus/wpf/) and the case studies above for what it looks like
pointed at real code, and everything from here down for how it works.

This revision is a rework after review. What changed: an explicit
**loans + permissions** model (the owner stays `Owned`, borrows are separate
facts), **`extern fn`** with unknown calls forbidden, diagnostics split into
precise codes (including "definite" vs "maybe"), and one golden example that
lowers into **real `ArrayPool<byte>` code**. The old-to-new code mapping is in the
[Changelog](#changelog-code-renumbering) section.

---

## What it actually does today

```
.own file
   ↓  lexer + recursive-descent parser
AST  (resource + extern fn + fn)
   ↓  scope/kind resolver  (names → Symbol, classification OWNED/BORROW/PLAIN)
   ↓  collect_signatures   (extern + local fn → table of ownership effects)
   ↓  lowering
CFG  (real basic blocks, branches, merges, terminal on return, Invoke on a call)
   ↓  flow-sensitive dataflow  (var-states + active loans; union at the merge)
OWN0xx diagnostics
   ↓  codegen
C#  (emit_* templates → real .NET; try/finally on the straight-line case)
```

Everything runs with no dependencies, on bare Python 3.11+. No `rustc`, no
`dotnet` — C# is only **generated**, not compiled (there is no compiler in the
sandbox). The golden example is verified *by construction* + by the checker; you
can run it yourself via `dotnet run` (see below).

### Running it

```bash
# run from the repository root (where the ownlang/ package and examples/ live)
python -m ownlang check  examples/ok_extern_calls.own        # check
python -m ownlang emit   examples/golden_arraypool/buffer.own # check + print C#
python -m ownlang cfg    examples/bad_maybe_release.own       # dump the CFG
python -m ownlang report examples/buffer_scratch.own          # buffer report + .ownreport.json

python tests/run_tests.py                                     # cases + codegen + golden + buffer smoke
```

`check` returns a non-zero exit code when there are errors — good for CI.
`emit` **refuses** to generate C# if the `.own` has even a single error.

### What it catches — the gallery

`examples/gallery/` holds small "real-life" programs: each drops exactly one
diagnostic and carries a C# analogue in a comment. Every file is pinned to its own
code by a test (`tests/test_gallery.py`), so the demo doesn't drift from what the
checker actually does. Run the whole thing at once:

```bash
python tests/test_gallery.py
```

| File | Code | Real C# analogue |
|------|-----|--------------------|
| `01_leak_on_error_path` | **OWN001** | forgot `Dispose()` on an early-out branch |
| `02_use_after_release` | **OWN002** | touched a stream after `Dispose()` |
| `03_double_release` | **OWN003** | `Dispose()` twice |
| `04_use_after_move` | **OWN005** | used a value after handing off ownership |
| `05_dispose_while_view_live` | **OWN008** | `ArrayPool.Return` while a `Span<byte>` over the array is still alive |
| `06_exclusive_while_shared` | **OWN006** | writing through a `Span` that aliases a live `ReadOnlySpan` |
| `07_use_after_handoff` | **OWN002** | touched the buffer after a call took it |
| `08_stack_buffer_escapes` | **OWN015** | returned a `Span<byte>` over a `stackalloc` (dangling) |
| `09_untracked_call` | **OWN040** | ownership "laundered" through an opaque call |
| `10_leak_in_loop` | **OWN001** | a resource acquired every loop iteration, never released |
| `11_overspan_full_view` | **OWN025** | a full-length `buf.AsSpan()` reading past the rented length |

`00_ok_clean` — a clean happy path (rent → view → return) that lowers into
exception-safe `ArrayPool` Rent/Return.

[`examples/gallery/cs/`](examples/gallery/cs/) mirrors 7 of these 12 cases in real,
compilable C#, run through the actual Roslyn extractor → OwnIR → core pipeline
(not the `.own` DSL's own dataflow) and verified in CI. The other 5 (move/borrow/
stack-buffer/unknown-call) are DSL-only concepts with no real C# detector yet —
see that directory's README for exactly why.

`check` prints the error rustc-style — `file:line:col`, the source line itself, and
a caret under the offending name:

```text
$ python -m ownlang check examples/gallery/05_dispose_while_view_live.own
examples/gallery/05_dispose_while_view_live.own:9:13: error: [OWN008] cannot release 'b' while it is borrowed
  9 |     release b;           // freeing the backing store while `view` is alive
                  ^
```

### Business use case: WPF lifetime leaks (the `lifetimes` module)

The performance profile (`stackalloc`/pool) is a toy for the performance zoo.
Business software more often dies not because a `Span<byte>` is 7 ns slower, but
because of a zombie ViewModel: someone subscribed to a singleton event and never
unsubscribed — the window is closed, but `CustomerViewModel` lives all day,
because the event bus holds a strong reference to it. The GC is not a telepath.

The key turn: **this is already expressible with the current ownership core.** We
model the ViewModel as a scope (constructor = start, `Dispose` = end); a
subscription = `acquire` of a token, unsubscription = `release`. Then "subscribed
and never Disposed" is plain **OWN001**, and "touched after Dispose" is **OWN002**.
The new, domain-neutral piece: a `resource` now carries a `kind` tag, attached to
the diagnostic as `[resource: ...]` — the seam a WPF profile / Roslyn frontend
hooks into later, without the core knowing anything about WPF.

```text
$ python -m ownlang check corpus/wpf/zombie-viewmodel/case.own
case.own:16:9: error: [OWN001] 'customerChanged' is owned but not released at
  end of function (leaks on at least one path) [resource: subscription token]
  16 |     let customerChanged = acquire Subscription(bus);
               ^
```

**Slice #2 — lifetime regions (region escape).** This is already a *new* analysis,
not reuse. We declare regions with an ordering and attach a lifetime to the object
and to services; a strong subscription to a longer-lived source promotes the object
to that source's lifetime and it leaks — `OWN014`. It is the **ordering** that makes
it a leak: a subscription to an equal-or-shorter-lived source is clean.

```text
$ python -m ownlang check corpus/wpf/viewmodel-escapes-to-app/case.own
case.own:15:23: error: [OWN014] 'bus' (lifetime 'App') outlives the captured
  object 'CustomerViewModel' (lifetime 'ViewModel'); the strong subscription
  promotes 'CustomerViewModel' to 'App' and it leaks (no release path)
  15 |     subscribe self to bus;
                            ^
```
```ownlang
lifetime App;  lifetime Window < App;  lifetime ViewModel < Window;
fn CustomerViewModel(bus: EventBus lifetime App) lifetime ViewModel {
    subscribe self to bus;          // App > ViewModel -> promotion -> OWN014
}
```

**P-001 — real C# (not hand-reduced).** A narrow Roslyn extractor
(`frontend/roslyn/`, type-aware: project-local `SemanticModel`, see P-014) finds
`event += without -=` in real `.cs` (by semantics: `sum += value` is arithmetic, not
an event) and emits OwnIR facts; the Python bridge (`python -m ownlang ownir
facts.json`) runs them through **the same core** and produces OWN001 **at the C#
site**:

```text
CustomerViewModel.cs:9: error: [OWN001] event 'bus.CustomerChanged' is subscribed
  (handler 'OnCustomerChanged') but never unsubscribed — ... (leak)
  [resource: subscription token]
```
And a `+=` on a **static** event (e.g. `SystemEvents.*`) is no longer a token leak
but a *region escape*: the extractor lowers it to a tokenless `capture` fact, and
**the same core** produces **OWN014** (the object is promoted to process lifetime; a
matching `-=` clears the finding) — the WPF escape as a profile of the general
region model, not a separate detector (P-004 WPF005; sample
`StaticEventEscapeViewModel`). These are two pinned modelings of the same
underlying shape, not one finding changing codes: the quickstart's
`GraphicsConfigurationDialog` verdict near the top of this README is the
token-tier **OWN001** error (pinned in
`corpus/real-world/screentogif-systemevents-leak`), while the region lowering
of the same static-source pattern is pinned as **OWN014** in
`corpus/wpf/systemevents-region-escape`. An injected source (unknown lifetime) stays an
OWN001 warning — the subscription profile's deliberate down-tier (OWN001 is otherwise
an error) — until ownership modelling can prove its lifetime.

There is one core (not a second checker written in C#): the extractor only
produces facts. dotnet exists only in CI (the `wpf-extractor` job runs the
extractor over the samples end-to-end); the Python bridge is tested locally
(`tests/test_ownir.py`) against hand-written facts. The v0 scope and non-goals are
in [`docs/proposals/P-001`](docs/proposals/P-001-csharp-extractor.md).

`corpus/wpf/` is a self-checking corpus of real WPF patterns (`before.cs`/
`after.cs`/`case.own`/expected), pinned by `tests/test_wpf.py`; the region theorem
is `tests/test_lifetimes.py` (10 cases). The full module plan (the OWN-WPF catalog,
slice boundaries, what is deferred) is in [`docs/lifetimes.md`](docs/lifetimes.md).
Honestly: `case.own` is a hand reduction of the pattern (a region escape with a
**static** source the extractor already emits on its own — `+=` → `capture` →
OWN014, see `StaticEventEscapeViewModel` and `corpus/wpf/systemevents-region-escape`;
cross-procedural points-to and other region facts are still hand reductions);
`self`/`source` are the function's own scope and its parameters, with no
cross-procedural points-to.

### Golden example: a real ArrayPool

```bash
cd examples/golden_arraypool
# Here live buffer.own (source) and Program.cs (the generated process + host).
# The PoC ships no .csproj of its own; to run, wrap Program.cs in a console project:
dotnet new console -o demo && cp Program.cs demo/ && cd demo && dotnet run
# (requires the .NET SDK; the PoC sandbox has none — verified by construction, not by running)
```

`buffer.own` declares a resource `Buffer` with `emit_*` templates mapping it onto
`System.Buffers.ArrayPool<byte>`. `python -m ownlang emit` produces the `process`
method verbatim, exactly as it is pasted into `Program.cs`:

```csharp
public static void process(int size)
{
    byte[] buf = ArrayPool<byte>.Shared.Rent(size);
    try
    {
        { // mutable borrow of buf as bytes
            var bytes = buf.AsSpan();
            Fill(bytes);
        }
        { // shared borrow of buf as view
            var view = buf.AsSpan();
            Hash(view);
        }
    }
    finally
    {
        ArrayPool<byte>.Shared.Return(buf);
    }
}
```

`Main` and the `Fill`/`Hash` stubs in `Program.cs` are host code, written by hand
(`extern fn` is the host's promise; the host supplies the body). A caveat: this snippet is
**emitter output verbatim, so it is illustrative, not normative** — `AsSpan()` takes the
whole rented array (Rent may return more than requested); an honest version would write
`AsSpan(0, size)`, but the length is not available to the borrow template, a deliberate
simplification for the smoke test.

---

## The language

Deliberately tiny. The whole grammar is in the `parser.py` docstring.

```
module Demo

resource Buffer {        // a resource with acquire/release methods
  acquire rent           //   -> in C#: Buffer.rent(...)   (or the emit_acquire template)
  release give           //   -> in C#: x.give()           (or the emit_release template)
  emit_type    "byte[]"                                   // optional:
  emit_acquire "ArrayPool<byte>.Shared.Rent({args})"      //   the real lowering
  emit_release "ArrayPool<byte>.Shared.Return({0})"       //   instead of the schematic one
  emit_borrow  "{0}.AsSpan()"
}

extern fn Fill(borrow_mut Buffer);   // the host's promise: the effect of each argument
extern fn Hash(borrow Buffer);
extern fn Store(consume Buffer);     // the only way to "release" ownership outward

fn process(size: int) {
  let buf = acquire Buffer(size);    // buf: Owned<Buffer>
  borrow_mut buf as bytes {          // exclusive borrow for the duration of the block
    Fill(bytes);
  }
  Hash(buf);                         // temporary shared borrow for the duration of the call
  release buf;                       // consume; after this buf is dead
}
```

Ownership operations: `acquire`, `let y = move x`, `borrow x as y { }`,
`borrow_mut x as y { }`, `release x`, `use x`, `callee(args)`, `return x`.
Parameters come as owning (`x: Buffer`) or borrowed
(`x: &Buffer`, `x: &mut Buffer`).

---

## The model: loans + permissions

This is the key fix from review. The old state description looked like
`Owned → SharedBorrowed(n) → …`, as if a borrow *replaces* `Owned`. The reviewer
rightly called that a crutch. An important detail: **the code already**, in the
previous version, kept borrow counters separate from the owner's linear state — so
the owner never actually "lost" `Owned`. Here that is made **explicit** and named.

**Variable state** (per owned symbol) — a subset of
`{OWNED, MOVED, RELEASED, ESCAPED}`. `ESCAPED` = ownership left the function
(returned via `return` or handed to a `consume` call). The owner stays `OWNED` the
entire time it is loaned out — a borrow never overwrites the owner's state.

**Active loans** — a borrow is a first-class object `Loan(owner, binding, kind)`,
**added** when it opens and **removed** when it closes. Loans live beside the
variable states, not inside them.

**Permissions** are derived on the fly from (variable-state + active loans):

| Owner state | Permissions |
|---|---|
| `Owned`, no loans | Own + Read + Write + Drop |
| `Owned`, a shared loan | Read (Own/Write/Drop suspended) |
| `Owned`, a mutable loan | — (exclusive: the owner is unavailable) |
| `Moved` / `Released` / `Escaped` | — |

Each operation checks the right it needs and reports a precise code: `move`/`consume`
require Own (suspended by *any* loan → OWN007), `release` requires Drop
(→ OWN008), `use` of the owner requires Read (suspended by a mutable loan → OWN013),
`borrow_mut` requires exclusivity (a live shared → OWN006, a live mut → OWN011),
`borrow` is incompatible with a live mut (→ OWN012).

Because borrows are block-scoped (a loan opened in a `while` body closes there, in
the same iteration), the set of active loans is **identical** on all predecessors of
any merge — including a loop's back-edge. This is an invariant that `join()`
**checks with an assert**, rather than assuming (see the note on the OWN010 reviewer
below).

---

## The call boundary: `extern fn` and a strict escape policy

The second big fix. Review: "an unknown call is a bus-sized hole." Fully agreed. Now:

* **Every call must resolve** to a declared `extern fn` or a local `fn`. An unknown
  call is a hard error **OWN040**. You can no longer tunnel the checker through
  `SomeCSharpCall(x)`.
* Each parameter carries an **ownership effect**: `borrow` (a temporary shared loan
  for the duration of the call), `borrow_mut` (a temporary exclusive), `consume`
  (takes ownership → the owner becomes `ESCAPED`), or plain (e.g. `int`).
* **Strict escape policy (MVP):** `borrow`/`borrow_mut` parameters are always
  *noescape* — the language simply has no way to express "keep the borrow." A value
  can only be released outward through `consume`/Owned. No `escapes` annotations: a
  borrow is safe by definition.

Local `fn`s also yield a signature: a `&mut` parameter → `borrow_mut`,
`&` → `borrow`, an owned resource → `consume`, anything else → plain. An incompatible
argument (a shared where `&mut` is needed; plain where a resource is needed; consume
through a borrow; the wrong arity) → **OWN041**.

---

## The rules that are checked

### Ownership / loans / permissions flow

| Code | What it catches |
|-----|-----------|
| **OWN001** | an owned resource not released on some path (a leak) |
| **OWN002** | use/… after release or consume (**definite** — on all paths) |
| **OWN003** | double release |
| **OWN004** | a borrow escapes its region (e.g. `return` of a borrow) |
| **OWN005** | use/… after move (**definite**) |
| **OWN006** | `borrow_mut` while a shared borrow is live |
| **OWN007** | move/consume/return of an owner under a live borrow |
| **OWN008** | release of an owner under a live borrow |
| **OWN009** | an operation on a resource that **might** have been released on some path (**maybe**) |
| **OWN010** | an operation on a resource that **might** have been moved on some path (**maybe**) |
| **OWN011** | `borrow_mut` while a `borrow_mut` is live (two exclusives) |
| **OWN012** | shared borrow while a `borrow_mut` is live |
| **OWN013** | direct access to the owner while it is `borrow_mut` |

### Buffers: storage policies

| Code | What it catches |
|-----|-----------|
| OWN015 | a stack-backed buffer (`stack`/`scratch`/`inline`) tries to escape the function (`return`) |
| OWN016 | a stack-backed buffer handed to a `consume` call (a move into a longer-lived owner) |
| OWN017 | a movable buffer (`pooled`/`native`) escapes — the model allows it, but PoC codegen can't yet honestly lower the escape (see below) |
| OWN019 | an inline capacity too large for a stack-backed policy (above the stack ceiling) |
| OWN021 | a `stack`/`inline` of dynamic size with no static bound (no `max =`) |
| OWN023 | a `scratch` with `fallback = forbidden`, but the size may exceed the inline limit |
| OWN024 | a buffer marked `sensitive` but not zeroed on release (no `clear = true`) |

### Unsupported / structural / boundary

| Code | What it catches |
|-----|-----------|
| OWN020 | an unsupported construct (`for`/`loop` iteration, async; `while` is supported) |
| OWN030 | unknown name |
| OWN031 | redefinition in scope |
| OWN032 | an owned resource copied without `move` |
| OWN033 | a function with a return type can reach the end without a `return` |
| OWN034 | an operation applied to a non-owned resource |
| OWN035 | return type mismatch |
| OWN036 | a cyclic ordering of lifetime regions |
| OWN040 | a call to an undeclared function (unknown calls are forbidden) |
| OWN041 | an incompatible call argument (arity / kind / plain-vs-resource) |

Lifetime regions (the `lifetimes` module): **OWN014** — an object promoted to a
longer-lived region through a strong subscription (region escape); **OWN036** — a
cycle in the `<` ordering; references to an undeclared region — **OWN030**.

The split of **definite (002/005)** vs **maybe (009/010)** is straight from review:
an error on *all* paths and an error on *some* path are different in sharpness, and
the split falls naturally out of the lattice of state sets. Each code is covered by a
test and an example in `examples/`.

---

## Where the real work lives: branch merges

Document №4 pointed the finger correctly: all the difficulty is not in the parser,
but in the **join of states at a control-flow merge**.

Each owned symbol's state is a **subset** of
`{OWNED, MOVED, RELEASED, ESCAPED}`: "what *may* be true here across all paths." At a
merge we take the **union**:

```
let c = acquire Conn(flag);
if (flag) { release c; }     // then: c -> {RELEASED}
                             // else: (empty) c -> {OWNED}
// merge: {RELEASED} ∪ {OWNED} = {RELEASED, OWNED}
// use c here             =>  OWN009 (may have been released on the then-path)
// end of function        =>  OWN001 (leaks on the else-path)
```

The checks at each operation ask "is this safe **on all** paths":
- `OWNED ∉` the state → **definite** (OWN002/OWN005);
- `OWNED ∈`, but `RELEASED`/`ESCAPED` is alongside → **maybe** (OWN009);
- `OWNED ∈`, but `MOVED` is alongside → **maybe** (OWN010);
- on exit `OWNED ∈` → OWN001.

The traversal is a worklist to fixpoint: `while` gives a back-edge, and a block is
re-evaluated until its in-state stops growing (the lattice
`{OWNED,MOVED,RELEASED,ESCAPED}` is finite, merge = union, the transfer is monotone →
it converges without widening). On a cycle-free CFG this degenerates into one pass
per block — like the old topological traversal. Diagnostics are printed in a second
pass, over the converged states (once, not on every fixpoint iteration).

### An important turn on false positives

In Snipper your prime directive was "a false positive is worse than a miss." Here it
is **deliberately inverted**. This is a safety checker: a missed use-after-release is
a real production bug, while a spurious OWN001 is just a rejected valid program. So
the analysis is intentionally conservative. The Rust borrow checker behaves exactly
the same way.

---

## Codegen to C#

Two strategies, chosen automatically.

**try/finally hoist** — for functions with no branching, no `move`, and no owned
`return`. Each resource is released exactly once, so the release is hoisted into a
`finally` (see the golden example above). The checker has **already proven**
release-exactly-once; the `finally` additionally holds that under exceptions.

**Why there is no runtime `bReleased` flag.** Review suggested, for the case of an
explicit `release` in the middle plus an auto-`finally`, introducing a runtime flag. I
**disagree for the PoC**. If the checker proved release-exactly-once on every path
(and it did), then the release is hoisted *out of* `try` — it is not duplicated in
the body — and the `finally` fires exactly once with no guard. A runtime flag only
makes sense if we don't trust the static result; and if we don't trust it, we
shouldn't ship it. So the PoC deliberately chooses **explicit release required** (not
RAII auto-release), with `finally` only as exception protection.

**faithful inline** — for functions with branching / ownership transfer, releases are
emitted exactly where they are in the source. Auto-hoisting releases out of arbitrary
control flow into a `finally` is real work; it is on the roadmap, not faked.

The `emit_*` templates on a resource turn the schematic `Resource.method()` into real
.NET (`ArrayPool<byte>.Shared.Rent/Return`, `byte[]`, `.AsSpan()`).

---

## Buffers: storage policies + logging

`stackalloc` is not an optimization in itself. It is a **storage strategy with a hard
lifetime contract**. So a buffer in OwnLang is an owned resource (release exactly
once, escape checks, borrow conflicts — all as usual), but with an explicit
**storage policy**. The model: *the user sets intent → the checker verifies
lifetime/ownership → the backend chooses or strictly enforces storage → codegen emits
safe C# → logs show the actual choice → a benchmark proves the win*. Not "the
compiler silently decided for you" — but "you set a policy, the compiler enforced it,
the runtime showed what was actually chosen."

### Modes

```
let a = Buffer.stack(256);                              // stackalloc only, fallback forbidden
let b = Buffer.stack(size, max = 1024);                 // dynamic, but with a guard
let c = Buffer.scratch(size, inline = 1024, fallback = pool);  // stack, else ArrayPool
let d = Buffer.pooled(size);                            // ArrayPool only; movable, Return required
let e = Buffer.native(size);                            // NativeMemory; unsafe, Free required
let f = Buffer.inline(128);                             // a fixed compile-time stack buffer
```

The main rule: **`stack` never falls back to the heap**; **`scratch` may**, because
the user explicitly allowed the fallback. An API that lies about memory is not an
abstraction. `stack`/`scratch`/`inline` are stack-backed → they cannot escape
(OWN015/016).

A buffer can be `move`d inside a function — ownership and the storage policy pass to
the new owner, and a `release` of the new name frees the original backing. The
namespace must be `Buffer`: `Foo.stack(...)` (a typo / foreign identifier) is
**OWN030**, not a silent allocation.

`pooled`/`native` are movable in the **ownership model** (in theory they can be
`return`/`consume`d). But **the deliverable here is a checker, and codegen only proves
the model lowers into real .NET**, without ballooning into an end in itself. There is
nothing to honestly lower an *escaping* buffer with: the value inside the function is
a `Span<byte>`, but to hand it out you need a handle (`byte[]`/`byte*`+length) the
caller will `Return`/`Free`. So the PoC **rejects** the escape of a movable buffer
(**OWN017**), rather than shipping C# that leaks or doesn't compile. Locally
`pooled`/`native` work fully (rent→borrow→release with a real
`ArrayPool.Return`/`NativeMemory.Free`). Full movable lowering (through a `byte[]`
handle or an `IMemoryOwner<byte>` wrapper) is on the **roadmap**.

### `scratch` lowers like this (this is the golden buffer example)

```csharp
byte[]? tmp_rented = null;
Span<byte> tmp_backing = stackalloc byte[1024];
Span<byte> tmp;
if (size <= 1024)
{
    OwnTrace.ScratchSelected("parse", "tmp", size, 1024, "stackalloc");
    OwnCounters.StackHit();
    tmp = tmp_backing[..size];
}
else
{
    OwnTrace.ScratchSelected("parse", "tmp", size, 1024, "ArrayPool");
    OwnCounters.PoolFallback(size);
    tmp_rented = ArrayPool<byte>.Shared.Rent(size);
    tmp = tmp_rented.AsSpan(0, size);
}
try { /* ... */ }
finally
{
    OwnCounters.Release();
    if (tmp_rented is not null)
        ArrayPool<byte>.Shared.Return(tmp_rented);
}
```

### Logging — a mandatory part, not an option

Without logs, `scratch` would become exactly the kind of "smart" abstraction that
silently picked the pool while you stare at a GC graph for three hours. So logging is
in three places:

1. **Compile-time report** (`python -m ownlang report file.own`): what the
   checker/codegen decided for each buffer — mode, inline limit, fallback, escape
   policy, clear, the generated branches and which checks passed. Printed as text and
   written to `file.ownreport.json` (handy for review/CI).

2. **Runtime trace** — the `OwnTrace.*` hook in the generated C#: which backend was
   actually chosen at a concrete `size`. Under `[Conditional("OWNSHARP_TRACE")]` — in a
   normal Release the calls are stripped out, so logging doesn't become a new bottleneck.

3. **Runtime counters** — `OwnCounters` (`ScratchStackHits`, `ScratchPoolFallbacks`,
   `ScratchPoolBytesRented`, `ScratchPoolBytesReturned`, `ScratchTotalRequestedBytes`,
   `ScratchMaxRequestedBytes`, `ScratchReleaseCount`, `ScratchForcedClears`) under
   `[Conditional("OWNSHARP_COUNTERS")]`. They answer the main question: do we really hit
   the stack often, or is the inline limit set wrong?

### Policies

A `policy` block is a reusable set of defaults; a buffer references it via
`policy =`, and inline options override it:

```
policy SensitiveScratch {
    inline_bytes     = 512;
    fallback         = pool;
    counters         = true;
    clear_on_release = true;       // zero the bytes before returning to the pool
}

fn handle(size: int) {
    let secret = Buffer.scratch(size, policy = SensitiveScratch);
    borrow_mut secret as m { Fill(m); }
    release secret;                 // codegen: secret.Clear(); then Return
}
```

### Runnable golden

`buffer_scratch_program.cs.txt` — a runnable example: the `parse` method and the
`OwnTrace`/`OwnCounters` classes are pasted **verbatim** from `python -m ownlang emit
buffer_scratch.own`, and `Fill`/`Hash`/`Main` are host code. It proves the buffer
model lowers into real .NET with a real `ArrayPool.Rent/Return`:

```bash
dotnet run -p:DefineConstants="OWNSHARP_TRACE;OWNSHARP_COUNTERS"
# parse(64)   -> the stackalloc branch (we don't touch the heap)
# parse(4096) -> the ArrayPool branch  (real Rent/Return), trace + counters in the output
```

### Where it cheats

The buffer element is fixed as `byte` (as in all examples). In a straight-line
function (no `if`/`move`/owned-return), buffers and ordinary resources lower in source
order, each into its own exception-safe `try/finally` split at the `release` point —
**but only if the lifetimes are laminar** (any pair is nested or disjoint) **and every
`release` is at the top level**: non-overlapping ones stay separate (a returns before
b is rented), nested ones nest (LIFO). A partial overlap (`let a; let b; release a; …
release b;`), a `release` inside a nested `borrow`/`if` block, or a resource consumed by
a call cannot be hoisted without distorting the lifetime / double cleanup, so such
functions lower faithful-inline (release exactly where written; no `try/finally`).
A `scratch`/`stack`/`native` of dynamic size guards an invalid (including negative)
request **before** any trace/counter, so broken input doesn't pollute the metrics. The
buffer size must be an integer — `Buffer.pooled(flag: bool)`, an owned resource, or
plain of unknown type (e.g. a copy of a borrow) as the size is **OWN018**; and `inline`
requires a compile-time literal — `Buffer.inline(n, max = …)` is **OWN021** (for dynamic
sizes there is `stack`). A plain local declared in the buffer body and used after release
is not wrapped in a hoisted `try` (otherwise it would leave the C# scope) — such a buffer
lowers inline.
Boolean settings (`clear_on_release`, `counters`, `sensitive`) and `trace` are
validated: a typo like `clear_on_release = ture` is **OWN030**, not a silent disabling
of clear on a sensitive buffer. And `sensitive = true` without `clear = true` is
**OWN024**: you marked it secret — you must zero it before the backing memory
(pool/allocator/stack frame) is reused. `counters` now also includes
`ScratchTotalRequestedBytes`/`ScratchMaxRequestedBytes` (the request distribution),
`ScratchPoolBytesReturned` (the balance with `Rented`) and `ScratchForcedClears`.
`native` stores a `byte*` (the backing, freed on release), but hands out a
`Span<byte>` view — borrows/calls see the same logical type as pooled/stack/scratch. A
borrow parameter of type `Buffer` (both in `extern` and in a **local** `fn`) renders as
`Span<byte>`/`ReadOnlySpan<byte>`, so a single `fn helper(x: &mut Buffer)` lowers into one
C# signature for all storage modes, and a call `helper(b)` compiles. The report
attributes diagnostics by buffer identity (`name#line:col`, carried across `move`
aliases), not by name in the text — two same-named buffers in adjacent scopes don't get
confused.
In a branchy function (there is an `if`/`move`/owned-return) inline mode is used: a
buffer with clean nesting gets a `try/finally`, while overlapping lifetimes, branchy
release and moved aliases get inline-release (real cleanup at the release sites, with no
hoist into `finally`; ordinary resources are inline there too — hoisting out of
arbitrary control flow is on the roadmap). A `native` of dynamic size guards a negative
request before `NativeMemory.Alloc`. Escaping movable buffers are rejected (OWN017);
full movable lowering is on the roadmap. Unknown values **and names** of settings (mode,
namespace, policy, fallback, plus the buffer option names and policy-block keys
themselves) are caught as **OWN030** — a typo in `fallback = forbidden`, `fallback = 0`
or `fallbak = forbidden` won't "leak" into the heap, it will be rejected. A repeated
option/key (`fallback = forbidden, fallback = pool`) is also **OWN030**: a conflicting
promise is not resolved by a "last one wins" rule. The benchmark matrix from the design
doc (safe vs unsafe, stack vs pool over sizes 32 B … 1 MB) is the **next layer**: the
rule "an unsafe backend is allowed only at a ≥ 10–15 % win with a disassembly
justification" sets the discipline, but running the benchmarks is outside the sandbox.
Unsafe contracts (`UNS0xx`) are not yet implemented: `native` lowers into
`NativeMemory.Alloc/Free` in an `unsafe` block, but pointer-escape checks are on the
roadmap.
Diagnostic **evidence** (the structured `note:` reachability steps some findings
carry — acquire→escape for a stack buffer that returns/consumes at OWN015/OWN016,
move→use for OWN005, and the acquire site of a leaked resource at OWN001) is exact
on a straight-line path, and on a control-flow merge when all incoming paths agree
on the same move line. The analysis keeps the **union** of per-path state, so only
when branches *disagree* on where a resource was moved does the merge keep a
representative site and label the step "moved here (on one of several paths)"
rather than naming a line only one branch took — a static merge cannot say which
path ran. (An acquire site is almost always exact: a resource is minted at one
`acquire`, so its RID has a single source line; a leaked owned *parameter* is
minted with no in-body site and so carries no acquire step.) Evidence coverage is
also partial by design: most findings still carry no slice yet (they render
exactly as before), and only the four producers above are wired so far.

---

## Changelog: code renumbering

The codes were re-laid-out into a coherent scheme. If you're looking at output from a
previous version:

| Was | Now | Note |
|------|-------|---------|
| OWN006 (catch-all borrow) | OWN006 / 007 / 008 / 011 / 012 / 013 | split into concrete violations |
| OWN002 (any use-after-release) | OWN002 (definite) + OWN009 (maybe) | split definite/maybe |
| OWN005 (any use-after-move) | OWN005 (definite) + OWN010 (maybe) | split definite/maybe |
| OWN007 (operation-requires-owned) | OWN034 | the number freed up under loans |
| OWN010 (undefined name) | OWN030 | |
| OWN011 (redefinition) | OWN031 | |
| OWN012 (copy-owned) | OWN032 | |
| OWN013 (missing-return) | OWN033 | |
| — | OWN040 / OWN041 | the new call boundary |

About the **reviewer's OWN010 "incompatible-state-at-join"**: in a block-scoped
language there can be no incompatible loans at a merge (a borrow is always balanced
inside a branch — and inside the `while` body, so a loop's back-edge carries the same
loan set too). So it is not a user-facing code, but an **assert invariant** in
`join()`. Adding a diagnostic that structurally never fires is exactly the kind of
decoration the whole effort is against. If an early exit from a borrow ever appears (a
`break` out of a body with an open loan), the assert turns into real code. (The number
OWN010 is taken by "maybe-move" in the new scheme.)

---

## Where it cheats (mandatory reading)

This is a PoC. The list of holes is deliberately explicit.

1. **The call boundary is closed, the field boundary is not.** `extern fn` + the ban
   on unknown calls (OWN040) close that "bus-sized hole": you can no longer tunnel
   ownership through an anonymous C# call. But **there are still no fields**, so "a
   borrow saved into a field/closure/timer" is not modelled — and in real C# that is the
   main source of leaks (ViewModels, events). This is the next step of escape analysis.

2. **No proofs.** This is a checker, not a verifier. No Boogie/Dafny/F\*. Soundness is
   not proven — it is argued and tested. Translation to Dafny/F\* and a proof are the
   **next layer**, not this one.

3. **`while` is analyzed** (worklist + fixpoint over the back-edge: cross-iteration
   leak/use-after-release/double-release, see `tests/test_loops.py`). But `for`/`loop`
   iteration and async are rejected for now (OWN020) — they need desugaring into `while`
   or a separate model; the CFG and worklist are ready for it.

4. **The PoC sandbox has no .NET** — the golden is verified *by construction* and by the
   checker. But **CI actually compiles and runs it** with a real compiler (the
   `dotnet-golden` job: it diffs the emit output against the host, then `dotnet run`), so
   the lowering is verified by execution — just not in this sandbox. On your machine:
   `dotnet run` in `examples/golden_arraypool`.

5. **No real type system.** Resources are nominal, `acquire` arguments are not typed,
   there is no arithmetic. The condition in an `if` is opaque text: control flow is
   modelled, not values. A call's return value is not tracked (a call as a statement; if
   a local `fn` returns a resource, it is not tracked).

6. **Shadowing is forbidden** (OWN031). Rust allows it; for the PoC the ban is simpler.

7. ~~CI actions are not pinned by commit SHA~~ — **fixed**: every `uses:` in
   `ci.yml`/`mine.yml`/`mine-on-push.yml`/`oracle.yml`/`pr-issue-validation.yml` is now a
   commit SHA with a `# vN` comment. `persist-credentials: false` is still open — SAST
   (zizmor) flags it, but the jobs are checkout + running tests, with no push and no
   secrets, so the exposure is minimal.

---

## How this maps to the design documents

| Layer from the documents | Status in the PoC |
|--------------------|--------------|
| OwnLang v0: ownership core, borrow blocks, must-release, C# codegen (doc №4) | **done** |
| OwnSharp IR: CFG + ownership facts (doc №2, Phase 2) | **done** (CFG + dataflow + loans/permissions) |
| Explicit interop boundary / escape policy (doc №2/3) | **partial** — calls are closed (OWN040/041), fields are not |
| Roslyn analyzer for C# with annotations (doc №2, Phase 1; doc №1, Option 1) | not here — an alternative frontend |
| Boogie backend / proof obligations (doc №2, Phase 3) | roadmap |
| Dafny backend (doc №2, Phase 4) | roadmap |
| F\* soundness of the core (doc №2, Phase 6) | roadmap |
| RustOwl-style IDE visualization (doc №1; doc №4) | roadmap — the CFG dump is a seed |

The nearest next step: **escape through fields** (item 1), then the **Boogie backend** —
generate proof obligations from the same CFG and run them through Z3.

---

## Related work / positioning

Honestly: **we are not the first or the best resource-leak detector for C#.** The niche
is densely occupied by mature tools, and pretending otherwise is exactly the decoration
the whole effort is against:

| Tool | What it catches | How |
|---|---|---|
| **Infer#** (Microsoft, on top of Facebook Infer) | resource leak, null-deref, thread-safety, taint | interprocedural, separation logic; over compiled `.dll`+`.pdb` |
| **CodeQL** `cs/local-not-disposed` | a local `IDisposable` without `Dispose` | dataflow over a built CodeQL database |
| **IDisposableAnalyzers** (`IDISP0xx`) | dispose / ownership-transfer | a Roslyn analyzer (syntax + symbols), in the IDE |
| **CA2000 / CA2213** (.NET SDK analyzers) | dispose before leaving scope; undisposed fields | flow-sensitive, but transfer recognition is a list of types |
| **SonarC#, PVS-Studio (V3178), ReSharper `[MustDisposeResource]`** | dispose leaks | patterns / annotations |

All of them beat us on **leak recall** over large bases: interprocedural, battle-tested,
without our "honest skip." That is the **bar**, and we acknowledge it.

**What sets us apart — the model, not the coverage.** The tools listed essentially
answer one question: *"is this `IDisposable` released?"*. Own.NET models **ownership as a
whole** in the Rust spirit — and out of that fall classes of defect that leak-only tools
don't have in their primary query:

- **double-dispose (OWN003)** and **use-after-dispose (OWN002)** — separate codes, not a
  "leak." The Infer#/CodeQL leak queries simply don't have them.
- **loans + permissions (OWN006–013)** — borrow aliasing and exclusivity
  (mutable-while-shared, etc.). No C# tool does this for `IDisposable`; C#'s `ref safety` /
  `scoped` / `Span` is escape-safety for ref/span values, not ownership of resources, and the
  overlap is almost nil.
- **region/lifetime escape (OWN014)** — promotion of an object to a longer-lived region
  (zombie ViewModel). This is lifetime analysis, not a dispose check.

The nearest "same idea, different language" is not in C# but in C++/Rust: the **C++
Lifetime profile** (Sutter / MSVC, opt-in), the experimental **lifetime safety in Clang**
(2025, inspired by Polonius), and **Polonius** itself — a Datalog formulation of Rust's
borrow check ([rust-lang/polonius](https://github.com/rust-lang/polonius)). Their facts
(`loan_issued_at` / `cfg_edge` / `loan_killed_at` / `subset`) are exactly the vocabulary
our OwnIR is written in (`acquire`/`use`/`release`/`return` + back-edge); we reproduce a
**region-based** model, just on a different engine (a Python worklist-fixpoint instead of
Datalog). Attempts at a "Rust-like C#" (such as RLC#) have been abandoned.

**And the mature detectors are an oracle for us.** Since they are strong at leak
detection, you can run them over the same code and cross-check the findings: an
intersection = high-confidence, *only-oracle* = our recall gap (what we missed),
*only-own* = a candidate FP **or** a unique catch (that very double-dispose). This is a
validation harness on top of mining — `scripts/oracle_compare.py` + the **oracle
(cross-tool)** workflow, details in [`docs/notes/oracle.md`](docs/notes/oracle.md).

> **Requirement (convention).** Every oracle run carries an accounting obligation:
> triage the `oracle-only` findings, and any case that turns out to be an oracle FP **or**
> our deliberate by-design skip — record as a pattern in
> [`docs/notes/field-notes-patterns.md`](docs/notes/field-notes-patterns.md)
> (the source file + the analyzer angle: why a naive detector is noisy while our
> escape/transfer-aware checker is correctly silent). The notebook is both a textbook of
> C# ownership/lifetime idioms and a living map of the precision frontier; it must not lag
> behind what we actually saw in other people's code.

---

## Layout

```
ownlang/
  ownlang/
    lexer.py        # tokenizer; for/loop/async lex as REJECTED (while doesn't); strings for emit_*
    ast_nodes.py    # AST dataclass nodes (resource, extern, call, effects, buffer, policy)
    parser.py       # recursive descent; the grammar is in the docstring
    buffers.py      # storage policies: modes, policy+intent resolution, validation
    cfg.py          # resolver (Symbol/Kind) + collect_signatures + lowering, Invoke
    analysis.py     # flow-sensitive dataflow: var-states + active loans + permissions
    lifetimes.py    # lifetime regions: region-escape (OWN014) + ordering validation
    ownir.py        # C# facts (OwnIR) -> core -> diagnostic at the C# site (P-001)
    diagnostics.py  # the OWN0xx codes in one place
    codegen.py      # C# codegen (emit_* templates, try/finally hoist + inline, buffers)
    report.py       # compile-time buffer report -> stdout + .ownreport.json
    __main__.py     # CLI: check / emit / cfg / report
  examples/
    ok_*.own                  # pass
    bad_*.own                 # fail with a specific code
    gallery/                  # "what it catches" — narrated examples, pinned by a test
    golden_arraypool/         # buffer.own + Program.cs (host code; .csproj not included)
  corpus/real-world/          # hand-reduced real ArrayPool bugs + expected codes
  corpus/wpf/                 # WPF lifetime bugs (zombie-VM, use-after-dispose)
  spec/                       # the NORMATIVE spec: OwnCore/Buffer/Lifetimes/Diag/Codegen
  docs/proposals/             # forward-looking RFCs: P-001 C# extractor, P-002 verif, ...
  docs/lifetimes.md           # the lifetimes module design (WPF, regions, slices)
  tests/
    run_tests.py              # analysis cases + codegen smoke + golden smoke
    test_codegen.py           # content assertions on the generated C#
    test_codegen_props.py     # a property fuzzer with an independent AST oracle
    test_gallery.py           # pins each gallery example to its code
    test_corpus.py            # pins each corpus case to its expected diagnostics
    test_wpf.py               # the WPF corpus: codes + [resource: kind] metadata
    test_lifetimes.py         # region-escape (OWN014) + lifetime-ordering validation
    test_spec.py              # conformance: every spec/ rule fires on an example
    test_ownir.py             # the OwnIR bridge: C# facts -> core -> OWN001 at the C# site
  frontend/roslyn/            # the C# extractor (Roslyn, CI-only) + .cs samples (P-001)
    OwnSharp.Extractor/        # ownsharp-extract (dotnet tool): facts only
    OwnSharp.Cli/              # owen / Owen.Cli (dotnet tool, gate A): extractor + vendored core, one install
  rust/                       # the Rust core migration (P-022): own-ir + own-syntax so far,
                               #   oracle-gated against this Python core — see rust/README.md
  pyproject.toml              # gate: ruff + mypy --strict (see below)
```

### Quality gate (ruff + mypy --strict)

Python was chosen for prototyping speed, but without types it easily hides the "forgot a
branch" class of bug (exactly what the old codegen kept producing). So the screws are
tightened, and they block CI (the `lint` job):

- **ruff** (`E,W,F,I,B,UP,C4,RUF`) — style + bugbear traps over the whole tree;
- **mypy `--strict`** on the `ownlang` package (the tests are dynamic fuzzer code, held
  only by ruff);
- **`typing.assert_never`** in every dispatch over node kinds (`lower_stmt`, `step`,
  `_stmt_inline`): a new unhandled union variant is a **type compile error**, a cheap
  substitute for an exhaustive match. Turning it on already caught a real hole — a buffer
  `let` left unclosed in the inline emitter.

Locally: `ruff check . && mypy`. This does not replace the regression net (the
fuzzer/oracle/corpus catch logic, the linter catches typos and types) — it complements it.
