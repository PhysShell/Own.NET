# Metamorphic testing — robustness QA for the checker itself

`scripts/metamorphic.py` generates **semantically-equivalent** variants of a
`.own` program — rewrites that cannot change its meaning — and asserts the
checker's diagnostics are **invariant**. A divergence is a *robustness bug in the
analyzer*: it keyed on something semantically irrelevant (a name, a textual
order). This finds such bugs with **no labels and no oracle** — the StaAgent /
Statfier line: testing the analyzer, not the program.

## Why it pays off on its own (no LLM)

1. **Automatic analyzer bug-finder.** Where invariance breaks, the checker is
   sensitive to something it shouldn't be. We hit exactly this class by hand this
   year — the P-014 syntactic FP wall (`sum += value` read as a subscription), the
   self-owned-control FPs, the multi-line-lambda parser drift. A harness catches
   them automatically.
2. **Regression ratchet.** Once "these transforms preserve the verdict on the
   corpus" is asserted in CI, every future change to the checker is tested against
   that invariant. Robustness can only ratchet up.
3. **A measurable stability metric** for the benchmark/paper: "diagnostics are
   invariant under N classes of meaning-preserving transformation across the
   corpus." The research-landscape note files this as a separable contribution.
4. **Free corpus amplification** — each real case spawns many variants that must
   all behave identically.

It is *also* the conformance check a future LLM fix-loop needs (RLVR reward =
checker-green **and** behavior-preserved, see `research-landscape-2026.md`) — but
that is a bonus; the standalone value above stands without any LLM.

## How

`parse(.own)` → mutate the **AST** (`dataclasses.replace`, the nodes are frozen)
→ `check_module` → compare the **multiset of diagnostic codes**. dotnet-free: it
drives the same parser + core the CLI uses. We compare *codes*, not (code, line):
a sound reorder can legitimately move an end-of-function diagnostic's *line* — it
anchors to the last statement — without changing which diagnostics fire, so a line
would false-positive a *correct* checker. What a meaning-preserving rewrite must
hold is *which* diagnostics fire: the code multiset. (Both this and the condition
text below were caught by codex on the first cut — see PR #45.)

### v1 transforms (each provably meaning-preserving)

- **alpha-rename** — rename a local **bound exactly once** (so it cannot be
  shadowing anything) and every one of its references — *including the identifier
  inside an opaque `if`/`while` condition*, so the variant stays a valid rename;
  pure alpha-equivalence.
- **reorder** — swap two adjacent **simple** statements whose touched-variable
  sets are **disjoint**; independent statements commute. (Conservative: it skips
  control flow / borrow blocks and any pair that shares a variable, so it never
  emits an unsound swap.)

### The result so far — two targets

**Core (`.own`, `metamorphic.py`).** The whole `.own` corpus (gallery + examples +
corpus, 28 programs) is **invariant under both transforms** — the expected baseline
for a core built on symbol identity + dataflow (it *should* be name/order-agnostic).

**Bridge (OwnIR facts, `metamorphic_facts.py`).** The same idea one level down: the
JSON the extractor emits is a *set of records* (components, their resources, DI
services, contracts), so **reversing** any record list or **consistently renaming**
a component/service identifier cannot change which leaks exist. All **18** committed
fact fixtures (plus a captive-DI set) are invariant under `check_facts` — including
`DI001` (a singleton capturing a scoped service), which holds under both service
reordering *and* a consistent rename of the dependency graph. Higher-signal than the
core, since the bridge carries the incidental complexity (DI graph, finding dedup,
source-lifetime tiering) — and still dotnet-free.

Both are real, if modest, robustness results, and the framework now ratchets them.
Neither harness is vacuous: a **teeth test** asserts the code key actually
distinguishes a leak from a clean run, and that the transforms genuinely fire.

## Run it

```sh
python scripts/metamorphic.py examples corpus            # core: sweep .own
python scripts/metamorphic.py --selftest                 # core: invariance + teeth (CI)
python scripts/metamorphic_facts.py tests/fixtures/ownir # bridge: sweep *.facts.json
python scripts/metamorphic_facts.py --selftest           # bridge: invariance + teeth (CI)
```

Both `--selftest`s run on every push (CI `script selftests` job), beside the miner
and oracle selftests.

## Follow-ups (where the bug-finding power grows)

- **More sound transforms** — core: dead-branch wrapping for statements that bind
  no later-used name, a redundant borrow/`use`, reorder into nested bodies; bridge:
  splitting independent components, or inserting a no-op released record.
- **C# source target** — mutate `.cs` (rename locals, reorder members) → re-run
  the extractor → check. This tests the *extractor*, where the syntactic-FP bugs
  actually lived — but it needs the Roslyn frontend, so it is CI-only.
- **LLM fix-loop conformance** — the same invariance check becomes the
  behavior-preservation half of the RLVR reward (downstream, only once a fix-loop
  exists).
