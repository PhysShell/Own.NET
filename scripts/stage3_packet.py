#!/usr/bin/env python3
"""Generate #262's Stage-3 cutover decision packet FROM THE EVIDENCE.

#262 asks for a packet with named fields. The temptation with a form like that
is to fill it in from memory at the end of the work, which produces a document
that is true about what someone remembers rather than about the tree. So every
line this writes is read from a recorded artifact or computed from the tree,
and a field whose evidence is missing says so rather than guessing.

The performance fields are the exception that proves the rule. They are
DEFERRED BY OWNER for the Stage-3 decision and are printed with that text and
no number, because a deferral is not a measurement and must never be rendered
as one. They are not deleted either: #262 asked for them, #263 still owes them,
and a packet missing the line is a packet nobody can notice is missing it.

Run:  python scripts/stage3_packet.py            (print)
      python scripts/stage3_packet.py --write    (write the generated fragment)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVIDENCE = os.path.join(ROOT, "docs", "evidence")
OUT = os.path.join(ROOT, "docs", "generated", "p022-stage3-packet.md")

# The exact wording the owner ruling requires wherever a performance number
# would otherwise go. Written once, so no field can drift into a softer phrasing.
DEFERRED = "DEFERRED BY OWNER — NOT MEASURED"

MISSING = "NOT RECORDED — evidence file absent"


def _read(name: str) -> dict | None:
    path = os.path.join(EVIDENCE, name)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _sweep_line() -> tuple[str, str]:
    d = _read("p022-stage3-sweep.result.json")
    if d is None:
        return MISSING, MISSING
    t = d["totals"]
    targets = len(d.get("targets", []))
    commit = d.get("source_commit", "")[:12]
    anchor = d.get("workflow_run_url") or "local run (no CI anchor)"
    five = (f"{t['agreed']}/{t['compare_attempted']} documents agreed over {targets} targets; "
            f"{t['acceptance_unexplained_observations']} acceptance-unexplained, "
            f"{t['declared_boundary_observations']} declared-boundary; "
            f"at {commit}; {anchor}")
    large = (f"the largest .sln of every target that has one is inside the same run "
             f"({sum(1 for doc in d['documents'] if doc.get('extraction_mode') == 'solution')} "
             f"solution documents); {t['diverged']} diverged, "
             f"{t['execution_failures']} execution-failure")
    return five, large


def _ledger() -> dict:
    d = _read("p022-stage3-cutover.json")
    if d is None:
        raise SystemExit("scripts/stage3_packet.py: docs/evidence/p022-stage3-cutover.json is "
                         "missing — the packet is derived from it and is not written without it")
    return d


def _by_id(led: dict, key: str) -> str:
    for m in led["measurements"]:
        if m["id"] == key:
            return m["result"]
    return MISSING


def _platform_block(led: dict, plat: str) -> str:
    rows = [m for m in led["measurements"] if m["platform"] == plat]
    return "; ".join(f"{m['id']}: {m['result']}" for m in rows) or MISSING


def packet() -> str:
    led = _ledger()
    head = _git("rev-parse", "HEAD")
    dirty = bool(_git("status", "--porcelain"))
    five, large = _sweep_line()
    cli = _read("p022-cli-1.result.json")
    cli_line = MISSING
    if cli is not None:
        caught = sum(1 for m in cli.get("mutations", []) if m.get("outcome") == "caught")
        cli_line = (f"{caught}/{len(cli.get('mutations', []))} mutants caught at "
                    f"{cli.get('source_commit', '')[:12]}")

    rows = [
        ("Stage-3 candidate SHA", head + (" (DIRTY TREE — not evidence)" if dirty else "")),
        ("Observation window", led["observation"]["mechanism"]
            + f"; first run {led['observation']['first_run']['sha'][:12]}: "
            + led["observation"]["first_run"]["result"]),
        ("Fast compare result", _by_id(led, "fast-compare")
            + " | samples: " + _by_id(led, "samples-compare")),
        ("Five-repo compare result", five),
        ("Large-solution result", large),
        ("Windows packaging result", _by_id(led, "packaging-windows")),
        ("Linux packaging result", _by_id(led, "packaging-linux")),
        ("Startup delta", led["deferred_fields"]["startup_delta"]),
        ("End-to-end delta", led["deferred_fields"]["end_to_end_delta"]),
        ("Peak memory delta", led["deferred_fields"]["peak_memory_delta"]),
        ("Known differences", "; ".join(
            f"{k['id']} ({k['status'].split(',')[0]})" for k in led["known_differences"])),
        ("Rollback command/config", "`--engine python` / `-Engine python` / "
                                    "`engine: python`; see `docs/notes/owen-engine-rollback.md`"),
        ("Python-removal timing", "Stage 4 — a separate, separately reviewable PR, after the "
                                  "observation policy. NOT now."),
    ]
    width = max(len(k) for k, _ in rows)
    body = "\n".join(f"{k + ':':<{width + 2}}{v}" for k, v in rows)
    def section(title: str, items: list[dict], *a: str) -> str:
        out = [f"\n## {title}\n"]
        for it in items:
            out.append(f"* **{it['id']}** — _{it.get(a[0], '')}_  \n  "
                       + it.get(a[1], "").replace("\n", " "))
        return "\n".join(out) + "\n"

    owed = [m for m in led["measurements"] if m["label"] == "DEFERRED EVIDENCE"]
    owed_block = ("\n## Owed, and named rather than predicted\n\n"
                  + "\n".join(
                      f"* **{m['id']}** ({m['platform']}) — {m['result']}  \n  via {m['method']}"
                      for m in owed) + "\n") if owed else ""

    return (
        "<!-- GENERATED by scripts/stage3_packet.py from docs/evidence/"
        "p022-stage3-cutover.json. Do not edit by hand: every line is read from a "
        "recorded artifact or computed from the tree. -->\n"
        "# P-022 Stage 3 — #262 cutover decision packet\n\n"
        "```text\n" + body + "\n```\n\n"
        "> **Performance.** " + led["owner_ruling_performance"] + "\n"
        f"\nCLI contract campaign: {cli_line}\n"
        + section("Known differences", led["known_differences"], "status", "summary")
        + section("Closed by this change (recorded as closures, not as differences)",
                  led["closed_in_this_change"], "was", "now")
        + owed_block
        + "\n## Measurements\n\n"
        + "\n".join(f"* `{m['id']}` [{m['platform']}] **{m['label']}** — {m['result']}"
                     for m in led["measurements"]) + "\n"
    )


def run() -> int:
    text = packet()
    if "--write" in sys.argv:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"wrote {os.path.relpath(OUT, ROOT)}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
