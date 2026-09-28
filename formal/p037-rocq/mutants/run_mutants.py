#!/usr/bin/env python3
"""Negative controls for the plain-Rocq P-037 proof package: every mutant
must be REJECTED.

The exporter under export/ links formal/p037-kernel directly (no copied
kernel semantics); each mutant copies formal/p037-kernel and this package
into a temp tree, applies one textual mutation, regenerates RustTables.v
with the exporter, and re-checks the Rocq files in order. A mutant that
still checks is a vacuous theorem or a blind seam; the script then exits 1.

Rocq-side mutants (R*) break the proof model; kernel-side mutants (D*) break
the Rust kernel and must be caught by the drift seam (Correspondence.v).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
FORMAL = PKG.parent
FILES = ["Lfp", "P037", "RustTables", "Correspondence"]
WARN = ["-w", "-notation-for-abbreviation"]

# (id, what it models, file relative to formal/, old text, new text)
MUTANTS = [
    ("R1", "non-commutative join (no|must = must, must|no = may)",
     "p037-rocq/theories/P037.v",
     "  | _, _ => May\n  end.\nDefinition fin",
     "  | No, Must => Must\n  | _, _ => May\n  end.\nDefinition fin"),
    ("R2", "law-preserving wrong join ('must wins': no|must = must)",
     "p037-rocq/theories/P037.v",
     "  | _, _ => May\n  end.\nDefinition fin",
     "  | No, Must | Must, No => Must\n  | _, _ => May\n  end.\nDefinition fin"),
    ("R3", "unsafe application: select/collapse the UNfinalized cells (F2)",
     "p037-rocq/theories/P037.v",
     "  let f := cfin c in", "  let f := c in"),
    ("R4", "dynamic split: `neg` orientation depends on the state",
     "p037-rocq/theories/P037.v",
     "  | Neg => (c.2, c.1)", "  | Neg => if transfer_beq c.1 Must then c else (c.2, c.1)"),
    ("R5", "fabricated must: const-pos reads a bottom cell as must",
     "p037-rocq/theories/P037.v",
     "  | ConstPos => diag c.1", "  | ConstPos => diag (if c.1 is Bot then Must else c.1)"),
    ("R6", "chaotic theorem without the fairness hypothesis",
     "p037-rocq/theories/Lfp.v",
     "Theorem chaotic_is_lfp sched : (forall i, In i sched) ->",
     "Theorem chaotic_is_lfp sched : (forall i, In i sched \\/ True) ->"),
    ("R7", "Jacobi pass bound one short (N instead of N + 1)",
     "p037-rocq/theories/Lfp.v",
     "Theorem jacobi_is_lfp : exists x, jacobi (S N) sbot = Some x /\\ x =1 lfp.",
     "Theorem jacobi_is_lfp : exists x, jacobi N sbot = Some x /\\ x =1 lfp."),
    ("D1", "KERNEL: law-preserving wrong join ('must wins')",
     "p037-kernel/src/lib.rs",
     "            (Self::Must, Self::Must) => Self::Must,\n            _ => Self::May,",
     "            (Self::Must, Self::Must) => Self::Must,\n"
     "            (Self::No, Self::Must) | (Self::Must, Self::No) => Self::Must,\n"
     "            _ => Self::May,"),
    ("D2", "KERNEL: collapsed() keeps the branch masks (structural, not a table)",
     "p037-kernel/src/lib.rs",
     "                    transform: Transform::Opaque,\n                    mask: Mask::Both,",
     "                    transform: Transform::Opaque,\n                    mask: e.mask,"),
    ("D3", "KERNEL: step() drops the seed (structural, not a table)",
     "p037-kernel/src/lib.rs",
     "        let mut acc = c.seed;\n        for slot in &c.edges {\n"
     "            if let Some(e) = slot {\n"
     "                let callee = x.get(e.callee).copied().unwrap_or(Cells::BOT);",
     "        let mut acc = Cells::BOT;\n        for slot in &c.edges {\n"
     "            if let Some(e) = slot {\n"
     "                let callee = x.get(e.callee).copied().unwrap_or(Cells::BOT);"),
    ("D4", "KERNEL: `neg` transform forgets the swap",
     "p037-kernel/src/lib.rs",
     "        Transform::Neg => callee.swap(),", "        Transform::Neg => callee,"),
]


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def check(tree: Path) -> str | None:
    """None if everything checks, else a one-line description of the failure."""
    pkg = tree / "p037-rocq"
    exp = run(["cargo", "run", "-q", "--manifest-path", "export/Cargo.toml"], pkg)
    if exp.returncode != 0:
        return "exporter: " + (exp.stderr.strip().splitlines() or ["failed"])[-1]
    (pkg / "theories/RustTables.v").write_text(exp.stdout)
    for f in FILES:
        cmd = ["rocq", "compile", *WARN, "-Q", "theories", "PlainSpike", f"theories/{f}.v"]
        r = run(cmd, pkg)
        if r.returncode != 0:
            out = r.stdout + r.stderr
            where = re.search(r'File "[^"]*", line (\d+)', out)
            err = [ln for ln in out.splitlines() if ln.startswith("Error")]
            line = int(where.group(1)) if where else 0
            src = (pkg / f"theories/{f}.v").read_text().splitlines()
            # the nearest enclosing statement, for the report
            stmt = next((s for s in reversed(src[:line])
                         if re.match(r"(Lemma|Theorem|Corollary|Definition|Fixpoint)\b", s)), "?")
            return f"{f}.v:{line} [{stmt.split(':')[0].strip()}] {err[0] if err else ''}"
    return None


def main() -> int:
    survivors = []
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "formal"
        ignore = shutil.ignore_patterns("target", "*.vo", "*.vok", "*.vos", "*.glob", ".*.aux")
        shutil.copytree(FORMAL / "p037-kernel", base / "p037-kernel", ignore=ignore)
        shutil.copytree(PKG, base / "p037-rocq", ignore=ignore)
        pristine = {p: p.read_text() for p in base.rglob("*") if p.suffix in {".v", ".rs"}}
        baseline = check(base)
        print(f"baseline (no mutation): {'OK' if baseline is None else 'FAILED: ' + baseline}")
        if baseline is not None:
            return 2
        for mid, what, rel, old, new in MUTANTS:
            for p, txt in pristine.items():
                p.write_text(txt)
            target = base / rel
            src = target.read_text()
            if src.count(old) != 1:
                print(f"{mid}: mutation site not found exactly once in {rel}")
                return 2
            target.write_text(src.replace(old, new))
            res = check(base)
            verdict = "KILLED  " if res else "SURVIVED"
            print(f"{mid} {verdict} {what}\n      -> {res or 'everything still checks'}")
            if res is None:
                survivors.append(mid)
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
