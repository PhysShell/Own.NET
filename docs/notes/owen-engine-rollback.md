# Selecting Owen's analysis engine, and rolling back

Owen has two analysis engines behind one launcher. Since **P-022 Stage 3**
(#262) the default is the **Rust core**; the **Python reference** remains
available and supported, and selecting it is the documented rollback for the
observation window.

This is the one canonical place that says how. If another document disagrees
with this one, this one is right.

## The selection

One selector, the same three spellings, on every launcher surface:

| surface | default (Rust) | roll back to Python | compare |
| --- | --- | --- | --- |
| `owen` | `owen check <path>` | `owen check --engine python <path>` | `--engine compare` |
| `scripts/own-check.sh` | `own-check.sh <path>` | `own-check.sh --engine python <path>` | `--engine compare` |
| `scripts/own-check.ps1` | `own-check.ps1 <path>` | `own-check.ps1 -Engine python <path>` | `-Engine compare` |
| Owen Action | (nothing) | `with: { engine: python }` | `engine: compare` |

`compare` runs both engines over one captured input and exposes the reference's
result **only** when they agree byte for byte. It is a development/CI seam for
the migration, not a promised public feature.

## Rolling back

Add the flag. That is the whole mechanism, and it is deliberately the whole
mechanism:

```yaml
# .github/workflows/your-workflow.yml
- uses: PhysShell/Own.NET@v1
  with:
    path: src
    engine: python      # roll back to the reference engine
```

```bash
owen check --engine python src
```

There is no environment variable that changes the engine, and that is on
purpose: an ambient setting is a thing you forget you set, and "which engine
produced this finding" would stop being answerable from the command that
produced it.

### What rollback is not

* **Not automatic.** Nothing falls back. If the Rust core fails, you get the
  Rust core's failure — visibly — and Owen does not quietly run Python and
  present its answer as though nothing happened. A result from an engine you
  did not choose is worse than an error, because you cannot tell.
* **Not a moved tag.** Release tags are immutable and are never re-pointed. A
  broken release is corrected by a **new patch release**.
* **Not Python's removal, and not its deprecation.** Stage 4 will remove the
  Python core from the *distribution*; until then it ships, it works, and it is
  supported. Stage 3 changed which engine answers when you say nothing.

## When the Rust core cannot be used

Both failures are **configuration errors (exit 2)**, never a fallback, and both
say so in as many words:

* the packaged binary is missing from an installed `owen` — a packaging or
  install fault;
* `OWEN_RUST_CORE` is set to something unusable.

Either way Owen tells you what it looked for and offers `--engine python`. It
does not decide for you.

## `OWEN_RUST_CORE` is for developers

`OWEN_RUST_CORE` says **where** a candidate `own-cli` binary is. It does not say
*which engine* to run — that is `--engine`. When it is set it wins; when it is
absent, an installed `owen` uses the binary inside its own package (#262 D6).

There is **no discovery**: no `PATH` lookup, no `rust/target` probing, no "first
binary found". Those are how a stale binary from some earlier build silently
stands in for the one you meant to run.

The two shell surfaces run from a **checkout** and have no package to fall back
on, so running them with the default engine needs a candidate:

```bash
cd rust && cargo build -p own-cli --release
export OWEN_RUST_CORE="$PWD/target/release/own-cli"
```

…or pass `--engine python` and skip the build.

## What is tested, and where

Rollback is not documentation-only. `tests/test_stage3_rollback.py` drives four
states on every runnable launcher surface and requires them to stay **distinct**:

```text
1  default, candidate fine         -> Rust runs
2  --engine python                 -> Python runs, and AGREES with 1
3  candidate broken, nothing asked -> visible failure (exit 2), fallback denied
4  candidate broken, python asked  -> Python runs anyway
```

3 and 4 are one flag apart and are the pair that matters: a launcher with a
hidden fallback makes 3 look like 4. 1 and 2 are what stop 3 passing for a
launcher that simply never worked.
