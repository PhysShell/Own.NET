# resource-effects Stage 2 / 2A — body-derived effects and the CFG falsifier (EXPLORATORY)

Research branch `research/resource-effects-v1`. Pre-registered in Own.NET-paperwork
`paper-eval/resource-effects/stage2a-cfg-probe-prereg-v1.json` and `stage2-body-effects-prereg-v1.json`;
evidence in `stage2a-cfg-probe-v1.json` and `stage2-body-effects-v1.json`. #304 frozen and unchanged; #382
untouched; nothing here is a production result. No frozen real witness was expected to move here (the Stage 0
narrowing), and none did.

## 1. Stage 2A: the CFG/IOperation cheap falsifier (KILLED, K6)

`frontend/roslyn/OwnSharp.CfgProbe` (research-only, never referenced by the extractor) answers the
pre-registered definite-release question over the 14 shapes in `corpus/re-cfg-probe` three ways: the
production syntax pipeline (extractor + Python reference), an IOperation walk, and a 28-line must-analysis
over `ControlFlowGraph.Create(body)` (intersection at joins, finally regions applied along leaving branches).

Tally: the CFG is strictly more precise than the production pipeline on **0 of 14** shapes (the pass
condition needed 3); the production pipeline is strictly better on 3 (the transitive consume s07, the
named-argument handoff s09, the relational site s10); 8 are equal; on s11 (reassignment) both are wrong and
the CFG would need SSA; on s12 (local function) the CFG would need a second graph inlined. KILL GATE CFG
triggers on three of its conditions; RQ-E4 is answered NO. Nothing Roslyn-specific was integrated.

The probe surfaced two SYNTAX-level gaps instead: no fresh summary for direct returns (`return new T()`,
`return Factory()`, conditional expressions of those — s08 Make2/Make3 had no record) and no receiver
release from a first-party body (s15 measured four OWN001, three of them false, and a missed OWN002).

## 2. Stage 2: E1 and E2 behind `OWEN_RE_BODY=1` (+148/-8 handwritten lines; byte-identical off)

- **E1 fresh for direct returns.** A `return` outside any try whose expression is an object creation of an
  owned disposable, a first-party disposable factory call, or a conditional of those (through parentheses
  and casts) is lowered as `acquire $ret` / `call … result=$ret` / `if` + `return $ret` — the facts
  `var r = new R(); return r;` already produces, so the core's R3/R4 decide `fresh`. An expression-bodied
  method of that shape gets a record of just that lowering.
- **E2 receiver release from a body.** An instance method of a first-party type whose body definitely
  (IsDefiniteInBody) calls this type's `IDisposable.Dispose` / `IAsyncDisposable.DisposeAsync`
  implementation on `this`, directly or through another such method, releases its receiver: `x.M()` on a
  tracked local is a `release`, and the same predicate is a consume signal in DisposesLocal. Decided by the
  resolved interface implementation, never by a name; a conditional body stays a `use`.

Measured (tests/test_re_controls.py pins the rows): s15 gives exactly the pre-registered `OWN001 x1
(RunMaybe) + OWN002 x1 (RunUse)`; `Drop(c) { c.Kill(); }` consumes. s08: Make2 and Make3 are fresh and
the callers dropping their results leak (true positives). `Make4(bool b) => b ? new R() : Make()` stays
`none`: the engine keeps INF-R3 (all returns acquired here) and INF-R4 (a forwarded call result) apart, so
a MIXED skeleton is R5 `none` (s08c isolates it: both-`new` and both-forward conditionals are fresh). That
generic engine rule (E3) is pre-registered for Stage 3 with the two-token `CreateLinkedTokenSource`
overload of the dependency source as its real witness.

Population, measured against the sub-stage 1b outputs: the six cases move only in case 2, where E1 makes
`CreateRequestMessage(...) => new HttpRequestMessage(...)` a fresh factory and three `Get*Async` callers
show an undisposed `request` (OWN001 x3). The effect is TRUE (a fresh, caller-owned object every call, so
the E1 kill condition — a borrowed-return method mis-proven fresh — is not met); whether an undisposed GET
`HttpRequestMessage` is a leak is a TYPE-MODEL question (dotnet/runtime itself never disposes them), the
same class of external knowledge as RQ-E3, recorded as UNDISPOSED_OPTIONAL and not counted as a witness.
The 82-file tree: E1 fires twice, no verdict moves. The 137-document corpus: no fact moves — a grep finds
no direct-return factory of a disposable type and no receiver method disposing `this` in it, so the corpus
cannot exercise E1/E2 (absence of shapes, not evidence of precision). Every control is unchanged.

Budget: the prereg allowed 120 extractor lines for E1+E2; the patch is 148 (the expression-bodied factory
path, which the 4A witness needs, is the excess). Recorded as a breach, not re-expected.
