# The gallery, in real C#

`examples/gallery/*.own` demonstrates each diagnostic through the abstract
`.own` DSL's generic `resource { acquire / release }` model. This directory is
the same gallery, in **real, compilable C#**, run through the actual pipeline
(`frontend/roslyn/OwnSharp.Extractor` → OwnIR → `python -m ownlang ownir`) —
not the toy language's own dataflow.

Each pair is `<NN>_<name>.bad.cs` (trips the code) / `<NN>_<name>.ok.cs` (the
fix, silent). `00_ok_clean.cs` has no bad variant, matching the `.own` file it
mirrors.

| Pair | Code | `.own` original |
|---|---|---|
| `00_ok_clean.cs` | (clean) | `examples/gallery/00_ok_clean.own` |
| `01_leak_on_error_path` | OWN001 | `examples/gallery/01_leak_on_error_path.own` |
| `02_use_after_release` | OWN002 | `examples/gallery/02_use_after_release.own` |
| `03_double_release` | OWN003 | `examples/gallery/03_double_release.own` |
| `07_use_after_handoff` | OWN002 | `examples/gallery/07_use_after_handoff.own` |
| `10_leak_in_loop` | OWN001 | `examples/gallery/10_leak_in_loop.own` |
| `11_overspan_full_view` | OWN025 | `examples/gallery/11_overspan_full_view.own` |

Verified in CI, not just "should compile": the `C# leak extractor (Roslyn) ->
OwnIR -> core` job (`.github/workflows/ci.yml`, step "Gallery C#-native bad/ok
pairs (examples/gallery/cs/)") runs every file above through the real
extractor and asserts the exact code on each `.bad.cs` and silence on each
`.ok.cs` and on `00_ok_clean.cs`.

## Why only 7 of the 12 `.own` cases have a real C# pair

Five `.own` gallery cases exercise a concept that exists in the abstract DSL's
ownership/loans model but has **no real detector on the C# side today** — this
isn't a missing example, it's a missing capability, and faking a `.cs` file
that doesn't actually trip the claimed code through the real pipeline would be
exactly the "probably compiles" dishonesty this gallery exists to avoid:

| `.own` case | Code | Why there's no real-C# pair yet |
|---|---|---|
| `04_use_after_move` | OWN005 | Needs `move`. The extractor/bridge (`ownlang/ownir.py`) never constructs a `Move` AST node — it isn't in the OwnIR flow-op vocabulary (`_FLOW_OPS`) at all, so no C# fact can reach it. |
| `05_dispose_while_view_live` | OWN008 | Needs a `borrow_mut ... as view { release ...; use view; }` conflict. `BorrowBlock`/`BorrowKind` are DSL-only AST nodes `ownir.py` never builds; the real-world analogue (return an `ArrayPool` array while a `Span` view is outstanding) lowers as a plain use-of-owner and produces **OWN002**, not OWN008. |
| `06_exclusive_while_shared` | OWN006 | Same `BorrowBlock` dependency as above — OwnIR-lowered functions never declare a `borrow`/`borrow_mut` resource member, so the core's shared-vs-exclusive lattice path can't be entered from real C#. |
| `08_stack_buffer_escapes` | OWN015 | Needs a `stack`-backed `BufferIntent` escaping via `return`. There is no `stackalloc` detector in the extractor and no buffer-kind field in any OwnIR-lowered acquire. |
| `09_untracked_call` | OWN040 | The core *can* raise OWN040, but the extractor only ever lowers **resolvable** first-party calls — an unresolvable one is dropped before it reaches OwnIR — and `check_facts` explicitly filters OWN040 out as a "synthetic-call artifact, never a real C# bug" (`ownlang/ownir.py`, belt-and-suspenders). By design, not a gap to close. |

The first four are real recall gaps (interprocedural move/borrow/stack-region
tracking through real C# — see the README's "Where it cheats" item 1 on field
escape for the same family of hole). If/when they close, the matching `.bad.cs`/
`.ok.cs` pair belongs here, verified the same way as the seven above.
