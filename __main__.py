"""
Command-line driver for the OwnLang PoC.

    python -m ownlang check  file.own      # report ownership diagnostics
    python -m ownlang emit   file.own      # check, then print generated C#
    python -m ownlang cfg    file.own      # dump the control-flow graph
    python -m ownlang report file.own      # buffer storage report + .ownreport.json

Exit code is non-zero if any error-level diagnostic was produced.
"""

from __future__ import annotations

import sys

from .parser import parse, ParseError
from .lexer import LexError
from .cfg import build_cfg, collect_signatures, collect_policies, CFG
from .analysis import analyze
from .codegen import generate
from .report import build_report, render_report
from .diagnostics import Diagnostic, Severity


def _collect(src: str) -> tuple[list[Diagnostic], object | None]:
    try:
        mod = parse(src)
    except (ParseError, LexError) as e:
        line = getattr(e, "line", 0)
        return [Diagnostic("OWN020", str(e).split(": ", 1)[-1], line)], None
    rnames = {r.name for r in mod.resources}
    sigs = collect_signatures(mod)
    pols = collect_policies(mod)
    diags: list[Diagnostic] = []
    for fn in mod.functions:
        cfg, d1 = build_cfg(fn, rnames, sigs, pols)
        d2 = analyze(cfg)
        diags.extend(d1)
        diags.extend(d2)
    diags.sort(key=lambda d: (d.line, d.code))
    return diags, mod


def cmd_check(path: str) -> int:
    src = _read(path)
    diags, _ = _collect(src)
    errors = [d for d in diags if d.severity == Severity.ERROR]
    for d in diags:
        print(d.render(path))
    if not diags:
        print(f"{path}: ok — no ownership problems found")
    n = len(errors)
    print(f"\n{n} error{'s' if n != 1 else ''}.")
    return 1 if errors else 0


def cmd_emit(path: str) -> int:
    src = _read(path)
    diags, mod = _collect(src)
    errors = [d for d in diags if d.severity == Severity.ERROR]
    if errors or mod is None:
        for d in diags:
            print(d.render(path), file=sys.stderr)
        print(f"\nrefusing to generate C#: {len(errors)} error(s).", file=sys.stderr)
        return 1
    print(generate(mod))  # type: ignore[arg-type]
    return 0


def cmd_cfg(path: str) -> int:
    src = _read(path)
    try:
        mod = parse(src)
    except (ParseError, LexError) as e:
        print(str(e), file=sys.stderr)
        return 1
    rnames = {r.name for r in mod.resources}
    sigs = collect_signatures(mod)
    pols = collect_policies(mod)
    for fn in mod.functions:
        cfg, _ = build_cfg(fn, rnames, sigs, pols)
        _print_cfg(cfg)
    return 0


def cmd_report(path: str) -> int:
    """Emit the compile-time buffer report: what storage policy the checker and
    codegen settled on for every buffer, and which checks passed. Prints a
    human summary to stdout and writes the machine-readable .ownreport.json."""
    src = _read(path)
    diags, mod = _collect(src)
    if mod is None:
        for d in diags:
            print(d.render(path), file=sys.stderr)
        return 1
    report = build_report(mod, diags)  # type: ignore[arg-type]
    print(render_report(report))
    out_path = path.rsplit(".", 1)[0] + ".ownreport.json"
    import json
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\nwrote {out_path}")
    return 0


def _print_cfg(cfg: CFG) -> None:
    print(f"fn {cfg.fn_name}  (entry: B{cfg.entry}, "
          f"params: {[p.name for p in cfg.params]})")
    for b in cfg.blocks:
        succ = ", ".join(f"B{s}" for s in b.succ) or "(exit)"
        print(f"  B{b.id} [{b.label}] -> {succ}")
        for ins in b.instrs:
            print(f"      {_fmt_instr(ins)}")
    print()


def _fmt_instr(ins) -> str:
    from .cfg import (Acquire, AcquireBuffer, MoveInto, Release, Use, Invoke,
                      BorrowStart, BorrowEnd, Return)
    if isinstance(ins, Acquire):
        return f"acquire {ins.sym.name} : {ins.resource}"
    if isinstance(ins, AcquireBuffer):
        i = ins.info
        size = i.size_const if i.size_is_const else (i.size_var or "?")
        return (f"buffer {ins.sym.name} : {i.mode.value}(size={size}, "
                f"inline={i.inline_bytes}, fallback={'pool' if i.fallback_pool else 'none'})")
    if isinstance(ins, MoveInto):
        return f"move {ins.src.name} -> {ins.dst.name}"
    if isinstance(ins, Release):
        return f"release {ins.sym.name}"
    if isinstance(ins, Use):
        return f"use {ins.sym.name}"
    if isinstance(ins, Invoke):
        parts = []
        for s, eff in ins.args:
            nm = s.name if s is not None else "<lit>"
            parts.append(f"{eff.name.lower()} {nm}")
        return f"invoke {ins.callee}({', '.join(parts)})"
    if isinstance(ins, BorrowStart):
        return f"borrow{'_mut' if ins.mut else ''} start {ins.owner.name} as {ins.binding.name}"
    if isinstance(ins, BorrowEnd):
        return f"borrow{'_mut' if ins.mut else ''} end {ins.owner.name}"
    if isinstance(ins, Return):
        return f"return {ins.sym.name if ins.sym else ''}".rstrip()
    return repr(ins)


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in {"check", "emit", "cfg", "report"}:
        print(__doc__)
        return 2
    cmd, path = argv[0], argv[1]
    return {"check": cmd_check, "emit": cmd_emit, "cfg": cmd_cfg,
            "report": cmd_report}[cmd](path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
