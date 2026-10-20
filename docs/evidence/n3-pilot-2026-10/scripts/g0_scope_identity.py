"""N3 pilot, gate G0: DI001 over saved `services` facts, current core vs the four
pre-registered rules (00-preregistration-g0.md). Research only: reads facts and
.csproj files, imports the unchanged core, writes a TSV of findings.

usage: python -I g0_scope_identity.py --ownnet <Own.NET checkout> \
           --research <direction-research root> --out <dir> [--extra name=facts.json ...]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

TEST_PACKAGES = (
    "Microsoft.NET.Test.Sdk",
    "xunit",
    "xunit.v3",
    "NUnit",
    "MSTest.TestFramework",
    "MSTest",
    "TUnit",
    "BenchmarkDotNet",
)
PKG_RE = re.compile(r'<PackageReference\s+[^>]*Include\s*=\s*"([^"]+)"', re.I)
IS_TEST_RE = re.compile(r"<IsTestProject>\s*true\s*</IsTestProject>", re.I)
# comparison only (rule 1 does not use it): the direction research's path regex
NONPRODUCT = re.compile(
    r"(^|[\\/])(tests?|testing|unittests?|[^\\/]*tests?[^\\/]*|benchmarks?|samples?|examples?"
    r"|demos?|docs?|playground|fixtures?|perf)([\\/]|$)",
    re.I,
)


def resolve(path: str, bases: list[str]) -> str | None:
    for b in bases:
        p = os.path.normpath(os.path.join(b, path))
        if os.path.exists(p):
            return p
    return None


_proj_cache: dict[str, tuple[str | None, bool]] = {}


def owning_project(src: str) -> tuple[str | None, bool]:
    """Nearest ancestor directory holding a .csproj -> (csproj path, is test project)."""
    d = os.path.dirname(src)
    seen = []
    while True:
        if d in _proj_cache:
            res = _proj_cache[d]
            break
        projs = sorted(glob.glob(os.path.join(glob.escape(d), "*.csproj")))
        seen.append(d)
        if projs:
            text = "\n".join(open(p, encoding="utf-8", errors="replace").read() for p in projs)
            pkgs = {m.lower() for m in PKG_RE.findall(text)}
            is_test = bool(IS_TEST_RE.search(text)) or any(t.lower() in pkgs for t in TEST_PACKAGES)
            res = (projs[0], is_test)
            break
        parent = os.path.dirname(d)
        if parent == d:
            res = (None, False)
            break
        d = parent
    for s in seen:
        _proj_cache[s] = res
    return res


def to_services(raw: list[dict], di) -> list:
    # the same field mapping as ownlang/ownir.py::_di_findings
    return [
        di.Service(
            name=str(s.get("name", "?")),
            lifetime=str(s.get("lifetime", "")),
            deps=tuple(s.get("deps", [])),
            weak_deps=tuple(s.get("weak_deps", [])),
            root_resolves=tuple(s.get("root_resolves", [])),
            disposable=s.get("disposable") is True,
            file=str(s.get("file", "?")),
            line=int(s.get("line", 0) or 0),
            ctor_file=str(s.get("ctor_file", "?")),
            ctor_line=int(s.get("ctor_line", 0) or 0),
            ctor_type=str(s.get("ctor_type", "")),
        )
        for s in raw
    ]


def g0_captives(
    services: list, di, own_root: bool = True, proven_only: bool = True
) -> tuple[list[tuple], int]:
    """Rules 3 and 4 over already-filtered registrations (rule 2). Same DI001 rule:
    singleton -> scoped, following transients only. The flags switch a rule off for
    the ablation: own_root=False walks from by_name[s.name] like the core, and
    proven_only=False lets the last registration of a name decide its lifetime."""
    by_name: dict[str, list] = {}
    for s in services:
        by_name.setdefault(s.name, []).append(s)

    def proven(name: str) -> str | None:
        regs = by_name.get(name)
        if not regs:
            return None
        if not proven_only:
            return regs[-1].lifetime
        lts = {r.lifetime for r in regs}
        return lts.pop() if len(lts) == 1 else "mixed"

    mixed = sum(1 for n in by_name if len({r.lifetime for r in by_name[n]}) > 1)
    out = []
    for s in services:
        if s.lifetime != di.SINGLETON:
            continue
        reported, visited = set(), set()
        # rule 3: the root is this registration, not by_name[s.name]
        root = s if own_root else by_name[s.name][-1]
        stack = [(tuple(root.deps), (s.name,))]
        while stack:
            deps, path = stack.pop()
            for dep in deps:
                lt = proven(dep)
                npath = (*path, dep)
                if lt == di.SCOPED:
                    if dep not in reported:
                        reported.add(dep)
                        out.append((s.file, s.line, s.name, dep, " -> ".join(npath), s.ctor_type))
                elif lt == di.TRANSIENT and dep not in visited:
                    visited.add(dep)
                    for r in by_name[dep] if proven_only else by_name[dep][-1:]:
                        stack.append((tuple(r.deps), npath))
    out.sort()
    return out, mixed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ownnet", required=True)
    ap.add_argument("--research", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--extra", action="append", default=[], help="name=facts.json[@source-base]")
    a = ap.parse_args()
    sys.path.insert(0, os.path.abspath(a.ownnet))
    from ownlang import di

    R = os.path.abspath(a.research)
    inputs: list[tuple[str, str, list[str]]] = []
    for p in sorted(glob.glob(os.path.join(R, "evidence", "holdout", "ownnet", "*", "facts.json"))):
        inputs.append(("holdout/" + os.path.basename(os.path.dirname(p)), p, [R]))
    for p in sorted(glob.glob(os.path.join(R, "evidence", "sweep", "runs", "*", "facts.json"))):
        inputs.append(
            (
                "sweep/" + os.path.basename(os.path.dirname(p)),
                p,
                [os.path.join(R, "repos", "Own.NET"), R],
            )
        )
    pair = os.path.join(R, "evidence", "pairs", "rrr-pi-rate_StockPriceSheetPrintService__60")
    for side in ("base", "fix"):
        inputs.append(
            (f"pair/rrr-pi-rate#60/{side}", os.path.join(pair, f"{side}.facts.json"), [R])
        )
    for e in a.extra:
        name, rest = e.split("=", 1)
        fp, _, base = rest.partition("@")
        inputs.append((name, fp, [base or os.path.dirname(fp)]))

    os.makedirs(a.out, exist_ok=True)
    rows, summary, ablation = [], [], []
    for name, fp, bases in inputs:
        facts = json.load(open(fp, encoding="utf-8"))
        raw = facts.get("services", []) if isinstance(facts.get("services"), list) else []
        cur = di.find_captive_dependencies(to_services(raw, di))
        kept, n_test, n_noproj, n_unres, regex_test = [], 0, 0, 0, 0
        for s in raw:
            src = resolve(str(s.get("file", "?")), bases)
            if NONPRODUCT.search(str(s.get("file", ""))):
                regex_test += 1
            if src is None:
                n_unres += 1
                kept.append(s)
                continue
            proj, is_test = owning_project(src)
            if proj is None:
                n_noproj += 1
            if is_test:
                n_test += 1
                continue  # rule 2
            kept.append(s)
        new, mixed = g0_captives(to_services(kept, di), di)
        cur_keys = {(f.file, f.line, f.singleton, f.captured) for f in cur}
        # ablation: each subset of rules 2/3/4 (rule 1 is the input to rule 2)
        for r2 in (False, True):
            for r3 in (False, True):
                for r4 in (False, True):
                    got, _ = g0_captives(
                        to_services(kept if r2 else raw, di), di, own_root=r3, proven_only=r4
                    )
                    keys = {g[:4] for g in got}
                    tag = "".join(n for n, on in (("2", r2), ("3", r3), ("4", r4)) if on) or "none"
                    for k in sorted(cur_keys | keys):
                        ablation.append(
                            (
                                name,
                                tag,
                                k[0],
                                k[1],
                                k[2],
                                k[3],
                                "current" if k in cur_keys else "new",
                                "reported" if k in keys else "-",
                            )
                        )
        new_keys = {r[:4] for r in new}
        for f in cur:
            k = (f.file, f.line, f.singleton, f.captured)
            rows.append(
                (
                    name,
                    "removed" if k not in new_keys else "kept",
                    f.file,
                    f.line,
                    f.singleton,
                    f.captured,
                    " -> ".join(f.path),
                    f.consumed_type,
                    "nonproduct" if NONPRODUCT.search(f.file) else "product",
                )
            )
        for r in new:
            if r[:4] not in cur_keys:
                rows.append(
                    (
                        name,
                        "NEW",
                        r[0],
                        r[1],
                        r[2],
                        r[3],
                        r[4],
                        r[5],
                        "nonproduct" if NONPRODUCT.search(r[0]) else "product",
                    )
                )
        summary.append(
            (
                name,
                len(raw),
                n_test,
                regex_test,
                n_noproj,
                n_unres,
                mixed,
                len(cur),
                len(new),
                sum(1 for r in new if r[:4] not in cur_keys),
            )
        )

    with open(os.path.join(a.out, "g0_findings.tsv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("input\tstatus\tfile\tline\tsingleton\tcaptured\tpath\timpl\tpath_regex\n")
        for r in rows:
            f.write("\t".join(map(str, r)) + "\n")
    with open(os.path.join(a.out, "g0_summary.tsv"), "w", encoding="utf-8", newline="\n") as f:
        f.write(
            "input\tregistrations\ttest_project\tpath_regex_nonproduct\tno_csproj\tunresolved_file\t"
            "mixed_lifetime_names\tdi001_current\tdi001_g0\tdi001_g0_new\n"
        )
        for r in summary:
            f.write("\t".join(map(str, r)) + "\n")
    with open(os.path.join(a.out, "g0_ablation.tsv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("input\trules_on\tfile\tline\tsingleton\tcaptured\torigin\tresult\n")
        for r in ablation:
            f.write("\t".join(map(str, r)) + "\n")
    print(open(os.path.join(a.out, "g0_summary.tsv"), encoding="utf-8").read())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
