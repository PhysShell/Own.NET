"""N3 pilot: run the PoC over one source tree (01-preregistration-g1-g4.md).

1. `services` facts: the given saved facts.json, or a fresh run of the extractor on the tree.
2. Lifetimes under G0 rules 1, 2 and 4 (test-project registrations dropped; a name is a lifetime
   only when all remaining registrations agree, else "mixed").
3. The PoC (`n3poc.dll`), then each warning is labelled test-project / path-regex non-product.

usage: python -I n3_run.py --src <tree> --poc <n3poc.dll> --refs <dir> [--refs <dir>] --out <dir>
           [--facts <facts.json> --facts-base <dir>] [--extractor <ownsharp-extract.dll>]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from g0_scope_identity import NONPRODUCT, owning_project, resolve


def lifetimes(raw: list[dict], bases: list[str]) -> tuple[dict, int]:
    kept, dropped = [], 0
    for s in raw:
        src = resolve(str(s.get("file", "?")), bases)
        if src is not None and owning_project(src)[1]:
            dropped += 1
            continue
        kept.append(s)
    service: dict[str, set[str]] = {}
    impl: dict[str, set[str]] = {}
    impls: dict[str, set[str]] = {}
    for s in kept:
        n, lt, ct = str(s.get("name", "?")), str(s.get("lifetime", "")), str(s.get("ctor_type", ""))
        service.setdefault(n, set()).add(lt)
        if ct:
            impl.setdefault(ct, set()).add(lt)
            impls.setdefault(n, set()).add(ct)

    def one(v: set[str]) -> str:
        return next(iter(v)) if len(v) == 1 else "mixed"

    return {
        "service": {k: one(v) for k, v in sorted(service.items())},
        "impl": {k: one(v) for k, v in sorted(impl.items())},
        "impls": {k: sorted(v) for k, v in sorted(impls.items())},
    }, dropped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--poc", required=True)
    ap.add_argument("--refs", action="append", default=[])
    ap.add_argument("--out", required=True)
    ap.add_argument("--facts")
    ap.add_argument("--facts-base", action="append", default=[])
    ap.add_argument("--extractor")
    a = ap.parse_args()
    src = os.path.abspath(a.src)
    os.makedirs(a.out, exist_ok=True)
    if a.facts:
        facts_path, bases = a.facts, a.facts_base or [src]
    else:
        facts_path, bases = os.path.join(os.path.abspath(a.out), "facts.json"), [src]
        subprocess.run(
            ["dotnet", a.extractor, ".", "-o", facts_path],
            cwd=src,
            check=True,
            stdout=subprocess.DEVNULL,
        )
    facts = json.load(open(facts_path, encoding="utf-8"))
    raw = facts.get("services", []) if isinstance(facts.get("services"), list) else []
    lts, dropped = lifetimes(raw, bases)
    lt_path = os.path.join(a.out, "lifetimes.json")
    json.dump(lts, open(lt_path, "w", encoding="utf-8"), indent=1, sort_keys=True)
    warn_raw = os.path.join(a.out, "warnings.raw.tsv")
    cmd = ["dotnet", a.poc, src, "--lifetimes", lt_path, "--out", warn_raw]
    for r in a.refs:
        cmd += ["--refs", r]
    p = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8")
    stats = p.stderr.strip()
    rows = open(warn_raw, encoding="utf-8").read().splitlines()
    with open(os.path.join(a.out, "warnings.tsv"), "w", encoding="utf-8", newline="\n") as f:
        f.write(rows[0] + "\ttest_project\tpath_regex\n")
        for r in rows[1:]:
            rel = r.split("\t", 1)[0]
            _, is_test = owning_project(os.path.join(src, rel))
            label = "nonproduct" if NONPRODUCT.search(rel) else "-"
            f.write(f"{r}\t{'test' if is_test else '-'}\t{label}\n")
    summary = {
        "src": src,
        "registrations": len(raw),
        "test_registrations_dropped": dropped,
        "scoped_names": sum(1 for v in lts["service"].values() if v == "scoped"),
        "mixed_names": sum(1 for v in lts["service"].values() if v == "mixed"),
        "warnings": len(rows) - 1,
        "poc": stats,
    }
    json.dump(summary, open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
