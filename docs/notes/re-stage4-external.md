# resource-effects Stage 4 — where the two external effects can come from (EXPLORATORY)

Research branch `research/resource-effects-v1`. Pre-registered in Own.NET-paperwork
`paper-eval/resource-effects/stage4-external-prereg-v1.json`; evidence in `stage4-external-v1.json`.
#304 frozen and unchanged; #382 untouched; nothing here is a production result. Every arm that applies a
key uses the Stage 1 key mechanism; the difference between the arms is where the rows come from.

## 4A — the dependency source through the generic rules (BODY_PROVED)

The pinned dotnet/runtime sources (49e04fa: `CancellationTokenSource.cs`, `CngKey.Delete.cs`, `CngKey.cs`)
were extracted as first-party with the Stage 2 body rules, summarised with the Stage 3 rule E3, and the
receiver-release facts dumped declaration-side (`OWEN_RE_DUMP_EFFECTS`, research-only). Derived, with
nothing typed by hand:

- `CreateLinkedTokenSource(CancellationToken)` → fresh (E1: a conditional of two `new`s);
- `CreateLinkedTokenSource(CancellationToken, CancellationToken)` → fresh (E1 + E3: a forward to the
  one-token overload, a `new`, a cast `new`) — the overload the frozen case 2 uses;
- `CngKey.Delete()` → receiver release (E2: `Dispose();` on `this` resolves to the IDisposable
  implementation in the other partial, definite on every normal exit);
- the `params` overload stays unknown (its span twin returns a switch expression, outside E1), as
  pre-registered; zero false rows among 28 evaluated instance methods.

Fed back as a key (provenance BODY_PROVED), the derived rows reproduce the Stage 1b answer-key FACTS and
VERDICTS byte for byte on case 2, case 4 and both sensitivity twins, and give the identity-key rows on
H1–H6. So the answer key of Stage 1 is derivable from the dependency source with the rules of Stages 2–3
and no API name anywhere.

## 4B — the explicit model pack (MODELLED)

The two answer-key rows re-labelled: 2 rows, 0 code lines, under ten minutes of reading. Reproduces
Stage 1 by construction. This is the cheapest point of the frontier and the competitor every inference arm
is measured against.

## 4C / 4D / 4E — documentation, mining, naming and LLM (SUGGESTED / MINED; never applied)

The `CngKey.Delete` remarks state the terminal effect in prose ("the CngKey object can no longer be used
after the named key is deleted"; "closes the handle"); the `CreateLinkedTokenSource` page never says who
disposes the result. Mining the train set (the 137-document corpus facts) yields no candidate: it uses
neither API, and a `use` op carries no method name, so receiver releases cannot be mined from facts at all.
The name rules M1/M2 name both witness APIs — and the four hostile false candidates. The LLM of this
session (model and prompt recorded) answers all six correctly, but that evidence is unversionable.

## The provenance experiment (RQ-E5)

One key holds the 4A rows (BODY_PROVED), the 4B rows (MODELLED) and six SUGGESTED name-rule rows, four
of them the hostile false ones. The extractor applies DECLARED/BODY_PROVED/MODELLED only; MINED and
SUGGESTED rows are counted as shadow. Gate on: W2/W4 recovered exactly as in Stage 1b, H1–H4 clean, six
shadow rows counted. `OWEN_RE_ORACLE_TRUST=all` (the M6 mutant): the same key moves H1 (false OWN001),
H2 (the true leak hidden), H4 (false OWN002 + OWN003). The gate is load-bearing and lives at the key; no
per-op provenance in OwnIR was needed. K7 is not triggered.

## Reading for the decision

Two pre-registered readings hold at once. The explicit two-row pack is the cheapest point of the frontier
and needs a human who read the API. The dependency-source derivation reaches the same rows with zero
false rows through generic rules, but needs the pinned BCL source and the Stage 2–3 rules (+148 extractor,
+50 engine lines). Mining gives nothing here; naming and LLM candidates must stay behind the gate. The final
record weighs this frontier against the held-out results of Stage 5.
