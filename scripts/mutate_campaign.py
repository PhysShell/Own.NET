#!/usr/bin/env python3
"""Run a mutation campaign and record what caught each mutation.

P-022's parity-work discipline makes a test evidence only once its mutation
fails **through the production surface it claims to protect** (rule 2), and
requires **every** catching layer to be exposed rather than the first one
(rule 3 — no fail-fast). Before this script the campaigns were run by hand and
written up in prose, which is exactly the shape that rots: the numbers in a
note cannot be re-derived, and a mutation whose target code has since moved
looks the same as one that still applies.

So a campaign is **data**: a definition file naming each mutation as an exact
text edit to a production file, and a result file recording, per mutation,
which layers failed. Both live beside the checkpoint note as evidence. The
definition is checkable in CI without running anything — every edit's `find`
string must still occur exactly once in its target — so a campaign that no
longer applies is a red build rather than a quiet fiction.

## What this script guarantees

* **No fail-fast, ever** (rule 3). Every layer runs for every mutation, and
  every failing test within a layer is recorded — not the first one.
* **Restore from a copy held in memory, never `git checkout`** (the lesson
  from #259 cp1's third round: `git checkout` also reverts whatever else the
  working tree was carrying). The original bytes are read before the edit and
  written back in a `finally`, and the script refuses to start with a dirty
  target file.
* **Cached bytecode is invalidated on every write.** A `.pyc` is validated
  against the source's integer mtime and size, so a same-size mutation can
  survive a restore and poison every later row. See `_invalidate_bytecode`.
* **A compile error is reported as a compile error**, never as "caught". A
  mutation that does not build proves nothing about the tests.
* **`M00` is the harness-honesty control**: a mutation entry with no edits,
  which must report **zero** failing layers. If it does not, the campaign is
  measuring a pre-existing red build and every other row is worthless.

## Definition format

```json
{
  "campaign": "p022-shadow-cp1",
  "comment": "...",
  "layers": [
    {"id": "python", "cwd": ".", "command": ["python3", "tests/test_repro_fixtures.py"],
     "parser": "python_fail_lines"},
    {"id": "rust", "cwd": "rust", "command": ["cargo", "test", "-p", "own-shadow",
     "--no-fail-fast"], "parser": "cargo_test"}
  ],
  "mutations": [
    {"id": "M00", "what": "harness-honesty control", "edits": []},
    {"id": "M01", "what": "...", "rule": "...",
     "edits": [{"file": "...", "find": "...", "replace": "..."}]}
  ]
}
```

`parser` decides how a layer's output is turned into catcher names:

* `cargo_test` — cargo prints `test <name> ... FAILED` on stdout and
  `Running <target>` on stderr, and capturing them separately loses the
  interleaving that attributes a test to its target (the #259 cp4 lesson), so
  the two streams are **merged**.
* `python_fail_lines` — the repo's harnesses print `FAIL: <what>` lines; the
  distinct leading phrase of each is the catcher.

Run:  python scripts/mutate_campaign.py <definition.json> --out <result.json>
      python scripts/mutate_campaign.py <definition.json> --check
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# `test <name> ... FAILED`. The streams are merged before matching so a test
# name is read in the same order cargo printed its `Running <target>` line —
# capturing them separately loses that interleaving (the #259 cp4 lesson).
_CARGO_FAIL = re.compile(r"^test (\S+) \.\.\. FAILED", re.MULTILINE)
_CARGO_COMPILE_ERROR = re.compile(r"^error(\[E\d+\])?: ", re.MULTILINE)
# The repo's harnesses print `FAIL[<check>]: <detail>`; the bracketed check is
# the catcher's identity. Without it a campaign would attribute a catch to each
# failing CASE and report the corpus size as the catcher count — noise, not
# evidence about which layer caught what (P-022 discipline 3).
_PY_FAIL_TAGGED = re.compile(r"^FAIL\[([^\]]+)\]:", re.MULTILINE)
_PY_FAIL = re.compile(r"^FAIL: (.+)$", re.MULTILINE)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    _invalidate_bytecode(path)


def _invalidate_bytecode(path: str) -> None:
    """Drop any cached bytecode for a source file we just rewrote.

    CPython validates a `.pyc` against the source's **integer** mtime and its
    **size**. A mutation that changes neither — `indent=2` → `indent=4` is
    exactly that — is invisible to that check, so restoring the original can
    leave the MUTATED bytecode in place and every later run silently executes
    it. Paid for: round 2 of the cp1 campaign reported
    `python::artifact-golden` as a catcher for fifteen Rust-only mutations,
    which is impossible; M15 (a same-size indent change) had poisoned the
    cache and every row after it was measuring the leftover.

    The layers also run with `PYTHONDONTWRITEBYTECODE=1` (see `_layer_env`),
    so the campaign neither reads nor writes stale caches."""
    if not path.endswith(".py"):
        return
    cached = importlib.util.cache_from_source(path)
    try:
        os.remove(cached)
    except FileNotFoundError:
        pass


def _layer_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def check_definition(campaign: dict[str, Any]) -> list[str]:
    """Verify the campaign still applies to the tree WITHOUT running anything:
    every edit's `find` must occur exactly once in its target file, and every
    `replace` must differ from it. A campaign whose target code has moved is a
    campaign whose recorded result no longer describes this tree."""
    problems: list[str] = []
    seen: set[str] = set()
    controls = 0
    for mutation in campaign.get("mutations", []):
        mid = mutation.get("id")
        if not isinstance(mid, str) or not mid:
            problems.append(f"mutation without an id: {mutation!r}")
            continue
        if mid in seen:
            problems.append(f"duplicate mutation id {mid}")
        seen.add(mid)
        if not mutation.get("what"):
            problems.append(f"{mid}: 'what' must say which rule the mutation breaks")
        edits = mutation.get("edits", [])
        if not edits:
            controls += 1
            continue
        for i, edit in enumerate(edits):
            where = f"{mid}.edits[{i}]"
            path = os.path.join(ROOT, edit.get("file", ""))
            if not os.path.isfile(path):
                problems.append(f"{where}: no such file: {edit.get('file')!r}")
                continue
            find, replace = edit.get("find"), edit.get("replace")
            if not isinstance(find, str) or not find:
                problems.append(f"{where}: 'find' must be a non-empty string")
                continue
            if not isinstance(replace, str):
                problems.append(f"{where}: 'replace' must be a string")
                continue
            if find == replace:
                problems.append(f"{where}: 'replace' is identical to 'find' — this is "
                                f"not a mutation (the #259 cp4 M10 lesson)")
            occurrences = _read(path).count(find)
            if occurrences != 1:
                problems.append(
                    f"{where}: 'find' occurs {occurrences} times in "
                    f"{edit.get('file')} (must be exactly 1) — the campaign no "
                    f"longer applies to this tree; re-anchor it and re-run")
    if controls != 1:
        problems.append(
            f"a campaign needs exactly one harness-honesty control (a mutation "
            f"with no edits); found {controls}")
    if not campaign.get("layers"):
        problems.append("a campaign needs at least one validation layer")
    return problems


def _run_layer(layer: dict[str, Any]) -> tuple[list[str], bool]:
    """(catcher names, compile_error). Streams are MERGED: cargo's `Running`
    lines go to stderr and its test results to stdout, and capturing them
    separately loses the interleaving that attributes a test to its target."""
    proc = subprocess.run(
        layer["command"],
        cwd=os.path.join(ROOT, layer.get("cwd", ".")),
        env=_layer_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    out = proc.stdout
    parser = layer.get("parser")
    if parser == "cargo_test":
        if _CARGO_COMPILE_ERROR.search(out) and not _CARGO_FAIL.search(out):
            return [], True
        return [f"{layer['id']}::{name}" for name in _CARGO_FAIL.findall(out)], False
    if parser == "python_fail_lines":
        phrases = set(_PY_FAIL_TAGGED.findall(out))
        if not phrases:
            # An untagged harness: collapse to the distinct leading phrase so
            # the count still means "checks", not "cases".
            phrases = {line.split(":")[0].strip() for line in _PY_FAIL.findall(out)}
        if proc.returncode != 0 and not phrases:
            phrases = {"non-zero exit with no FAIL line"}
        return sorted(f"{layer['id']}::{p}" for p in phrases), False
    raise SystemExit(f"unknown parser {parser!r} in layer {layer['id']!r}")


def run_campaign(campaign: dict[str, Any]) -> dict[str, Any]:
    layers = campaign["layers"]
    records: list[dict[str, Any]] = []
    for mutation in campaign["mutations"]:
        mid = mutation["id"]
        edits = mutation.get("edits", [])
        originals: dict[str, str] = {}
        try:
            for edit in edits:
                path = os.path.join(ROOT, edit["file"])
                # Read the original ONCE, keep it, restore from it. Never
                # `git checkout` — that would also revert unrelated work.
                if path not in originals:
                    originals[path] = _read(path)
                current = _read(path)
                if current.count(edit["find"]) != 1:
                    raise SystemExit(
                        f"{mid}: anchor for {edit['file']} is not unique any more; "
                        f"run --check")
                _write(path, current.replace(edit["find"], edit["replace"], 1))
            caught: list[str] = []
            compile_error = False
            # EVERY layer runs, for every mutation (rule 3: no fail-fast).
            for layer in layers:
                names, failed_to_build = _run_layer(layer)
                compile_error = compile_error or failed_to_build
                caught += names
        finally:
            for path, text in originals.items():
                _write(path, text)
        if not edits:
            status = "control_clean" if not caught else "control_dirty"
        elif compile_error:
            status = "compile_error"
        elif caught:
            status = "caught"
        else:
            status = "survived"
        print(f"{mid}: {status} ({len(caught)} catcher(s)) — {mutation['what']}",
              flush=True)
        records.append({
            "id": mid,
            "what": mutation["what"],
            "rule": mutation.get("rule"),
            "status": status,
            "caught_by": sorted(set(caught)),
        })
    totals = {
        "mutations": sum(1 for r in records if r["status"] != "control_clean"
                         and r["status"] != "control_dirty"),
        "caught": sum(1 for r in records if r["status"] == "caught"),
        "survived": sum(1 for r in records if r["status"] == "survived"),
        "compile_errors": sum(1 for r in records if r["status"] == "compile_error"),
        "control_clean": sum(1 for r in records if r["status"] == "control_clean"),
    }
    return {
        "campaign": campaign["campaign"],
        "generated_by": "scripts/mutate_campaign.py",
        "comment": (
            "A RECORDED run, not a CI gate: mutating the tree and running every "
            "layer takes minutes and cannot be part of the per-commit gates. What "
            "IS gated is the campaign DEFINITION (every anchor still resolves) and "
            "this file's internal consistency — see tests/test_generated_docs.py."),
        "layers": [layer["id"] for layer in layers],
        "totals": totals,
        "mutations": records,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("definition")
    ap.add_argument("--out", help="where to write the recorded result")
    ap.add_argument("--check", action="store_true",
                    help="verify the definition still applies; run nothing")
    ap.add_argument("--only", help="run one mutation id (for re-anchoring)")
    args = ap.parse_args()

    with open(args.definition, encoding="utf-8") as f:
        campaign = json.load(f)

    problems = check_definition(campaign)
    if problems:
        for p in problems:
            print(f"ERROR: {p}")
        return 1
    if args.check:
        print(f"campaign '{campaign['campaign']}' definition OK: "
              f"{len(campaign['mutations'])} mutations, every anchor resolves")
        return 0

    if args.only:
        campaign = dict(campaign)
        campaign["mutations"] = [m for m in campaign["mutations"]
                                 if m["id"] in (args.only, "M00")]
    result = run_campaign(campaign)
    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        _write(args.out, text)
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(text)
    return 0 if result["totals"]["survived"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
