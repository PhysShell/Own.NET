#!/usr/bin/env python3
"""OwnIR v2 `proven_call` (H1) — the compatibility controls and the derived refusals.

H1 lets a call inside a state-protocol region through ONLY when the shared heap-effect
summaries prove it harmless, and it does so through a must-understand op. These controls
hold the "must-understand" and the "only when proven" (docs/notes/h1-proven-call.md):

* **C1 — old core, new facts.** The REAL v1 core — `ownlang/` exactly as it was at the
  H0 landing point, the last commit with `OWNIR_VERSION = 1`, taken out of git history —
  is run on v2 facts the extractor wrote for an admitted `proven_call`. It must refuse
  (exit 2): on the version stamp, and, with the stamp stripped (an absent version reads
  as the core's own), on the unknown op. A v1 core cannot read v2 facts as clean.
* **C2/C3 — missing evidence, malformed op or section.** Documents DERIVED from the real
  extractor output for `cases/H1a_harmless_call.cs` (the committed
  `typestate_cs_h1a_harmless_call.facts.json`), one targeted corruption each, written to
  `tests/fixtures/lowered/proven_call_*.facts.json` by `--write` and held in sync here.
  Each is refused; the Layer 2 golden pins the text and the Rust bridge replays it byte
  for byte (`own-bridge/tests/replay.rs`), so the two engines refuse identically.
* **C4 — Unknown is poison.** A mutant predicate that reads Unknown as harmless must
  ADMIT what the real one refuses (transitive Unknown, an Unknown callee, an Unknown site):
  the pinned refusals would go red under it.
* **C5 — the op cannot be dropped.** A core whose admission pass is a no-op admits the
  refused kill fixtures; facts whose `proven_call` was dropped read as clean. Both differ
  from what the ledgers pin, so neither can happen silently.

Run:  python tests/test_proven_call.py            (verify)
      python tests/test_proven_call.py --write    (regenerate the derived fixtures)
"""

from __future__ import annotations

import copy
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang import heap_effects, ownir
from ownlang.ownir import OwnIRError, check_facts

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
LOWDIR = os.path.join(ROOT, "tests", "fixtures", "lowered")
BASE = "typestate_cs_h1a_harmless_call"
CALLEE = "Own.Protocols.Cases.H1aHarmlessCall.Twice(int)"
# The H0 landing point: the last commit whose core understands OwnIR v1 (and nothing newer).
V1_CORE = "1c70e867eb408d931ae3dfffd8c0b351190f6547"


def _read(name: str) -> dict[str, Any]:
    with open(os.path.join(LOWDIR, f"{name}.facts.json"), encoding="utf-8") as f:
        doc: dict[str, Any] = json.load(f)
    return doc


def _region(doc: dict[str, Any]) -> dict[str, Any]:
    for fn in doc["functions"]:
        for n in fn.get("body", []):
            if n.get("op") == "borrow_mut":
                return n  # type: ignore[no-any-return]
    raise KeyError("borrow_mut")


def _pc(doc: dict[str, Any]) -> dict[str, Any]:
    for n in _region(doc)["body"]:
        if n.get("op") == "proven_call":
            return n  # type: ignore[no-any-return]
    raise KeyError("proven_call")


def _record(doc: dict[str, Any], key: str) -> dict[str, Any]:
    for m in doc["heap_effects"]["methods"]:
        if m["key"] == key:
            return m  # type: ignore[no-any-return]
    raise KeyError(key)


def _derived() -> dict[str, dict[str, Any]]:
    """The refusal fixtures, each one corruption of the real extractor output."""
    base = _read(BASE)
    site = _pc(base)["site"]
    out: dict[str, dict[str, Any]] = {}

    def make(name: str, edit: Callable[[dict[str, Any]], None]) -> None:
        doc = copy.deepcopy(base)
        edit(doc)
        out[f"proven_call_{name}"] = doc

    def no_section(d: dict[str, Any]) -> None:
        del d["heap_effects"]

    def no_site_record(d: dict[str, Any]) -> None:
        d["heap_effects"]["methods"] = [m for m in d["heap_effects"]["methods"]
                                        if m["key"] != site]

    def site_not_a_string(d: dict[str, Any]) -> None:
        _pc(d)["site"] = 7

    def empty_callee(d: dict[str, Any]) -> None:
        _pc(d)["callee"] = ""

    def outside_region(d: dict[str, Any]) -> None:
        call = _pc(d)
        _region(d)["body"].remove(call)
        body = d["functions"][0]["body"]
        body.insert(body.index(_region(d)), call)

    def bad_section(d: dict[str, Any]) -> None:
        d["heap_effects"]["heap_effects_version"] = 9

    def wrong_callee(d: dict[str, Any]) -> None:
        _pc(d)["callee"] = "Own.Protocols.Cases.H1aHarmlessCall.Thrice(int)"

    def missing_callee_record(d: dict[str, Any]) -> None:
        d["heap_effects"]["methods"] = [m for m in d["heap_effects"]["methods"]
                                        if m["key"] != CALLEE]

    def unknown_callee(d: dict[str, Any]) -> None:
        _record(d, CALLEE)["unknown"] = ["dynamic"]

    def unknown_site(d: dict[str, Any]) -> None:
        _record(d, site)["unknown"] = ["expression Await"]

    def virtual_in_site(d: dict[str, Any]) -> None:
        calls = _record(d, site)["calls"]
        calls.append({"id": len(calls), "callee": "Own.Protocols.Cases.IClock.Ticks()",
                      "dispatch": "virtual", "receiver": ["heap"], "args": [], "line": 18})

    for name, edit in [("no_section", no_section), ("no_site_record", no_site_record),
                       ("site_not_a_string", site_not_a_string),
                       ("empty_callee", empty_callee), ("outside_region", outside_region),
                       ("bad_section", bad_section), ("wrong_callee", wrong_callee),
                       ("missing_callee_record", missing_callee_record),
                       ("unknown_callee", unknown_callee), ("unknown_site", unknown_site),
                       ("virtual_in_site", virtual_in_site)]:
        make(name, edit)
    return out


def _verdict(facts: dict[str, Any]) -> list[str] | str:
    try:
        return sorted({f.code for f in check_facts(facts)})
    except OwnIRError as e:
        return f"refused: {e}"


# --- C2 / C3 ------------------------------------------------------------------


EXPECT_REFUSAL = {
    "proven_call_no_section": "needs the 'heap_effects' section",
    "proven_call_no_site_record": "has no record in 'heap_effects'",
    "proven_call_site_not_a_string": "needs a non-empty string 'site'",
    "proven_call_empty_callee": "needs a non-empty string 'site' and a non-empty string 'callee'",
    "proven_call_outside_region": "outside a borrow_mut region",
    "proven_call_bad_section": "section is malformed — heap-effect facts: heap_effects_version",
    "proven_call_wrong_callee": "the site does not call",
    "proven_call_missing_callee_record": f"'{CALLEE}' has no summary",
    "proven_call_unknown_callee": f"'{CALLEE}': writes.instance is unknown",
    "proven_call_unknown_site": "the call site: writes.instance is unknown",
    "proven_call_virtual_in_site": "'Own.Protocols.Cases.IClock.Ticks()' is virtual",
}


def _derived_controls(write: bool) -> list[str]:
    fails: list[str] = []
    derived = _derived()
    if set(derived) != set(EXPECT_REFUSAL):
        fails.append("the derived fixtures and their expectations name different cases")
    with open(os.path.join(LOWDIR, "manifest.json"), encoding="utf-8") as f:
        ledger = {c["name"] for c in json.load(f)["cases"]}
    for name, doc in sorted(derived.items()):
        path = os.path.join(LOWDIR, f"{name}.facts.json")
        text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
        if write:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        elif not os.path.exists(path):
            fails.append(f"{name}: derived fixture missing; run with --write")
        else:
            with open(path, encoding="utf-8") as f:
                if json.load(f) != doc:
                    fails.append(f"{name}: derived fixture is stale; run with --write")
        if name not in ledger:
            fails.append(f"{name}: not in tests/fixtures/lowered/manifest.json")
        got = _verdict(doc)
        if not (isinstance(got, str) and EXPECT_REFUSAL.get(name, "\0") in got):
            fails.append(f"{name}: expected a refusal naming {EXPECT_REFUSAL.get(name)!r}, "
                         f"got {got!r}")
    if _verdict(_read(BASE)) != []:
        fails.append(f"{BASE}: the uncorrupted document must be admitted and clean")
    return fails


# --- C1 -----------------------------------------------------------------------


def _v1_core(tmp: str) -> str | None:
    """Materialize `ownlang/` as it was at V1_CORE; None when history lacks it."""
    archive = subprocess.run(["git", "archive", "--format=tar", V1_CORE, "ownlang"],
                             cwd=ROOT, capture_output=True, check=False)
    if archive.returncode != 0:
        return None
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        if hasattr(tarfile, "data_filter"):   # 3.11.4+; the archive is our own history
            tar.extractall(tmp, filter="data")
        else:
            tar.extractall(tmp)
    return tmp


def _old_core_controls() -> list[str]:
    fails: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        core = _v1_core(tmp)
        if core is None:
            return [f"C1: commit {V1_CORE[:12]} (the last v1 core) is not in this clone's "
                    f"history; the old-core control needs it (CI checks out fetch-depth 0)"]
        with open(os.path.join(core, "ownlang", "ownir.py"), encoding="utf-8") as f:
            if "\nOWNIR_VERSION = 1\n" not in f.read():
                fails.append(f"C1: {V1_CORE[:12]} is not a v1 core")
        stamped = _read(BASE)
        unstamped = {k: v for k, v in stamped.items() if k != "ownir_version"}
        for label, doc, want in [
                ("stamped v2", stamped, "OwnIR facts are schema v2, but this core understands v1"),
                ("stamp removed", unstamped, "unknown OwnIR flow op 'proven_call'")]:
            path = os.path.join(tmp, "facts.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(doc, f)
            run = subprocess.run([sys.executable, "-m", "ownlang", "ownir", path],
                                 cwd=core, capture_output=True, text=True, check=False)
            if run.returncode != 2 or want not in run.stderr:
                fails.append(f"C1 ({label}): the v1 core must refuse with {want!r}, got exit "
                             f"{run.returncode}: {run.stderr.strip()[-300:]!r}")
    return fails


# --- C4 / C5 ------------------------------------------------------------------


@contextmanager
def _patched(module: Any, name: str, value: Any) -> Iterator[None]:
    saved = getattr(module, name)
    setattr(module, name, value)
    try:
        yield
    finally:
        setattr(module, name, saved)


def _unknown_is_harmless(s: heap_effects.Summary) -> str | None:
    """The C4 mutant: Unknown read as harmless (the one thing H1 must never do)."""
    def lift(level: int, unknown: int, to: int) -> int:
        return to if level == unknown else level
    return _REAL_HARMLESS(heap_effects.Summary(
        tuple(lift(p, heap_effects.UNKNOWN, heap_effects.PLAIN) for p in s.params),
        None if s.receiver is None else lift(s.receiver, heap_effects.UNKNOWN,
                                             heap_effects.PLAIN),
        (lift(s.writes[0], heap_effects.W_UNKNOWN, heap_effects.W_NONE),
         lift(s.writes[1], heap_effects.W_UNKNOWN, heap_effects.W_NONE),
         lift(s.writes[2], heap_effects.W_UNKNOWN, heap_effects.W_NONE)),
        tuple(r for r in s.returns if r != "unknown")))


_REAL_HARMLESS = heap_effects.harmless


def _mutant_controls() -> list[str]:
    fails: list[str] = []
    derived = _derived()
    poisoned = {"typestate_cs_h1g_transitive_unknown": _read("typestate_cs_h1g_transitive_unknown"),
                "proven_call_unknown_callee": derived["proven_call_unknown_callee"],
                "proven_call_unknown_site": derived["proven_call_unknown_site"]}
    for name, doc in poisoned.items():
        if not isinstance(_verdict(doc), str):
            fails.append(f"C4: {name} must be refused by the real predicate")
        with _patched(heap_effects, "harmless", _unknown_is_harmless):
            if isinstance(_verdict(doc), str):
                fails.append(f"C4: {name} is still refused when Unknown reads as harmless, so "
                             f"it does not pin Unknown-is-poison")
    refused = ["typestate_cs_h1d_global_state", "typestate_cs_h1e_transitive_global",
               "typestate_cs_h1f_polluted_scc", "typestate_cs_h1j_mutates_outer_value"]
    for name in refused:
        doc = _read(name)
        with _patched(ownir, "_admit_proven_calls", lambda facts: None):
            if _verdict(doc) != []:
                fails.append(f"C5: {name} must read as clean when the admission is dropped "
                             f"(so that the pinned refusal catches the drop)")
        dropped = copy.deepcopy(doc)
        _region(dropped)["body"] = [n for n in _region(dropped)["body"]
                                    if n.get("op") != "proven_call"]
        if _verdict(dropped) != [] or not isinstance(_verdict(doc), str):
            fails.append(f"C5: {name}: dropping its proven_call must turn a refusal into "
                         f"clean, which the committed facts and verdict ledgers then catch")
    return fails


def run(write: bool = False) -> int:
    fails = _derived_controls(write)
    fails += _old_core_controls()
    fails += _mutant_controls()
    for f in fails:
        print(f"FAIL proven_call: {f}")
    print(f"proven_call (OwnIR v2, H1): {len(EXPECT_REFUSAL)} derived refusals, the v1 core "
          f"on v2 facts, Unknown-is-poison and dropped-admission mutants — "
          f"{'FAIL' if fails else 'PASS'}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run(write="--write" in sys.argv[1:]))
