#!/usr/bin/env python3
"""
Diagnostic rendering tests (the `diagnostics` module, P-015 evidence slice).

Pins two contracts that a downstream tool and the CLI both depend on:

  1. The *empty-evidence invariant*: a diagnostic with no evidence (the common
     case) renders byte-for-byte as it did before the evidence field existed, in
     both the plain `render()` and the rustc-style `render_pretty()`. This is the
     backward-compatibility promise the P-015 change is built on.
  2. The *evidence slice*: a populated diagnostic appends exactly one `note:`
     line per evidence step, in order, after the caret block; a step whose file
     is None (the "same file as the anchor" convention) renders the diagnostic's
     own filename.

A short smoke test also pins the `ownlang.evidence` SARIF builders that the same
slice feeds (lineless / empty-file steps are dropped so the SARIF log can never
carry an empty artifactLocation.uri; a DI path is labelled captor-first).

Run:  python tests/test_diagnostics.py
      python tests/run_tests.py     (once folded into the suite aggregator)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang import evidence
from ownlang.diagnostics import Diagnostic, Evidence

# a source whose line 3 names `b`, so render_pretty can place a caret under it.
_SOURCE = "module M\nfn f() {\n    use b;\n}\n"


def _empty_evidence_invariant() -> list[str]:
    """render()/render_pretty() must be unchanged when evidence == ()."""
    fails: list[str] = []
    d = Diagnostic(code="OWN002", message="use 'b' after it was released", line=3)
    if d.evidence != ():   # the default; the invariant is about this case
        fails.append("a freshly constructed Diagnostic must default to no evidence")

    plain = d.render("m.own")
    if plain != "m.own:3: error: [OWN002] use 'b' after it was released":
        fails.append(f"plain render changed for empty evidence: {plain!r}")
    if "\n" in plain:
        fails.append("plain render of an evidence-free diagnostic must be one line")

    pretty = d.render_pretty("m.own", _SOURCE)
    if "note:" in pretty:
        fails.append("render_pretty must emit no note: line when evidence is empty")
    # header + source line + caret, and nothing past the caret.
    if not pretty.splitlines()[-1].strip().startswith("^"):
        fails.append(f"render_pretty should end at the caret for empty evidence: {pretty!r}")
    return fails


def _evidence_slice() -> list[str]:
    """A populated slice appends ordered note: lines; file=None uses the anchor file."""
    fails: list[str] = []
    d = Diagnostic(
        code="OWN001",
        message="owned 'h' not released on all paths",
        line=3,
        evidence=(
            Evidence(line=2, label="acquired here", role="acquired"),          # same file
            Evidence(line=9, label="missing release", file="other.own", role="released"),
        ),
    )

    notes = [ln for ln in d.render("m.own").splitlines() if ln.lstrip().startswith("note:")]
    expected = [
        "  note: acquired here at m.own:2",       # file=None -> the anchor's filename
        "  note: missing release at other.own:9",
    ]
    if notes != expected:
        fails.append(f"evidence note lines wrong/out of order: {notes!r}")

    # the order must be stable: acquired before missing-release.
    body = d.render("m.own")
    if body.index("acquired here") > body.index("missing release"):
        fails.append("evidence slice rendered out of order in render()")

    pretty = d.render_pretty("m.own", _SOURCE)
    pnotes = [ln for ln in pretty.splitlines() if ln.lstrip().startswith("note:")]
    if pnotes != expected:
        fails.append(f"render_pretty evidence lines wrong/out of order: {pnotes!r}")
    # the notes come AFTER the caret, not before it.
    lines = pretty.splitlines()
    caret_idx = next(i for i, ln in enumerate(lines) if ln.strip().startswith("^"))
    first_note_idx = next(i for i, ln in enumerate(lines) if ln.lstrip().startswith("note:"))
    if first_note_idx <= caret_idx:
        fails.append("render_pretty must place note: lines after the caret block")
    return fails


def _evidence_builders() -> list[str]:
    """ownlang.evidence: drop unusable steps; label a DI path captor-first."""
    fails: list[str] = []

    steps = [
        ("a.cs", 10, "acquired"),
        ("", 11, "no file -> dropped"),       # empty file must not yield an empty uri
        ("b.cs", 0, "no line -> dropped"),    # lineless step is noise
    ]
    rel = evidence.related_locations(steps)
    if len(rel) != 1 or rel[0]["physicalLocation"]["artifactLocation"]["uri"] != "a.cs":
        fails.append(f"related_locations should keep only the usable step: {rel!r}")
    if any(loc["physicalLocation"]["artifactLocation"]["uri"] == "" for loc in rel):
        fails.append("related_locations must never emit an empty artifactLocation.uri")

    flow = evidence.code_flow(steps)
    locs = flow[0]["threadFlows"][0]["locations"] if flow else []
    if len(locs) != 1:
        fails.append(f"code_flow should keep only the usable step: {flow!r}")
    if evidence.code_flow([]) != []:
        fails.append("code_flow of no steps must be [] so the caller can splice conditionally")

    loc_by_name = {"App": ("app.cs", 1), "Mid": ("mid.cs", 2), "Scoped": ("db.cs", 3)}
    di = evidence.di_path_steps(("App", "Mid", "Scoped"), loc_by_name, "captures scoped service")
    if di[0] != ("app.cs", 1, "singleton 'App' (captor)"):
        fails.append(f"di_path_steps must label the captor first: {di!r}")
    if di[-1] != ("db.cs", 3, "captures scoped service 'Scoped'"):
        fails.append(f"di_path_steps must label the captured last: {di!r}")
    if di[1] != ("mid.cs", 2, "via 'Mid'"):
        fails.append(f"di_path_steps must label middle hops as pass-through: {di!r}")
    # an unknown hop is skipped, keeping the slice ordered and truthful.
    di2 = evidence.di_path_steps(("App", "Gone", "Scoped"), loc_by_name, "captures scoped service")
    if [s[0] for s in di2] != ["app.cs", "db.cs"]:
        fails.append(f"di_path_steps must skip a hop with an unknown location: {di2!r}")
    return fails


def run() -> int:
    """Run every diagnostics-rendering case; return 0/1."""
    fails: list[str] = []
    fails += _empty_evidence_invariant()
    fails += _evidence_slice()
    fails += _evidence_builders()
    for f in fails:
        print(f"DIAGNOSTICS FAIL: {f}")
    print(f"diagnostics: {'PASS' if not fails else 'FAIL'} "
          f"(evidence invariant + slice ordering + SARIF builders)")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
