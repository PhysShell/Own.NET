"""
Command-line driver for the OwnLang PoC.

    python -m ownlang check  file.own      # report ownership diagnostics
    python -m ownlang check  file.own --format sarif   # SARIF 2.1.0 log (code scanning)
    python -m ownlang emit   file.own      # check, then print generated C#
    python -m ownlang cfg    file.own      # dump the control-flow graph (human debug view)
    python -m ownlang cfg    file.own --format json   # canonical CFG JSON (oracle seam)
    python -m ownlang report file.own      # buffer storage report + .ownreport.json
    python -m ownlang ownir  facts.json    # check OwnIR facts extracted from C# (P-001)
    python -m ownlang ownir  facts.json --format github|msbuild|human|sarif
    python -m ownlang summaries facts.json # dump solved method-ownership summaries
                                           # (MOS) + extern log — deterministic JSON
    python -m ownlang explain OWN001 [DI002 ...]     # explain diagnostic code(s): what/why/fix
    python -m ownlang explain --json findings.json   # explain every code in a findings/SARIF file

`explain` is the diagnostic catalogue side of the CLI (the `ownsharp explain` the
roslyn-tools-shaped surface advertises): it prints what a code means, why it fires,
and how to fix it. It lives in the core, next to the catalogue, because there is one
checker — the C# extractor emits facts, it does not own the diagnostics.

`--format` selects the finding surface. On `ownir`: `human` (default CLI line),
`github` (CI annotations on the PR diff), `msbuild` (VS Error List), or `sarif`
(a SARIF 2.1.0 log — GitHub code scanning, and the cross-tool oracle reads it too).
On `check` it is `human` (default) or `sarif` — the `.own` flow diagnostics as a
SARIF log carrying each finding's evidence slice (relatedLocations / codeFlows);
`github`/`msbuild` are ownir-only (they render a Finding, not a Diagnostic).
`--severity` (ownir only) picks how the host shows a finding — `error` (default,
fails a build / red check) or `warning` (advisory). It is a presentation choice;
the finding is still the core's verdict.
`--verbosity` (ownir only) is `quiet` (errors only — hide the advisory notes:
OWN050 "leakage analysis skipped", OWN051 "ownership transfer unverified",
OWN052 "summaries skipped"), `normal` (default), or `verbose` (also print a
per-code breakdown).

Exit code is non-zero if any error-level diagnostic was produced.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import TYPE_CHECKING, Any

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


def cmd_check(path: str, fmt: str = "human", severity: str = "error") -> int:
    src = _read(path)
    diags, _ = _collect(src)
    errors = [d for d in diags if d.severity == Severity.ERROR]
    if fmt == "sarif":
        # SARIF 2.1.0 log for GitHub code scanning — carries each diagnostic's
        # structured evidence slice as relatedLocations / codeFlows. The exit code
        # still reflects the verdict, so `check --format sarif` gates CI the same
        # way the human surface does.
        import json

        from .diag_sarif import build_sarif
        print(json.dumps(build_sarif(diags, path, severity), indent=2))
        return 1 if errors else 0
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


def cmd_cfg(path: str, fmt: str = "human") -> int:
    src = _read(path)
    try:
        mod = parse(src)
    except (ParseError, LexError) as e:
        print(str(e), file=sys.stderr)
        return 1
    rnames = {r.name for r in mod.resources}
    sigs = collect_signatures(mod)
    pols = collect_policies(mod)
    kinds = collect_kinds(mod)
    cfgs = [build_cfg(fn, rnames, sigs, pols, kinds)[0] for fn in mod.functions]
    if fmt == "json":
        # The canonical CFG-layer oracle seam (P-022 step 0): a frozen,
        # deterministic JSON contract the Rust port is diffed against. The
        # human dump below stays a debug view, not a contract. Canonical text
        # (sorted keys) is the contract's own dump, not an ad-hoc json.dumps.
        from .cfg_json import canonical_json
        print(canonical_json(cfgs))
        return 0
    for cfg in cfgs:
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


# A diagnostic code is OWN/WPF/DI followed by three digits. Used to validate an
# `explain` argument and to harvest codes out of a findings/SARIF JSON file.
_CODE_RE = re.compile(r"^(OWN|WPF|DI)\d{3}$")


def _explain_one(code: str) -> str:
    """The explanation block for one code: its title and the long-form what/why/fix
    (falling back to just the title when no long-form exists), or an 'unknown code'
    line. Pure text so it is trivially testable."""
    from .diagnostics import EXPLANATIONS, TITLES
    code = code.upper()
    title = TITLES.get(code)
    body = EXPLANATIONS.get(code)
    if title is None and body is None:
        return f"{code}: unknown diagnostic code"
    out = f"{code}: {title}" if title else code
    if body:
        out += "\n\n" + body
    return out


def _codes_from_json(obj: object) -> list[str]:
    """Every distinct diagnostic code reachable in a decoded JSON value, in first-seen
    order. Harvests the values of any `code`/`ruleId` key (so it reads a findings array,
    a single finding, or a SARIF log's results) that look like a diagnostic code."""
    seen: dict[str, None] = {}

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, val in node.items():
                if key in {"code", "ruleId"} and isinstance(val, str) and _CODE_RE.match(val):
                    seen.setdefault(val, None)
                else:
                    walk(val)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(obj)
    return list(seen)


def cmd_explain(codes: list[str], json_path: str | None) -> int:
    """Explain diagnostic code(s): print what each means, why it fires, and how to fix
    it. Codes come from the command line (`explain OWN001 DI002`) and/or are harvested
    from a findings/SARIF JSON (`--json findings.json`), so you can explain exactly the
    codes a run produced. Exit 2 on a usage error (no codes) or an unreadable JSON."""
    import json
    all_codes = list(codes)
    if json_path is not None:
        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"explain: cannot read {json_path}: {e}", file=sys.stderr)
            return 2
        found = _codes_from_json(data)
        if not found:
            print(f"explain: no diagnostic codes found in {json_path}", file=sys.stderr)
            return 2
        # de-dupe against any codes already given on the command line, preserving order
        for c in found:
            if c not in all_codes:
                all_codes.append(c)
    if not all_codes:
        print("explain: give a code (e.g. OWN001) or --json <findings.json>", file=sys.stderr)
        return 2
    from .diagnostics import EXPLANATIONS, TITLES
    print("\n\n".join(_explain_one(c) for c in all_codes))
    # If every requested code is unknown, that is almost certainly a typo — fail (2)
    # rather than silently succeed. A mix of known + unknown still exits 0.
    if all(c.upper() not in TITLES and c.upper() not in EXPLANATIONS for c in all_codes):
        return 2
    return 0


def cmd_summaries(path: str) -> int:
    """Dump the solved Method Ownership Summaries (MOS) + the extern-boundary
    log for an OwnIR facts file as one deterministic JSON document on stdout
    (roadmap stage 1). The debugging answer to "why did this call stay plain /
    consume / fresh?" — and the frozen parity surface the Rust port of the
    inference layer is diffed against, so its output contract is byte-stable:
    sorted method keys, sorted extern log, fixed field order. Exit code is 0
    even when the solve degraded (the `degraded` field carries the reason —
    this surface reports state, it does not judge); 2 only for unreadable
    facts, like `ownir`."""
    import json

    from .ownir import OwnIRError, dump_summaries, load
    try:
        doc = dump_summaries(load(path))
    except OwnIRError as e:
        print(f"{path}: error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(doc, indent=2, sort_keys=True))
    return 0


def cmd_ownir(path: str, fmt: str = "human", severity: str = "error",
              verbosity: str = "normal") -> int:
    """Check OwnIR facts (extracted from real C# by the Roslyn frontend) through
    the same core, surfacing findings at their C# locations (P-001). `fmt`
    selects the surface: human (CLI), github (CI annotations), msbuild (VS),
    sarif (SARIF 2.1.0 log);
    `severity` picks how the host shows them (error/warning); `verbosity` is
    `quiet` (errors only — hide the advisory notes), `normal` (default), or
    `verbose` (also print a per-code breakdown)."""
    from .ownir import OwnIRError, build_sarif, check_facts, load, render_finding
    try:
        findings = check_facts(load(path))
    except OwnIRError as e:
        # bad facts / a drifted contract: a clear one-liner, not a traceback.
        print(f"{path}: error: {e}", file=sys.stderr)
        return 2
    # In a machine format, stdout carries only the annotations/diagnostics a host
    # (GitHub, MSBuild/VS) parses; the human summary goes to stderr so it cannot
    # pollute that stream.
    machine = fmt in {"github", "msbuild", "sarif"}
    summary_to = sys.stderr if machine else sys.stdout
    # Advisory findings (OWN050 "leakage analysis skipped", OBL005 "dead protocol
    # rule") are always shown as warnings regardless of --severity, and never
    # affect the exit code — they are coverage/hygiene notes, not verdicts.
    # Inline `[OwnIgnore("reason")]` suppressions (P-004, #209) are counted and carried in
    # SARIF `suppressions`, but kept OUT of the human findings stream and the exit code —
    # visibility over silence, without failing the run. Everything else is "active".
    suppressed = [f for f in findings if f.suppressed]
    active = [f for f in findings if not f.suppressed]
    leaks = [f for f in active if not f.advisory]
    notes = [f for f in active if f.advisory]
    shown = leaks if verbosity == "quiet" else active
    if fmt == "sarif":
        # SARIF is one document for the whole run (not a line per finding): stdout
        # carries only the JSON; the summary goes to stderr like the other machine
        # formats. build_sarif applies the same per-finding severity policy below.
        # Suppressed findings ride along (marked with a `suppressions` array) so a
        # SARIF consumer can count them rather than losing them.
        import json
        print(json.dumps(build_sarif(shown + suppressed, severity), indent=2))
    else:
        for f in shown:
            # Severity is the weaker of the host's --severity and the finding's own
            # intrinsic level: an advisory note (OWN050) is always a warning; a
            # global `--severity warning` downgrades everything; and a finding the
            # extractor could not prove a leak (an injected-source subscription,
            # f.severity == "warning") shows as a warning even at the default error
            # level (P-004).
            if f.advisory or severity == "warning" or f.severity == "warning":
                fsev = "warning"
            else:
                fsev = severity
            print(render_finding(f, fmt, fsev))
    if not shown:
        print(f"{path}: ok — no subscription leaks found", file=summary_to)
    n = len(leaks)
    summary = f"\n{n} finding{'s' if n != 1 else ''}"
    if notes:
        # the advisory band is no longer only OWN050 (OBL005 and the OWN051/OWN052
        # interprocedural notes ride it too) — name the codes actually present
        # instead of hardcoding one.
        note_codes = "/".join(sorted({x.code for x in notes}))
        summary += (f" ({len(notes)} advisory hidden)" if verbosity == "quiet"
                    else f", {len(notes)} advisory ({note_codes})")
    if suppressed:
        # counted, never silent: [OwnIgnore] suppressions are tallied here and carried in
        # SARIF `suppressions`, but they do not print as findings and do not fail the run.
        summary += f", {len(suppressed)} suppressed ([OwnIgnore])"
    print(summary + ".", file=summary_to)
    if verbosity == "verbose" and findings:
        by_code: dict[str, int] = {}
        for f in findings:
            by_code[f.code] = by_code.get(f.code, 0) + 1
        breakdown = ", ".join(f"{c}={by_code[c]}" for c in sorted(by_code))
        print(f"  by code: {breakdown}", file=summary_to)
    return 1 if leaks else 0


def _own_fix_parse(
    args: list[str], flags: set[str], multi: set[str]
) -> tuple[list[str], dict[str, Any]] | None:
    """Split `--flag value` (flags/multi) from positionals; None on any arg error."""
    positional: list[str] = []
    opts: dict[str, Any] = {m: [] for m in multi}
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            if a not in flags and a not in multi:
                print(f"own-fix: unknown flag {a}", file=sys.stderr)
                return None
            if i + 1 >= len(args):
                print(f"own-fix: {a} requires a value", file=sys.stderr)
                return None
            if a in multi:
                opts[a].append(args[i + 1])
            else:
                opts[a] = args[i + 1]
            i += 2
        else:
            positional.append(a)
            i += 1
    return positional, opts


def _read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write_atomic(path: str, obj: Any) -> int:
    """Write only after the object is fully built; a bad path is a clean exit 2."""
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except OSError as exc:
        print(f"own-fix: cannot write {path}: {exc}", file=sys.stderr)
        return 2
    return 0


def _cmd_candidates(rest: list[str]) -> int:
    parsed = _own_fix_parse(
        rest, {"--config", "--class", "--output", "--root"}, {"--finding-id"}
    )
    if parsed is None:
        return 2
    positional, opts = parsed
    if (len(positional) != 1 or not opts.get("--config")
            or not opts.get("--class") or not opts.get("--output")):
        print("usage: own-fix subscriptions candidates <facts.json> --config <own.toml> "
              "--class <FQN> [--finding-id <ID>]... --output <candidates.json> [--root <dir>]",
              file=sys.stderr)
        return 2

    from ownlang.config import ConfigError, load_target_subscribe
    from ownlang.fix_candidates import CollectError, collect_candidates

    try:
        target = load_target_subscribe(opts["--config"])
    except ConfigError as exc:
        print(f"own-fix: {exc}", file=sys.stderr)
        return 2
    try:
        facts = _read_json(positional[0])
    except (OSError, ValueError) as exc:
        print(f"own-fix: cannot read facts {positional[0]}: {exc}", file=sys.stderr)
        return 2
    try:
        envelope = collect_candidates(
            facts, target, opts["--class"], opts["--finding-id"] or None, opts.get("--root", ".")
        )
    except CollectError as exc:
        print(f"own-fix: {exc}", file=sys.stderr)
        return 2
    rc = _write_atomic(opts["--output"], envelope)
    if rc == 0:
        print(f"own-fix: wrote {len(envelope['candidates'])} candidate(s) -> {opts['--output']}")
    return rc


def _cmd_render(rest: list[str]) -> int:
    parsed = _own_fix_parse(rest, {"--prompt", "--schema"}, set())
    if parsed is None:
        return 2
    positional, opts = parsed
    if len(positional) != 1 or not opts.get("--prompt") or not opts.get("--schema"):
        print("usage: own-fix subscriptions render <candidates.json> --prompt <prompt.txt> "
              "--schema <fix-plan.schema.json>", file=sys.stderr)
        return 2

    from ownlang.fix_candidates import CollectError
    from ownlang.fix_plan import render

    try:
        bundle = _read_json(positional[0])
    except (OSError, ValueError) as exc:
        print(f"own-fix: cannot read candidates {positional[0]}: {exc}", file=sys.stderr)
        return 2
    try:
        prompt, schema = render(bundle)
    except CollectError as exc:
        print(f"own-fix: {exc}", file=sys.stderr)
        return 2
    try:
        with open(opts["--prompt"], "w", encoding="utf-8") as fh:
            fh.write(prompt)
    except OSError as exc:
        print(f"own-fix: cannot write {opts['--prompt']}: {exc}", file=sys.stderr)
        return 2
    rc = _write_atomic(opts["--schema"], schema)
    if rc == 0:
        count = len(bundle.get("candidates", []))
        print(f"own-fix: rendered prompt + schema for {count} candidate(s)")
    return rc


def _cmd_validate_plan(rest: list[str]) -> int:
    parsed = _own_fix_parse(rest, {"--output"}, set())
    if parsed is None:
        return 2
    positional, opts = parsed
    if len(positional) != 2 or not opts.get("--output"):
        print("usage: own-fix subscriptions validate-plan <candidates.json> <fix-plan.json> "
              "--output <validated-plan.json>", file=sys.stderr)
        return 2

    from ownlang.fix_plan import PlanError, validate_plan

    try:
        bundle = _read_json(positional[0])
    except (OSError, ValueError) as exc:
        print(f"own-fix: cannot read candidates {positional[0]}: {exc}", file=sys.stderr)
        return 2
    try:
        plan = _read_json(positional[1])
    except (OSError, ValueError) as exc:
        print(f"own-fix: cannot read fix-plan {positional[1]}: {exc}", file=sys.stderr)
        return 2
    try:
        validated = validate_plan(bundle, plan)
    except PlanError as exc:
        print(f"own-fix: {exc}", file=sys.stderr)
        return 2
    rc = _write_atomic(opts["--output"], validated)
    if rc == 0:
        print(f"own-fix: validated {len(validated['decisions'])} decision(s) -> {opts['--output']}")
    return rc


def _cmd_apply(rest: list[str]) -> int:
    """S2 step 8: `own-fix subscriptions apply` — the canonical patch bundle. Thin
    orchestration only: re-run the apply gate, invoke the accepted Owen.CSharp.Rewriter
    (as an argv vector, never a shell string), verify its transport output, and publish
    change.patch + apply-manifest.json + postimage/ as ONE atomic bundle. No model, no o7."""
    from ownlang.fix_apply import ApplyError
    from ownlang.fix_bundle import apply_bundle, split_rewriter_command

    flags = {"--plan", "--candidates", "--root", "--out", "--rewriter"}
    parsed = _own_fix_parse(rest, flags, set())
    if parsed is None:
        return 2
    positional, opts = parsed
    if positional or not all(opts.get(k) for k in ("--plan", "--candidates", "--out")):
        print("usage: own-fix subscriptions apply --plan <validated-plan.json> "
              "--candidates <candidates.json> --root <source-root> --out <artifact-dir> "
              "[--rewriter <owen-rewrite-command>]", file=sys.stderr)
        return 2
    try:
        rewriter = split_rewriter_command(opts.get("--rewriter") or "owen-rewrite")
    except ValueError as exc:
        print(f"own-fix: refuse: --rewriter is not a parseable command ({exc}); it is "
              "split with POSIX shell rules, so quote a path containing spaces or "
              "backslashes", file=sys.stderr)
        return 2
    if not rewriter:
        print("own-fix: refuse: --rewriter is empty", file=sys.stderr)
        return 2
    try:
        published = apply_bundle(opts["--plan"], opts["--candidates"],
                                 opts.get("--root") or ".", opts["--out"], rewriter)
    except ApplyError as exc:
        print(f"own-fix: refuse: {exc}", file=sys.stderr)
        return 2
    print(f"own-fix: wrote change.patch + apply-manifest.json + postimage -> {published}")
    return 0


def _cmd_gate(rest: list[str]) -> int:
    """S2 step 9: `own-fix subscriptions gate` — the structural self-gate. Re-validates a
    canonical step 8 bundle against its plan + candidates and proves the patch's semantics
    with an INDEPENDENT host Git in a hermetic throwaway repo, then publishes a
    byte-deterministic gate-result.json. No model, no o7, no analyzer, no target tests; the
    real checkout / index / config are never touched. There is deliberately no `--git`
    override — evidence of an INDEPENDENT apply cannot come from a caller-supplied stand-in."""
    from ownlang.fix_gate import GateError, run_gate

    flags = {"--bundle", "--plan", "--candidates", "--root", "--out"}
    parsed = _own_fix_parse(rest, flags, set())
    if parsed is None:
        return 2
    positional, opts = parsed
    if positional or not all(opts.get(k) for k in
                             ("--bundle", "--plan", "--candidates", "--out")):
        print("usage: own-fix subscriptions gate --bundle <step8-bundle> "
              "--plan <validated-plan.json> --candidates <candidates.json> "
              "--root <pristine-source-root> --out <gate-evidence-dir>", file=sys.stderr)
        return 2
    try:
        published = run_gate(opts["--bundle"], opts["--plan"], opts["--candidates"],
                             opts.get("--root") or ".", opts["--out"])
    except GateError as exc:
        print(f"own-fix: refuse: {exc.category}: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # fail closed: any surprise is a refusal, not a traceback
        print(f"own-fix: refuse: INFRASTRUCTURE: internal error "
              f"({type(exc).__name__}: {exc})", file=sys.stderr)
        return 2
    print(f"own-fix: wrote gate-result.json -> {published}")
    return 0


def _cmd_verify_delta(rest: list[str]) -> int:
    """S2 step 10: `own-fix subscriptions verify-delta` — the analyzer-semantic gate over an
    accepted step 8 bundle. Re-runs Own.NET's real core analyzer (from a snapshotted ownlang
    package in a fresh, isolated subprocess) over the pristine preimage and the accepted
    postimage and proves the OWN001 delta matches the plan (converted gone, manual preserved,
    no new OWN001 of any lane, no new OWN050). --gate is mandatory; there is no --config."""
    from ownlang.fix_delta import DeltaError, run_verify_delta
    from ownlang.fix_gate import GateError  # the reused snapshot/publish helpers raise this

    flags = {"--bundle", "--plan", "--candidates", "--root", "--gate", "--extractor-dll", "--out"}
    parsed = _own_fix_parse(rest, flags, {"--ref-dir"})
    if parsed is None:
        return 2
    positional, opts = parsed
    # a repeated singleton flag is an input error, not a silent last-wins (LA F11)
    for f in flags:
        if rest.count(f) > 1:
            print(f"own-fix: {f} given more than once", file=sys.stderr)
            return 2
    if positional or not all(opts.get(k) for k in flags):
        print("usage: own-fix subscriptions verify-delta --bundle <step8-bundle> "
              "--plan <validated-plan.json> --candidates <candidates.json> "
              "--root <pristine-source-root> --gate <step9-gate-result.json> "
              "--extractor-dll <OwnSharp.Extractor.dll> --out <delta-evidence-dir> "
              "[--ref-dir <dir>]...", file=sys.stderr)
        return 2
    try:
        published = run_verify_delta(
            opts["--bundle"], opts["--plan"], opts["--candidates"], opts["--root"],
            opts["--gate"], opts["--extractor-dll"], opts["--out"], opts.get("--ref-dir") or [])
    except (DeltaError, GateError) as exc:  # both carry a stable .category
        print(f"own-fix: refuse: {exc.category}: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # fail closed: any surprise is a refusal, not a traceback
        print(f"own-fix: refuse: INFRASTRUCTURE: internal error "
              f"({type(exc).__name__}: {exc})", file=sys.stderr)
        return 2
    print(f"own-fix: wrote delta-result.json -> {published}")
    return 0


def cmd_own_fix(rest: list[str]) -> int:
    """`own-fix subscriptions {candidates|render|validate-plan|apply|gate|verify-delta} ...`."""
    if len(rest) < 2 or rest[0] != "subscriptions":
        print("usage: python -m ownlang own-fix subscriptions "
              "{candidates|render|validate-plan|apply|gate|verify-delta} ...", file=sys.stderr)
        return 2
    verb, args = rest[1], rest[2:]
    if verb == "candidates":
        return _cmd_candidates(args)
    if verb == "render":
        return _cmd_render(args)
    if verb == "validate-plan":
        return _cmd_validate_plan(args)
    if verb == "apply":
        return _cmd_apply(args)
    if verb == "gate":
        return _cmd_gate(args)
    if verb == "verify-delta":
        return _cmd_verify_delta(args)
    print(f"own-fix: unknown subcommand {verb!r} "
          "(candidates | render | validate-plan | apply | gate | verify-delta)", file=sys.stderr)
    return 2


_FORMATS = {"human", "github", "msbuild", "sarif", "json"}
_SEVERITIES = {"error", "warning"}
_VERBOSITY = {"quiet", "normal", "verbose"}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"check", "emit", "cfg", "report", "ownir",
                                   "summaries", "explain", "config", "own-fix"}:
        print(__doc__)
        return 2
    cmd = argv[0]
    # `own-fix subscriptions candidates` (S0 Part B): analysis-only candidate export
    # for the subscription-autofix pipeline. Has its own nested shape, so it is handled
    # before the single-positional path below.
    if cmd == "own-fix":
        return cmd_own_fix(argv[1:])
    # `config` is the minimal P-015 carrier (P-035): read an explicit own.toml and
    # print the declared weak-subscribe "SimpleType.Method" names, one per line, for
    # own-check.sh to forward to the extractor. A malformed config is a HARD error
    # (exit 2), never a silent empty list.
    if cmd == "config":
        rest = argv[1:]
        if len(rest) != 1:
            print("usage: python -m ownlang config <own.toml>", file=sys.stderr)
            return 2
        from ownlang.config import ConfigError, load_weak_subscribe
        try:
            for name in load_weak_subscribe(rest[0]):
                print(name)
        except ConfigError as exc:
            print(f"own-check: {exc}", file=sys.stderr)
            return 2
        return 0
    # `explain` has its own shape — zero-or-more code positionals plus an optional
    # `--json <file>` — so it is handled before the single-positional path below.
    if cmd == "explain":
        codes: list[str] = []
        json_path: str | None = None
        rest = argv[1:]
        i = 0
        while i < len(rest):
            a = rest[i]
            if a == "--json":
                if i + 1 >= len(rest):
                    print("--json requires a value", file=sys.stderr)
                    return 2
                json_path, i = rest[i + 1], i + 2
                continue
            if a.startswith("--json="):
                json_path, i = a.split("=", 1)[1], i + 1
                continue
            codes.append(a)
            i += 1
        return cmd_explain(codes, json_path)
    # Pull the optional value-flags (`--format`/`--severity`/`--verbosity`, ownir
    # only) out of the arguments in either `--flag V` or `--flag=V` form; everything
    # else is positional. Keeps the other commands' single positional-path contract.
    opts = {"--format": "human", "--severity": "error", "--verbosity": "normal"}
    seen: set[str] = set()
    positional: list[str] = []
    rest = argv[1:]
    i = 0
    while i < len(rest):
        a = rest[i]
        matched = False
        for flag in opts:
            if a == flag:
                if i + 1 >= len(rest):
                    print(f"{flag} requires a value", file=sys.stderr)
                    return 2
                opts[flag], i = rest[i + 1], i + 2
                seen.add(flag)
                matched = True
                break
            if a.startswith(flag + "="):
                opts[flag], i = a.split("=", 1)[1], i + 1
                seen.add(flag)
                matched = True
                break
        if matched:
            continue
        positional.append(a)
        i += 1
    # exactly one positional (the path/file); zero or extra args is a usage error
    # (a silently-ignored extra arg hides a caller mistake).
    if len(positional) != 1:
        print(__doc__)
        return 2
    fmt, severity, verbosity = (opts["--format"], opts["--severity"],
                                opts["--verbosity"])
    if fmt not in _FORMATS:
        print(f"unknown --format {fmt!r} (choose: {', '.join(sorted(_FORMATS))})",
              file=sys.stderr)
        return 2
    if severity not in _SEVERITIES:
        print(f"unknown --severity {severity!r} (choose: "
              f"{', '.join(sorted(_SEVERITIES))})", file=sys.stderr)
        return 2
    if verbosity not in _VERBOSITY:
        print(f"unknown --verbosity {verbosity!r} (choose: "
              f"{', '.join(sorted(_VERBOSITY))})", file=sys.stderr)
        return 2
    # Value-flag scope, rejected by *presence* (so a redundant `--format human` is a
    # clear error, not a silent no-op): `ownir` takes all three; `check` takes only
    # `--format`, and only human|sarif (github/msbuild are per-finding renderers that
    # need an OwnIR Finding, not a Diagnostic); `cfg` takes only `--format`, and only
    # human|json (the canonical CFG-layer oracle seam); every other command takes none.
    if cmd in {"check", "cfg"}:
        extra = seen - {"--format"}
        if extra:
            print(f"{'/'.join(sorted(extra))} only apply to `ownir`", file=sys.stderr)
            return 2
        allowed = {"human", "sarif"} if cmd == "check" else {"human", "json"}
        if fmt not in allowed:
            print(f"{cmd} --format must be one of {'/'.join(sorted(allowed))} "
                  f"(got {fmt!r})", file=sys.stderr)
            return 2
    elif cmd != "ownir" and seen:
        print("--format/--severity/--verbosity only apply to `ownir`",
              file=sys.stderr)
        return 2
    path = positional[0]
    if cmd == "ownir":
        if fmt == "json":  # json is the cfg seam's format, not an ownir surface
            print("ownir --format must be one of github/human/msbuild/sarif "
                  "(got 'json')", file=sys.stderr)
            return 2
        return cmd_ownir(path, fmt, severity, verbosity)
    if cmd == "check":
        return cmd_check(path, fmt, severity)
    if cmd == "cfg":
        return cmd_cfg(path, fmt)
    return {"emit": cmd_emit, "report": cmd_report,
            "summaries": cmd_summaries}[cmd](path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
