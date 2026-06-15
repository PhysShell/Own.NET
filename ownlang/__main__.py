"""
Command-line driver for the OwnLang PoC.

    python -m ownlang check  file.own      # report ownership diagnostics
    python -m ownlang emit   file.own      # check, then print generated C#
    python -m ownlang cfg    file.own      # dump the control-flow graph
    python -m ownlang report file.own      # buffer storage report + .ownreport.json
    python -m ownlang ownir  facts.json    # check OwnIR facts extracted from C# (P-001)
    python -m ownlang ownir  facts.json --format github|msbuild|human

`--format` (ownir only) selects the finding surface: `human` (default CLI line),
`github` (CI annotations on the PR diff), or `msbuild` (VS Error List).

Exit code is non-zero if any error-level diagnostic was produced.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cfg import Instr

from .analysis import analyze
from .buffers import validate_policies
from .cfg import CFG, build_cfg, collect_kinds, collect_policies, collect_signatures
from .codegen import generate
from .diagnostics import Diagnostic, Severity
from .lexer import LexError
from .lifetimes import check_lifetimes
from .parser import ParseError, parse
from .report import build_report, render_report


def check_module(mod: object) -> list[Diagnostic]:
    """Run the full ownership pipeline over an already-parsed module and return
    its diagnostics. This is the AST-level entry to the *one* checker: callers
    that already hold a `Module` (the OwnIR bridge lowers facts straight to one)
    use this instead of re-serialising to source text and re-parsing it."""
    rnames = {r.name for r in mod.resources}  # type: ignore[attr-defined]
    sigs = collect_signatures(mod)  # type: ignore[arg-type]
    pols = collect_policies(mod)  # type: ignore[arg-type]
    kinds = collect_kinds(mod)  # type: ignore[arg-type]
    diags: list[Diagnostic] = list(validate_policies(pols))
    diags.extend(check_lifetimes(mod))  # type: ignore[arg-type]
    for fn in mod.functions:  # type: ignore[attr-defined]
        cfg, d1 = build_cfg(fn, rnames, sigs, pols, kinds)
        d2 = analyze(cfg)
        diags.extend(d1)
        diags.extend(d2)
    diags.sort(key=lambda d: (d.line, d.code))
    return diags


def _collect(src: str) -> tuple[list[Diagnostic], object | None]:
    try:
        mod = parse(src)
    except (ParseError, LexError) as e:
        line = getattr(e, "line", 0)
        return [Diagnostic("OWN020", str(e).split(": ", 1)[-1], line)], None
    return check_module(mod), mod


def cmd_check(path: str) -> int:
    src = _read(path)
    diags, _ = _collect(src)
    errors = [d for d in diags if d.severity == Severity.ERROR]
    for d in diags:
        print(d.render_pretty(path, src))
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
            print(d.render_pretty(path, src), file=sys.stderr)
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
    # surface diagnostics (e.g. a mistyped buffer mode) without crashing the
    # report; the report still covers every well-formed buffer.
    errors = [d for d in diags if d.severity == Severity.ERROR]
    for d in diags:
        print(d.render(path), file=sys.stderr)
    report = build_report(mod, diags)  # type: ignore[arg-type]
    print(render_report(report))
    out_path = path.rsplit(".", 1)[0] + ".ownreport.json"
    import json
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\nwrote {out_path}")
    return 1 if errors else 0


def _print_cfg(cfg: CFG) -> None:
    print(f"fn {cfg.fn_name}  (entry: B{cfg.entry}, "
          f"params: {[p.name for p in cfg.params]})")
    for b in cfg.blocks:
        succ = ", ".join(f"B{s}" for s in b.succ) or "(exit)"
        print(f"  B{b.id} [{b.label}] -> {succ}")
        for ins in b.instrs:
            print(f"      {_fmt_instr(ins)}")
    print()


def _fmt_instr(ins: Instr) -> str:
    from .cfg import (
        Acquire,
        AcquireBuffer,
        BorrowEnd,
        BorrowStart,
        Invoke,
        MoveInto,
        Release,
        Return,
        Use,
    )
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
    with open(path, encoding="utf-8") as f:
        return f.read()


def cmd_ownir(path: str, fmt: str = "human") -> int:
    """Check OwnIR facts (extracted from real C# by the Roslyn frontend) through
    the same core, surfacing findings at their C# locations (P-001). `fmt`
    selects the surface: human (CLI), github (CI annotations), msbuild (VS)."""
    from .ownir import OwnIRError, check_facts, load, render_finding
    try:
        findings = check_facts(load(path))
    except OwnIRError as e:
        # bad facts / a drifted contract: a clear one-liner, not a traceback.
        print(f"{path}: error: {e}", file=sys.stderr)
        return 2
    # In a machine format, stdout carries only the annotations/diagnostics a host
    # (GitHub, MSBuild/VS) parses; the human summary goes to stderr so it cannot
    # pollute that stream.
    machine = fmt in {"github", "msbuild"}
    summary_to = sys.stderr if machine else sys.stdout
    for f in findings:
        print(render_finding(f, fmt))
    if not findings:
        print(f"{path}: ok — no subscription leaks found", file=summary_to)
    n = len(findings)
    print(f"\n{n} finding{'s' if n != 1 else ''}.", file=summary_to)
    return 1 if findings else 0


_FORMATS = {"human", "github", "msbuild"}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"check", "emit", "cfg", "report", "ownir"}:
        print(__doc__)
        return 2
    cmd = argv[0]
    # Pull the optional `--format X` / `--format=X` flag (ownir only) out of the
    # arguments; everything else is positional. Keeps the other commands' single
    # positional-path contract intact.
    fmt = "human"
    positional: list[str] = []
    rest = argv[1:]
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--format":
            if i + 1 >= len(rest):
                print("--format requires a value: human|github|msbuild",
                      file=sys.stderr)
                return 2
            fmt, i = rest[i + 1], i + 2
            continue
        if a.startswith("--format="):
            fmt, i = a.split("=", 1)[1], i + 1
            continue
        positional.append(a)
        i += 1
    # exactly one positional (the path/file); zero or extra args is a usage error
    # (a silently-ignored extra arg hides a caller mistake).
    if len(positional) != 1:
        print(__doc__)
        return 2
    if fmt not in _FORMATS:
        print(f"unknown --format {fmt!r} (choose: {', '.join(sorted(_FORMATS))})",
              file=sys.stderr)
        return 2
    if cmd != "ownir" and fmt != "human":
        print("--format only applies to `ownir`", file=sys.stderr)
        return 2
    path = positional[0]
    if cmd == "ownir":
        return cmd_ownir(path, fmt)
    return {"check": cmd_check, "emit": cmd_emit, "cfg": cmd_cfg,
            "report": cmd_report}[cmd](path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
