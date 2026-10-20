# ruff: noqa: E501  (research script; long docstring/comment lines)
"""R3: the unchanged extractor (A-ext vs B-ext) and the Python core on each project (00-preregistration.md §2).

B-ext = OWN_EXTRA_REF_DIRS with B's framework reference packs + one --ref-dir per B package compile folder.
The extractor keeps its TPA first, so B-ext is what today's extractor can be given; it is not identical to B.

usage: python -I run_r3.py --research <root> --proj <build_modes out> --extractor <dll> --ownnet <checkout> --out <dir>
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import subprocess

DOTNET = r"C:\Program Files\dotnet"


def run(cmd: list[str], env: dict, cwd: str, log: str) -> int:
    with open(log, "w", encoding="utf-8") as f:
        return subprocess.run(cmd, env=env, cwd=cwd, stdout=f, stderr=subprocess.STDOUT).returncode


def fact_counts(facts: dict) -> dict:
    c = collections.Counter()
    for k, v in facts.items():
        if isinstance(v, list):
            c[k] = len(v)
    acq = sum(
        1 for fn in facts.get("functions", []) for n in json.dumps(fn).split('"op": "acquire"')[1:]
    )
    c["flow_acquire"] = acq
    c["stats"] = json.dumps(facts.get("stats", {}))[:200]
    return dict(c)


def findings(sarif_path: str) -> list[tuple[str, str, int, str]]:
    try:
        log = json.load(open(sarif_path, encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for r in log.get("runs", [{}])[0].get("results", []):
        loc = r.get("locations", [{}])[0].get("physicalLocation", {})
        out.append(
            (
                r.get("ruleId", ""),
                loc.get("artifactLocation", {}).get("uri", ""),
                loc.get("region", {}).get("startLine", 0),
                r.get("message", {}).get("text", "")[:200],
            )
        )
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--research", required=True)
    ap.add_argument("--proj", required=True)
    ap.add_argument("--extractor", required=True)
    ap.add_argument("--ownnet", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    manifest = json.load(open(os.path.join(a.proj, "manifest.json"), encoding="utf-8"))
    summary = []
    for m in manifest:
        pid = m["id"]
        csproj = os.path.join(a.research, m["project"])
        refs_b = [
            x
            for x in open(os.path.join(a.proj, pid, "refs_B.txt"), encoding="utf-8")
            .read()
            .split("\n")
            if x
        ]
        packs = sorted(
            {os.path.dirname(p) for p in refs_b if os.sep + "packs" + os.sep in p or "/packs/" in p}
        )
        pkg_dirs = sorted(
            {
                os.path.dirname(p)
                for p in refs_b
                if p not in packs and "packs" not in p.split(os.sep)
            }
        )
        out = os.path.join(a.out, pid)
        os.makedirs(out, exist_ok=True)
        rows = {}
        for mode in ("A", "B"):
            env = dict(os.environ)
            env.pop("OWN_EXTRA_REF_DIRS", None)
            cmd = [
                "dotnet",
                a.extractor,
                csproj,
                "-o",
                os.path.join(out, f"facts_{mode}.json"),
                "--flow-locals",
                "--stats",
            ]
            if mode == "B":
                env["OWN_EXTRA_REF_DIRS"] = os.pathsep.join(packs)
                for d in pkg_dirs:
                    cmd += ["--ref-dir", d]
            rc = run(cmd, env, a.research, os.path.join(out, f"extract_{mode}.log"))
            facts = (
                json.load(open(os.path.join(out, f"facts_{mode}.json"), encoding="utf-8"))
                if rc == 0
                else {}
            )
            sarif = os.path.join(out, f"findings_{mode}.sarif")
            crc = -1
            if rc == 0:
                with open(sarif, "w", encoding="utf-8") as f:
                    crc = subprocess.run(
                        [
                            "python",
                            "-m",
                            "ownlang",
                            "ownir",
                            os.path.join(out, f"facts_{mode}.json"),
                            "--format",
                            "sarif",
                            "--severity",
                            "warning",
                        ],
                        cwd=a.ownnet,
                        stdout=f,
                        stderr=subprocess.DEVNULL,
                    ).returncode
            rows[mode] = {
                "extractor_rc": rc,
                "core_rc": crc,
                "facts": fact_counts(facts),
                "findings": findings(sarif),
                "packs": packs if mode == "B" else [],
                "ref_dirs": len(pkg_dirs) if mode == "B" else 0,
            }
        fa, fb = set(rows["A"]["findings"]), set(rows["B"]["findings"])
        rule_a = collections.Counter(f[0] for f in fa)
        rule_b = collections.Counter(f[0] for f in fb)
        diff = {"only_A": sorted(fa - fb), "only_B": sorted(fb - fa)}
        json.dump(
            {"A": rows["A"], "B": rows["B"], "diff": diff},
            open(os.path.join(out, "r3.json"), "w", encoding="utf-8"),
            indent=1,
        )
        summary.append(
            {
                "id": pid,
                "A_rc": (rows["A"]["extractor_rc"], rows["A"]["core_rc"]),
                "B_rc": (rows["B"]["extractor_rc"], rows["B"]["core_rc"]),
                "facts_A": {k: v for k, v in rows["A"]["facts"].items() if k != "stats"},
                "facts_B": {k: v for k, v in rows["B"]["facts"].items() if k != "stats"},
                "rules_A": dict(rule_a),
                "rules_B": dict(rule_b),
                "only_A": len(diff["only_A"]),
                "only_B": len(diff["only_B"]),
            }
        )
        print(json.dumps(summary[-1]))
    json.dump(
        summary, open(os.path.join(a.out, "r3_summary.json"), "w", encoding="utf-8"), indent=1
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
