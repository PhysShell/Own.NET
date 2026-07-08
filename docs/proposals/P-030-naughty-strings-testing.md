# P-030 — Naughty-strings robustness pack (BLNS-driven crash testing)

- **Status:** draft
- **Depends on / relates to:**
  - [P-001](P-001-csharp-extractor.md) — the C# → OwnIR extractor: the thing that
    has to survive arbitrary third-party source text in the first place.
  - [P-012](P-012-bug-corpus-mining.md) — same "curated corpus, gated in CI"
    shape, but keyed by **string content**, not by bug pattern; orthogonal, not a
    replacement.
  - [P-015](P-015-configuration-surface.md) — the future `own.toml`/`.ownrc`
    config surface; config discovery has to survive naughty paths/globs too.
  - [P-024](P-024-security-audit-profile.md) — same "берём готовое, не
    изобретаем свою эвристику" instinct (adopt an existing corpus instead of
    hand-rolling a dozen Unicode edge cases), but explicitly **not** a security
    profile — see Non-goals.

## Motivation

Own.NET's whole value proposition is running against real, uncontrolled legacy
C#/WPF/DevExpress code: arbitrary identifiers, string literals, resource
strings, file and project paths chosen by other people over twenty years. The
project's own honest-skip philosophy (`docs/ROADMAP.md`) already treats "the
checker doesn't know" as an acceptable, first-class outcome — but a **crash**
is not "doesn't know," it's the tool falling over on a customer's codebase,
which is strictly worse than a missed diagnostic.

Today robustness is exercised only by *valid* fixtures — `corpus/wpf/`,
`corpus/real-world/`, `tests/fixtures/` — plus whatever `ParseError`/`LexError`
paths (`ownlang/lexer.py`, `ownlang/parser.py`) happen to be hit incidentally.
Nothing in the suite deliberately throws adversarial *text* at the extractor,
the JSON/SARIF emitters (`ownlang/cfg_json.py`, `ownlang/diag_sarif.py`,
`ownlang/diagnostics.py`, `ownlang/report.py`), or the CLI (`ownlang/__main__.py`)
— zero-width joiners, RTL/LTR override characters, unpaired surrogates, SQL/
XSS-shaped strings sitting inert inside a C# string literal, absurdly long
lines, mixed line endings, strings that are themselves valid-looking JSON or
XML, "your kernel just crashed"-style command injection payloads. And this
class of bug is not hypothetical here: `OwnAudit/Run-Audit.ps1` already carries
a scar from exactly this — `PYTHONUTF8=1` is set specifically to dodge a
**cp1251 console crash on a Russian-locale Windows target**. That is one
instance of the bug class BLNS exists to catch *systematically*, found the hard
way instead of by test.

[Big List of Naughty Strings](https://github.com/minimaxir/big-list-of-naughty-strings)
(BLNS) is a maintained, MIT-licensed corpus built for exactly this: ~500 strings
(Unicode edge cases, escaping/injection-shaped strings, whitespace and
line-ending oddities, format-breakers for JSON/XML/CSV/SQL/shell), shipped as a
plain `blns.json` array plus a `.NET` port (`NaughtyStrings` NuGet package) for
the C#-side pieces (`audit/`'s eventual C# on lift-out, per
[`OwnAudit/README.md`](https://github.com/PhysShell/OwnAudit/blob/main/README.md)). BLNS itself is
explicit that it is not a substitute for real security testing (see
Non-goals) — its contract here is narrower and cheaper: **the tool must not
crash, hang, or corrupt output on any string in the corpus.**

## Scope

1. **Vendor the corpus.** A pinned, static copy of `blns.json` (upstream tag/
   commit recorded in a comment) as a fixture, e.g.
   `tests/fixtures/blns.json` — no network fetch at test time, no submodule
   (matches the project's existing "no external runtime deps beyond stdlib"
   posture in the Python core).

2. **Layer 1 — lexer/parser/extractor.** Parametrize over every BLNS entry,
   embedding it as: (a) `.own` string-literal content, (b) a C# string literal
   fed through the P-001 extractor, (c) a file/module name passed on the CLI.
   Assert only: no unhandled exception escapes `ownlang/lexer.py` /
   `ownlang/parser.py` / the extractor; the *only* acceptable failure shapes
   are `LexError`/`ParseError` (or the extractor's own diagnostic-and-skip
   path) — never a raw traceback, never a hang past a fixed timeout.

3. **Layer 2 — serialization.** Pipe BLNS content through
   `ownlang/diagnostics.py` → `ownlang/diag_sarif.py` / `ownlang/cfg_json.py` /
   `ownlang/report.py` (as a synthesized finding message / file path / symbol
   name) and assert the emitted JSON/SARIF/Markdown is well-formed
   (round-trips through a JSON/SARIF parser) with no crash — this is the
   layer `test_cfg_json.py` / `test_diag_sarif.py` already exercise for valid
   input; this proposal is the adversarial-input twin.

4. **Layer 3 — CLI & future config.** `ownlang/__main__.py` argument/path
   handling, and (when [P-015](P-015-configuration-surface.md) lands) `own.toml`
   discovery, given BLNS-flavored file names, directory names, and glob
   patterns. Same contract as Layer 1, spelled out for I/O: the *only*
   acceptable rejections are `FileNotFoundError` / `IsADirectoryError` /
   `PermissionError` / `UnicodeDecodeError` / `OSError` surfaced as a clean CLI
   error — the shape `cmd_explain`'s `--json` path already uses
   (`except (OSError, json.JSONDecodeError)`) — and, once P-015 lands, a
   documented config-parse error; never a raw traceback, never a hang past a
   fixed timeout. This pack is expected to *find*, not assume, that contract:
   today `_read()` — the path opener behind `check`/`emit`/`cfg`/`report` —
   catches nothing, so a BLNS-flavored path (a null byte, an unpaired
   surrogate, a name that turns out to be a directory) is a live candidate for
   turning this layer red on day one, not a hypothetical.

5. **Land as one hermetic, parametrized module** —
   `tests/test_naughty_strings.py` — wired into `tests/run_tests.py` and CI the
   same way `tests/test_corpus.py` is: fast, offline, property-style
   ("must not crash," not "must produce code X").

6. **Follow-on, not in v0:** an equivalent pass over `OwnAudit`'s SARIF
   ingestion / `artifacts/health-report.*` rendering, since that's the other
   place free text from arbitrary source flows into output — deferred because
   it crosses the repo boundary and OwnAudit already treats SARIF as its
   external contract.

## Non-goals

- **Not a security test / pentest substitute.** BLNS's own README says the
  same. This proposal claims only "does not crash / does not corrupt state on
  adversarial text" — nothing about exploitability, authorization, or network
  surface. That territory is [P-024](P-024-security-audit-profile.md)'s, and
  this proposal does not overlap it: no scanning, no CVE claims, no new
  security-flavored diagnostic codes.
- **Not a new checker or diagnostic.** No new `OWN0NN` code, no severity
  change, no touch to ownership/lifetime semantics. Purely a regression/
  robustness harness around existing entry points.
- **Not coverage-guided fuzzing.** That is `007`'s `fuzz/` (cargo-fuzz)
  territory on the eventual Rust core (P-022) — an open-ended search for novel
  crashes. This is a fixed, curated, deterministic corpus, cheap enough to run
  on every commit, not a campaign.
- **Not "every naughty string gets a pretty diagnostic."** The honest-skip /
  `ParseError` contract is sufficient; the property under test is "no crash,
  no hang, no corrupted output," not "graceful handling with a nice message"
  for all ~500 entries.
- **Does not change the `corpus/` layout** (`before.cs`/`after.cs`/`case.own`)
  from P-012 — BLNS fixtures are a separate, orthogonal corpus keyed by string
  content, not by bug pattern, and live under `tests/fixtures/`, not `corpus/`.

## Sketch

```text
tests/fixtures/blns.json          # vendored, pinned copy (upstream commit noted)
tests/test_naughty_strings.py     # parametrized over every entry, 3 layers above
```

```python
import json, os
from ownlang.lexer import LexError
from ownlang.parser import ParseError, parse

with open(os.path.join(os.path.dirname(__file__), "fixtures", "blns.json"),
          encoding="utf-8") as f:
    BLNS = json.load(f)


def run() -> int:
    """One case per BLNS entry, in the suite's zero-dependency style: no
    pytest — tests/run_tests.py auto-discovers every test_*.py that exposes
    a run() -> int, same as tests/test_corpus.py."""
    fails: list[str] = []
    for naughty in BLNS:
        # Embed the entry in a grammatically legal STRING position: per
        # ownlang/parser.py's grammar, string literals appear only in
        # resource emit_*/kind members (a `let` rhs never takes a string),
        # so a benign entry parses cleanly and only the naughty content is
        # under test — the wrapper follows the run_tests.py PRELUDE shape.
        src = f'module M\nresource R {{ acquire a release r emit_type "{naughty}" }}\n'
        try:
            parse(src)
        except (ParseError, LexError):
            pass  # an honest rejection is fine; anything else is a bug
        except Exception as e:
            fails.append(f"{naughty!r}: {type(e).__name__}: {e}")
    for f in fails:
        print(f"NAUGHTY FAIL: {f}")
    return 1 if fails else 0
```

Serialization side follows the same shape against `diag_sarif.py` /
`cfg_json.py`, asserting `json.loads(...)` / a SARIF-shape check succeeds.

## Open questions

1. **Generation vs. fixture files.** Synthesize `.own`/`.cs` source around each
   BLNS entry on the fly (parametrized, no repo bloat — the sketch above) vs.
   materializing ~500 tiny fixture files. Leaning generation; only fall back to
   files if a specific entry needs a shape the generator can't express.
2. **Timeout bound.** Several BLNS entries are specifically shaped to blow up
   naive parsers (repetition/expansion strings). What per-case wall-clock
   cutoff counts as "hung" in CI?
3. **Encoding boundary.** Is UTF-8 the only contract for this pack, or does
   OwnAudit's cp1251-console incident warrant its own explicit BLNS pass over
   the PowerShell/console path, given it already burned once?
4. **Vendoring mechanics.** Pinned static copy of `blns.json` (simple, matches
   current no-submodule posture) vs. a `scripts/` updater that re-fetches on
   demand — leaning static copy with the upstream commit noted in a header
   comment.
5. **Rust-core inheritance.** When/if P-022's Rust core lands with a
   differential oracle (Python = golden), does this pack become a shared input
   fed to both sides rather than a Python-only test?
6. **OwnAudit follow-on timing.** Scope item 6 defers the OwnAudit-side pass —
   confirm that's the right call now vs. folding it in immediately given the
   cp1251 precedent already lives there.
