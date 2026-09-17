#!/usr/bin/env python3
"""
P-036 comparative bakeoff harness — Owen vs Infer# / RLC# / CodeQL / CA2000.

Runs every comparator over the same per-case inputs (one project per
`before.cs` / `after.cs` file, plus the stub file and NuGet references the
manifest declares) and records, per (case, side, tool, config):

  * the raw findings (rule, line, message, level) — preserved verbatim under
    `<out>/raw/<tool>/<case>.<side>.<config>.json`;
  * an explicit status from the preregistered vocabulary
    (docs/notes/p036-bakeoff.md §0):

        DETECTED_STOCK / DETECTED_CONFIGURED / DETECTED_CUSTOM_MODEL /
        DETECTED_CUSTOM_QUERY          a leak-family finding on `before`
        MISSED                         no leak-family finding on `before`
        CLEAN / FALSE_POSITIVE_<cfg>   `after` side
        UNSUPPORTED                    the tool cannot take this input
                                       (build failed, unresolved input)
        CRASHED                        the tool itself failed
        NOT_APPLICABLE                 the tool has no rule for the defect
                                       class (declared in the manifest)

  * an EXPLORATORY wall-clock per step, labelled non-admissible for #263.

It is deliberately dumb: no re-scoring, no line matching cleverness. The
human-reviewed reading of every detection lives in the research note.

Tool locations (environment):
  OWEN_ROOT          this repository (default: the script's parent)
  DOTNET_ROOT        .NET 8 SDK root (dotnet on PATH is also fine)
  OWN_EXTRA_REF_DIRS WindowsDesktop reference pack dir (as oracle.yml)
  CODEQL_HOME        CodeQL 2.27.0 bundle dir (contains `codeql`)
  CODEQL2022_HOME    CodeQL bundle 20221211 dir — RLC# runs UNMODIFIED here
  RLC_HOME           clone of microsoft/global-resource-leaks-codeql
  INFERSHARP_HOME    extracted infersharp-linux64-v1.5 (`infersharp/` dir)

Usage:
  python scripts/p036_bakeoff.py --write-manifest docs/evidence/p036-bakeoff/corpus.json
  python scripts/p036_bakeoff.py --manifest docs/evidence/p036-bakeoff/corpus.json \
        --work /tmp/bakeoff --out docs/evidence/p036-bakeoff \
        [--tools owen,codeql,rlc,infersharp,netanalyzers,idisp] [--cases F1-01,F3-S1] [--jobs 3]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("OWEN_ROOT", Path(__file__).resolve().parent.parent))

TIMING_LABEL = (
    "EXPLORATORY ONLY / NON-ADMISSIBLE FOR #263 / NON-PUBLICATION-GRADE / UNCONTROLLED SHARED HOST"
)

# ---------------------------------------------------------------------------
# The corpus manifest (preregistered; see docs/notes/p036-bakeoff.md §0/§1).
# provenance: 1 historical real bug, 2 existing regression fixture,
#             3 adversarial mutation of a real shape, 4 synthetic conformance,
#             5 exploratory (post-hoc)
# na: tools that have NO rule for the case's defect class, by their
#     documented rule scope — those get NOT_APPLICABLE instead of MISSED.
# ---------------------------------------------------------------------------

RAII_TOOLS = ("codeql", "rlc", "infersharp", "netanalyzers", "idisp")
NA_SUBSCRIPTION = dict.fromkeys(RAII_TOOLS, "no event-subscription/lifetime rule")
NA_TIMER = dict.fromkeys(
    RAII_TOOLS, "no timer-stop/lifecycle rule; the timer type is not IDisposable"
)
NA_DI = dict.fromkeys(RAII_TOOLS, "no DI-lifetime rule")
NA_OBL = dict.fromkeys(RAII_TOOLS, "no project-protocol/obligation rule")
NA_PRG = dict.fromkeys(RAII_TOOLS, "no loop-progress rule")


def _c(
    cid: str,
    family: str,
    prov: int,
    source: str,
    expected: list[str],
    why: str,
    subject: str,
    na: dict[str, str] | None = None,
    stubs: list[str] | None = None,
    project: str | None = None,
    rlc_annotations: list[dict[str, str]] | None = None,
    prov_note: str = "",
    sides: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": cid,
        "family": family,
        "provenance": prov,
        "provenance_note": prov_note,
        "source": source,
        "expected": expected,
        "subject": subject,
        "why_p036": why,
        "na": na or {},
        "stubs": stubs or [],
        "project": project,
        "rlc_annotations": rlc_annotations or [],
        "sides": sides or ["before", "after"],
    }


CASES: list[dict[str, Any]] = [
    # ---- F1: subscription release reachability (#278 class) --------------------
    _c(
        "F1-01",
        "F1",
        1,
        "corpus/wpf/subscription-param-guarded-unregister",
        ["OWN001"],
        "the #278 motivating incident: -= behind a bool parameter in a non-teardown method",
        "ctor += to injected INotifyPropertyChanged; "
        "-= under if(!flag) in UnregisterEventHandlers(bool)",
        NA_SUBSCRIPTION,
        prov_note="SectorTS GTD (heap-proven, #278), hand-reduced",
    ),
    _c(
        "F1-02",
        "F1",
        3,
        "corpus/wpf/subscription-teardown-early-return-guard",
        ["OWN001"],
        "P-037 row 2 spelling of the guard, on a subscription; #305 attack A",
        "Dispose() -> Cleanup(keepAlive: true); -= after `if (keepAlive) return;`",
        NA_SUBSCRIPTION,
    ),
    _c(
        "F1-03",
        "F1",
        3,
        "corpus/wpf/subscription-disposing-else-branch-release",
        ["OWN001"],
        "branch membership of the canonical Dispose(bool) guard; #305 attack B",
        "-= in the else of if(disposing)",
        NA_SUBSCRIPTION,
    ),
    _c(
        "F1-04",
        "F1",
        1,
        "corpus/wpf/subscription-nonteardown-release",
        ["OWN001"],
        "release exists but no lifecycle root reaches it (P-036 lifecycle roots)",
        "-= only in StopListening(), which nothing here calls",
        NA_SUBSCRIPTION,
        prov_note="SectorTS DocCloud shape (#278 rule 3), hand-reduced",
    ),
    _c(
        "F1-05",
        "F1",
        3,
        "corpus/wpf/subscription-uncalled-local-function",
        ["OWN001"],
        "declaration is not execution: uncalled local function / lambda inside Dispose",
        "-= inside a nested callable Dispose never invokes",
        NA_SUBSCRIPTION,
    ),
    _c(
        "F1-06",
        "F1",
        3,
        "corpus/wpf/subscription-overload-conflated-cleanup",
        ["OWN001"],
        "call resolution by symbol, not name: Cleanup() vs uncalled Cleanup(bool)",
        "-= in the uncalled overload of a teardown helper",
        NA_SUBSCRIPTION,
    ),
    _c(
        "F1-07",
        "F1",
        3,
        "corpus/wpf/subscription-finalizer-release",
        ["OWN001"],
        "a finalizer is not a lifecycle root while the publisher pins the subscriber",
        "-= only in ~Finalizer",
        NA_SUBSCRIPTION,
    ),
    _c(
        "F1-08",
        "F1",
        3,
        "corpus/wpf/subscription-xaml-name-only-release",
        ["OWN001"],
        "enrollment: a Window_Closing-named handler with no wiring is not a root",
        "-= in a name-only handler nobody wires",
        NA_SUBSCRIPTION,
    ),
    _c(
        "F1-09",
        "F1",
        3,
        "corpus/wpf/subscription-ambiguous-overload-wiring",
        ["OWN001"],
        "unresolved lifecycle event + ambiguous method group: no delegate target proven",
        "-= in the never-attached overload of a wired handler",
        NA_SUBSCRIPTION,
    ),
    _c(
        "F1-10",
        "F1",
        2,
        "corpus/wpf/subscription-explicit-delegate-release",
        ["OWN001"],
        "specificity control: release-match through `new Handler(H)` vs bare `H`",
        "ctor += new PropertyChangedEventHandler(H), Dispose -= H",
        NA_SUBSCRIPTION,
    ),
    _c(
        "F1-11",
        "F1",
        1,
        "corpus/real-world/screentogif-systemevents-leak",
        ["OWN001"],
        "real OSS static-source subscription leak; lifetime tiering (static source => error)",
        "SystemEvents.DisplaySettingsChanged += in a Window ctor, never -=",
        NA_SUBSCRIPTION,
        prov_note="ScreenToGif @27a49c3 GraphicsConfigurationDialog.xaml.cs:35",
    ),
    _c(
        "F1-12",
        "F1",
        1,
        "corpus/real-world/screentogif-loaded-subscription",
        ["OWN001"],
        "real OSS view<->view-model subscription with inline lambdas (no -= handle)",
        "_viewModel.X += lambda in Window_Loaded, never detached",
        NA_SUBSCRIPTION,
        prov_note="ScreenToGif @27a49c3 VideoSource.xaml.cs:50-83, reduced",
    ),
    _c(
        "F1-13",
        "F1",
        2,
        "corpus/wpf/zombie-viewmodel",
        ["OWN001"],
        "token-returning Subscribe: the IDisposable token is discarded — RAII tools MAY see it",
        "bus.Subscribe<T>(handler) result ignored; no Dispose",
        {
            "codeql": "cs/local-not-disposed needs a local; "
            "a discarded call result is out of scope",
            "infersharp": "scope-uncertain: Pulse tracks allocated resources; "
            "IEventBus.Subscribe is an interface stub",
            "rlc": "scope-uncertain: IDisposable return of an interface call",
        },
        stubs=["eventbus"],
    ),
    _c(
        "F1-14",
        "F1",
        2,
        "corpus/fixtures/systemevents-console",
        ["OWN001", "OWN014"],
        "the July three-tool oracle fixture: one subscription leak "
        "+ three RAII controls in one program",
        "DisplayWatcher ctor += SystemEvents (leak #1); FileStream locals (#2 #3 #4 controls)",
        project="SystemEventsLeak.csproj",
        sides=["before"],
    ),
    # ---- F2: timer Stop() lifecycle (WPF002) ----------------------------------
    _c(
        "F2-01",
        "F2",
        3,
        "corpus/wpf/timer-stop-param-guarded",
        ["OWN001"],
        "WPF002 twin of F1-01: Stop() behind a caller parameter",
        "Tick += in ctor; Stop() under if(!flag)",
        NA_TIMER,
    ),
    _c(
        "F2-02",
        "F2",
        3,
        "corpus/wpf/timer-stop-early-return-guard",
        ["OWN001"],
        "WPF002 twin of F1-02",
        "Stop() after a parameter-guarded early return",
        NA_TIMER,
    ),
    _c(
        "F2-03",
        "F2",
        3,
        "corpus/wpf/timer-stop-uncalled-helper",
        ["OWN001"],
        "helper reachability from a lifecycle root",
        "Stop() in ReleaseTimer() called only from Reset()",
        NA_TIMER,
    ),
    _c(
        "F2-04",
        "F2",
        3,
        "corpus/wpf/timer-stop-nonteardown-release",
        ["OWN001"],
        "no lifecycle root reaches the Stop()",
        "Stop() in an arbitrary method",
        NA_TIMER,
    ),
    _c(
        "F2-05",
        "F2",
        3,
        "corpus/wpf/timer-stop-wrong-receiver",
        ["OWN001"],
        "receiver identity: Stop() on another timer credits nothing",
        "Stop() on a different field",
        NA_TIMER,
    ),
    _c(
        "F2-06",
        "F2",
        3,
        "corpus/wpf/timer-stop-unwired-lifecycle",
        ["OWN001"],
        "enrollment: a lifecycle-looking handler with no wiring",
        "Stop() in unwired Window_Closing",
        NA_TIMER,
    ),
    # ---- F3: interprocedural IDisposable ownership transfer --------------------
    _c(
        "F3-01",
        "F3",
        1,
        "corpus/real-world/ownership-handoff-consume",
        ["OWN001", "OWN002"],
        "consume contract through a helper: leak arm + use-after-handoff arm + clean handoff",
        "Archive(Stream) disposes; Leak() never hands off; Run() uses after handoff; RunOk() clean",
        prov_note="representative real-world pattern (stream sink), corpus note",
    ),
    _c(
        "F3-02",
        "F3",
        2,
        "corpus/real-world/ownership-handoff-use",
        ["OWN002"],
        "pure use-after-handoff (no leak arm)",
        "Consume(s) disposes; s.Length after",
    ),
    _c(
        "F3-03",
        "F3",
        2,
        "corpus/real-world/ownership-handoff-use-transitive",
        ["OWN002"],
        "consume through a forwarding chain (summary composition)",
        "Consume -> Inner -> Dispose; use after",
    ),
    _c(
        "F3-04",
        "F3",
        1,
        "corpus/real-world/field-dispose-via-helper",
        ["OWN001"],
        "release of an owned field through a first-party sink (NLog WaitForDispose)",
        "Timer field; after.cs releases via extension method that disposes its receiver",
        prov_note="NLog Common/AsyncHelpers.cs WaitForDispose shape",
    ),
    _c(
        "F3-05",
        "F3",
        1,
        "corpus/real-world/field-dispose-via-exchange",
        ["OWN001"],
        "Interlocked.Exchange detach-and-dispose idiom (heap identity through a call)",
        "Timer field; Interlocked.Exchange(ref _t, null)?.Dispose()",
        prov_note="NLog TimeoutContinuation shape",
    ),
    _c(
        "F3-06",
        "F3",
        1,
        "corpus/real-world/sharex-rfc2898-derivebytes-leak",
        ["OWN001"],
        "intraprocedural control: real OSS crypto IDisposable never disposed",
        "Rfc2898DeriveBytes + RandomNumberGenerator.Create() never disposed",
        prov_note="ShareX @ed2a864 Vault_ooo.cs:216",
    ),
    _c(
        "F3-07",
        "F3",
        2,
        "corpus/real-world/tcplistener-accept-leak",
        ["OWN001"],
        "factory-acquire control (AcceptTcpClient)",
        "TcpClient from AcceptTcpClient never disposed",
    ),
    _c(
        "F3-08",
        "F3",
        2,
        "corpus/real-world/local-dispose-via-using-statement",
        ["OWN001"],
        "plain local leak control",
        "local IDisposable never disposed / using in after",
    ),
    _c(
        "F3-09",
        "F3",
        2,
        "corpus/real-world/using-statement-throw-releases",
        ["OWN001"],
        "exceptional-path control (using vs manual dispose after a throwing call)",
        "manual Dispose after a may-throw call",
    ),
    _c(
        "F3-10",
        "F3",
        1,
        "corpus/real-world/ado-executereader-leak",
        ["OWN001"],
        "ADO reader leak (real-world shape)",
        "DbDataReader from ExecuteReader never disposed",
        prov_note="representative ADO.NET shape, corpus note",
    ),
    _c(
        "F3-S1",
        "F3",
        4,
        "corpus/p036-bakeoff/guarded-consume-flag-branch",
        ["OWN001"],
        "P-037 §8 row 1: guarded consume, call site passes the constant that skips the release",
        "Close(s, keep: true) never disposes",
    ),
    _c(
        "F3-S2",
        "F3",
        4,
        "corpus/p036-bakeoff/guarded-consume-early-return",
        ["OWN001"],
        "P-037 §8 row 2: early-return spelling must converge with row 1",
        "Close(s, keep: true) returns before Dispose",
    ),
    _c(
        "F3-S3",
        "F3",
        4,
        "corpus/p036-bakeoff/guarded-consume-wrapper-forward",
        ["OWN001"],
        "P-037 §8 row 7: split imported through a wrapper (id edge)",
        "Outer(s, true) -> Inner(s, true) never disposes",
    ),
    _c(
        "F3-S4",
        "F3",
        4,
        "corpus/p036-bakeoff/guarded-consume-negation-wrapper",
        ["OWN001"],
        "P-037 §8 row 8: neg edge",
        "Outer(s, stop:false) -> Inner(s, keep:true) never disposes",
    ),
    _c(
        "F3-S5",
        "F3",
        4,
        "corpus/p036-bakeoff/nullguard-helper-use-after",
        ["OWN002"],
        "P-037 §8 row 4: self-null split retires the D1 `may`; "
        "use after a provably-disposing helper",
        "Close(s) { if (s != null) s.Dispose(); } then s.Length",
    ),
    _c(
        "F3-S6",
        "F3",
        4,
        "corpus/p036-bakeoff/mixed-release-forward-use-after",
        ["OWN002"],
        "P-037 §8 row 12: unanimous must across release/forward arms",
        "Route(s, flag) consumes on both arms; s.Length after",
    ),
    # ---- F4: enrollment vs effect ----------------------------------------------
    _c(
        "F4-S1",
        "F4",
        4,
        "corpus/p036-bakeoff/enrollment-dispose-without-idisposable",
        ["OWN001"],
        "audit attack D / P-036 LifecycleEnrollment: name-root Dispose nobody can call",
        "Cache.Dispose() unsubscribes but Cache is not IDisposable; Use() drops it",
        NA_SUBSCRIPTION,
    ),
    _c(
        "F4-S2",
        "F4",
        4,
        "corpus/p036-bakeoff/enrollment-owner-drops-subscriber",
        ["OWN001"],
        "RAII half of enrollment: owner drops an IDisposable subscriber — RAII tools cover this",
        "var sub = new Subscriber(src); never disposed",
    ),
    # ---- F5: exceptional exit --------------------------------------------------
    _c(
        "F5-S1",
        "F5",
        4,
        "corpus/p036-bakeoff/subscription-release-skipped-by-throw",
        ["OWN001"],
        "P-036 Phase 2 fixture 7: -= after a may-throw call inside Dispose",
        "Dispose() { _log.Flush(); _props.PropertyChanged -= H; }",
        NA_SUBSCRIPTION,
    ),
    # ---- F6: release through delegate / virtual target -------------------------
    _c(
        "F6-S1",
        "F6",
        4,
        "corpus/p036-bakeoff/release-through-delegate-target",
        ["OWN001"],
        "P-036 Phase 2 fixture 6: cleanup through an interface (before) "
        "vs a statically-known delegate (after)",
        "Dispose() => _cleanup.Run() / _cleanup() where _cleanup = Detach",
        NA_SUBSCRIPTION,
    ),
    # ---- F7 / F8: obligations, progress ----------------------------------------
    _c(
        "F7-S1",
        "F7",
        4,
        "corpus/p036-bakeoff/obligation-barrier-through-helper",
        ["OBL001"],
        "#272/#274: forbidden barrier raised inside a helper while the obligation is open",
        "IsLoaded=false; Rebuild() notifies Document; IsLoaded=true",
        {
            **NA_OBL,
            "owen": "P-025 core exists but the C# protocol extractor is pending (proposals README)",
        },
    ),
    _c(
        "F8-S1",
        "F8",
        4,
        "corpus/p036-bakeoff/loop-no-progress-through-helper",
        ["PRG001"],
        "#275: back-edge without progress through a helper's false outcome",
        "while (queue.Count > 0) { if (!TryRun(job)) continue; queue.Dequeue(); }",
        {**NA_PRG, "owen": "PRG001 does not exist at 70189a3"},
    ),
    # ---- F9: region / DI escapes ------------------------------------------------
    _c(
        "F9-01",
        "F9",
        2,
        "corpus/di/singleton-captures-scoped-dbcontext",
        ["DI001"],
        "DI captive dependency (registration-graph lifetime rule)",
        "AddSingleton<NotificationService> whose ctor takes the scoped AppDbContext",
        NA_DI,
        stubs=["di"],
    ),
    _c(
        "F9-02",
        "F9",
        2,
        "corpus/wpf/viewmodel-escapes-to-app",
        ["OWN014"],
        "region escape: Window-scoped VM promoted to App lifetime through an App-scoped bus",
        "appBus.CustomerChanged += OnCustomerChanged, no token",
        NA_SUBSCRIPTION,
        stubs=["eventbus"],
    ),
    _c(
        "F9-03",
        "F9",
        2,
        "corpus/wpf/systemevents-region-escape",
        ["OWN014"],
        "region escape through a static process-lived source (WPF Window)",
        "SystemEvents.X += in a Window; no release path",
        NA_SUBSCRIPTION,
    ),
]

STUBS = {
    "eventbus": """// bakeoff stub (harness-provided, identical for every tool): the corpus file
// references IEventBus / CustomerChanged without declaring them.
using System;
public sealed class CustomerChanged : EventArgs { }
public interface IEventBus
{
    event EventHandler CustomerChanged;
    IDisposable Subscribe<T>(Action<T> handler);
}
""",
    "di": """// bakeoff stub (harness-provided, identical for every tool): the corpus file
// uses the Microsoft.Extensions.DependencyInjection abstractions unqualified.
global using Microsoft.Extensions.DependencyInjection;
""",
}

PACKAGES_FOR_STUB = {"di": [("Microsoft.Extensions.DependencyInjection.Abstractions", "8.0.2")]}

# ---------------------------------------------------------------------------
# rule families
# ---------------------------------------------------------------------------

OWEN_ADVISORY = {"OWN050", "OWN051", "OWN052"}
CODEQL_LEAK = {
    "cs/local-not-disposed",
    "cs/dispose-not-called-on-throw",
    "cs/missed-using-statement",
    "cs/late-dispose",
    "cs/missing-dispose",
}
CA_LEAK = {"CA2000", "CA2213"}
IDISP_LEAK = {
    "IDISP001",
    "IDISP002",
    "IDISP003",
    "IDISP004",
    "IDISP005",
    "IDISP006",
    "IDISP009",
    "IDISP016",
    "IDISP017",
    "IDISP018",
}


def is_leak_family(tool: str, rule: str, message: str = "", level: str = "") -> bool:
    if tool == "owen":
        return rule not in OWEN_ADVISORY and level in ("error", "warning", "")
    if tool == "codeql":
        r = rule.lower()
        return (
            rule in CODEQL_LEAK
            or "not-disposed" in r
            or "dispose" in r
            or rule.startswith("ownnet/p036/")
        )
    if tool == "rlc":
        return "Resource Leak" in message
    if tool == "infersharp":
        return "RESOURCE_LEAK" in rule.upper() or "MEMORY_LEAK" in rule.upper()
    if tool == "netanalyzers":
        return rule in CA_LEAK
    if tool == "idisp":
        return rule in IDISP_LEAK
    return False


@dataclass
class Finding:
    rule: str
    line: int
    message: str
    level: str = ""
    path: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunResult:
    case: str
    side: str
    tool: str
    config: str
    status: str
    findings: list[Finding]
    other: list[Finding]
    elapsed_s: float
    notes: str = ""
    timing_label: str = TIMING_LABEL


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def sh(
    cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None, timeout: int = 900
) -> tuple[int, str, str]:
    e = dict(os.environ)
    if env:
        e.update(env)
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=e,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as ex:
        return 124, str(ex.stdout or ""), f"TIMEOUT after {timeout}s: {ex}"
    except FileNotFoundError as ex:
        return 127, "", str(ex)
    return p.returncode, p.stdout, p.stderr


def dotnet_env() -> dict[str, str]:
    e = {
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        "DOTNET_NOLOGO": "1",
        "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
    }
    root = os.environ.get("DOTNET_ROOT")
    if root:
        e["PATH"] = root + os.pathsep + os.environ.get("PATH", "")
        e["DOTNET_ROOT"] = root
    return e


def parse_sarif(text: str, strip: Path | None = None) -> list[Finding]:
    out: list[Finding] = []
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        return out
    for run in doc.get("runs", []) or []:
        for r in run.get("results", []) or []:
            line = 0
            path = ""
            locs = r.get("locations") or []
            if locs:
                pl = locs[0].get("physicalLocation", {})
                path = pl.get("artifactLocation", {}).get("uri", "")
                line = int(pl.get("region", {}).get("startLine", 0) or 0)
            path = re.sub(r"^file:/*", "/", path)
            if strip and path.startswith(str(strip)):
                path = path[len(str(strip)) :].lstrip("/")
            path = path.rsplit("/", 1)[-1] if "/" in path else path
            out.append(
                Finding(
                    str(r.get("ruleId", "")),
                    line,
                    str(r.get("message", {}).get("text", "")),
                    str(r.get("level", "")),
                    path,
                    {
                        "codeFlows": len(r.get("codeFlows", []) or []),
                        "relatedLocations": len(r.get("relatedLocations", []) or []),
                    },
                )
            )
    return out


def split_findings(tool: str, fs: list[Finding]) -> tuple[list[Finding], list[Finding]]:
    leak = [f for f in fs if is_leak_family(tool, f.rule, f.message, f.level)]
    other = [f for f in fs if f not in leak]
    return leak, other


def status_for(side: str, config: str, leak: list[Finding], failure: str | None) -> str:
    if failure:
        return failure
    tag = "CUSTOM_QUERY" if config.startswith("custom_query") else config.upper()
    if side == "before":
        return f"DETECTED_{tag}" if leak else "MISSED"
    return f"FALSE_POSITIVE_{tag}" if leak else "CLEAN"


# ---------------------------------------------------------------------------
# project materialization
# ---------------------------------------------------------------------------


def needs_windows(src: str) -> bool:
    return bool(re.search(r"^\s*using System\.Windows(\.Forms)?;", src, re.M))


def packages_for(src: str, tfm: str, case: dict[str, Any]) -> list[tuple[str, str]]:
    pk: list[tuple[str, str]] = []
    if re.search(r"^\s*using Microsoft\.Win32;", src, re.M) and tfm == "net8.0":
        pk.append(("Microsoft.Win32.SystemEvents", "8.0.0"))
    if re.search(r"^\s*using System\.Data\.SqlClient;", src, re.M):
        pk.append(("System.Data.SqlClient", "4.8.6"))
    for s in case.get("stubs", []):
        pk.extend(PACKAGES_FOR_STUB.get(s, []))
    return pk


def csproj(tfm: str, packages: list[tuple[str, str]], analyzers: bool, idisp: bool) -> str:
    win = tfm.endswith("-windows")
    props = [
        f"<TargetFramework>{tfm}</TargetFramework>",
        "<OutputType>Library</OutputType>",
        "<Nullable>disable</Nullable>",
        "<ImplicitUsings>enable</ImplicitUsings>",
        "<LangVersion>latest</LangVersion>",
        "<DebugType>portable</DebugType>",
        "<TreatWarningsAsErrors>false</TreatWarningsAsErrors>",
        "<NoWarn>CS8632;CS0067;CS0414;CS0169;CS0649;CS1998;CS0168;CS0219;CS8981;CS0108;CS0618</NoWarn>",
        f"<EnableNETAnalyzers>{'true' if analyzers else 'false'}</EnableNETAnalyzers>",
        "<AnalysisLevel>latest</AnalysisLevel>" if analyzers else "",
        "<RunAnalyzersDuringBuild>true</RunAnalyzersDuringBuild>" if analyzers else "",
    ]
    if win:
        props += [
            "<UseWPF>true</UseWPF>",
            "<UseWindowsForms>true</UseWindowsForms>",
            "<EnableWindowsTargeting>true</EnableWindowsTargeting>",
        ]
    items = [f'<PackageReference Include="{n}" Version="{v}" />' for n, v in packages]
    if idisp:
        items.append(
            '<PackageReference Include="IDisposableAnalyzers" Version="4.0.8">'
            "<PrivateAssets>all</PrivateAssets></PackageReference>"
        )
    return (
        '<Project Sdk="Microsoft.NET.Sdk">\n  <PropertyGroup>\n    '
        + "\n    ".join(p for p in props if p)
        + "\n  </PropertyGroup>\n  <ItemGroup>\n    "
        + "\n    ".join(items)
        + "\n  </ItemGroup>\n</Project>\n"
    )


EDITORCONFIG_STOCK = """root = true
[*.cs]
dotnet_diagnostic.CA2000.severity = warning
dotnet_diagnostic.CA2213.severity = warning
dotnet_diagnostic.CA1001.severity = warning
dotnet_diagnostic.CA1063.severity = warning
dotnet_diagnostic.CA1816.severity = warning
"""
EDITORCONFIG_CONFIGURED = (
    EDITORCONFIG_STOCK
    + """dotnet_code_quality.CA2000.interprocedural_analysis_kind = ContextSensitive
dotnet_code_quality.CA2000.dispose_analysis_kind = AllPaths
dotnet_code_quality.CA2000.max_interprocedural_method_call_chain = 5
dotnet_code_quality.CA2213.interprocedural_analysis_kind = ContextSensitive
"""
)


def materialize(case: dict[str, Any], side: str, work: Path) -> tuple[Path, list[str], str]:
    """Create <work>/proj/<id>-<side>/ with Case.cs (+Stubs.cs) and Case.csproj.
    Returns (projdir, list of source files relative to projdir, tfm)."""
    src_dir = ROOT / case["source"]
    proj = work / "proj" / f"{case['id']}-{side}"
    if proj.exists():
        shutil.rmtree(proj)
    proj.mkdir(parents=True)
    if case.get("project"):
        # a self-contained fixture with its own project (the July oracle fixture)
        for p in src_dir.iterdir():
            if p.name in ("bin", "obj"):
                continue
            if p.is_dir():
                shutil.copytree(p, proj / p.name)
            else:
                shutil.copy2(p, proj / p.name)
        files = sorted(p.name for p in proj.glob("*.cs"))
        return proj, files, "net8.0"
    src = (src_dir / f"{side}.cs").read_text(encoding="utf-8")
    (proj / "Case.cs").write_text(src, encoding="utf-8")
    files = ["Case.cs"]
    # global-using stubs first (they must open the file), then type stubs
    stub_parts = [STUBS[s] for s in sorted(case.get("stubs", []), key=lambda k: k != "di")]
    m = re.search(r"partial class (\w+)\s*:\s*Window\b", src)
    if m and "InitializeComponent()" in src:
        # the XAML-generated half of a WPF partial class: an empty
        # InitializeComponent(), identical for every tool (recorded in the note)
        stub_parts.append(
            "// bakeoff stub (harness-provided, identical for every tool): the\n"
            "// XAML-generated half of the partial class.\n"
            f"partial class {m.group(1)} {{ private void InitializeComponent() {{ }} }}\n"
        )
    if stub_parts:
        (proj / "Stubs.cs").write_text("\n".join(stub_parts), encoding="utf-8")
        files.append("Stubs.cs")
    tfm = "net8.0-windows" if needs_windows(src) else "net8.0"
    (proj / "Case.csproj").write_text(
        csproj(tfm, packages_for(src, tfm, case), False, False), encoding="utf-8"
    )
    return proj, files, tfm


def project_file(proj: Path) -> str:
    cands = sorted(proj.glob("*.csproj"))
    return cands[0].name if cands else "Case.csproj"


# ---------------------------------------------------------------------------
# tool runners
# ---------------------------------------------------------------------------


# own-check.sh runs `dotnet build` on the shared extractor project on every call;
# two concurrent calls race on its obj/ output (CS2012). Serialize them.
_OWEN_LOCK = threading.Lock()


def run_owen(proj: Path, files: list[str]) -> tuple[list[Finding], str | None, str]:
    cmd = [
        str(ROOT / "scripts" / "own-check.sh"),
        "--format",
        "sarif",
        "--severity",
        "warning",
        "--",
    ]
    cmd += [str(proj / f) for f in files]
    with _OWEN_LOCK:
        rc, out, err = sh(cmd, cwd=proj, env=dotnet_env())
    if rc not in (0, 1):
        return [], "CRASHED", f"own-check rc={rc}: {err[-800:]}"
    fs = parse_sarif(out, proj)
    return fs, None, err[-400:] if "extractor:" in err else ""


def dotnet_build(proj: Path, outdir: str, extra: list[str] | None = None) -> tuple[bool, str]:
    cmd = [
        "dotnet",
        "build",
        project_file(proj),
        "-c",
        "Debug",
        "-o",
        outdir,
        "--no-incremental",
        "-v",
        "quiet",
        "-p:TreatWarningsAsErrors=false",
        "-p:WarningLevel=4",
    ] + (extra or [])
    rc, out, err = sh(cmd, cwd=proj, env=dotnet_env())
    return rc == 0, out + "\n" + err


WARN_RE = re.compile(
    r"^(?P<file>[^\s(]+)\((?P<line>\d+),(?P<col>\d+)\): warning "
    r"(?P<rule>CA\d{4}|IDISP\d{3}): (?P<msg>.*?)(?: \[[^\]]*\])?$",
    re.M,
)


def parse_build_warnings(log: str) -> list[Finding]:
    seen = set()
    out: list[Finding] = []
    for m in WARN_RE.finditer(log):
        key = (m.group("rule"), m.group("line"), m.group("file"))
        if key in seen:
            continue
        seen.add(key)
        msg = re.sub(r" \(https?://\S+\)", "", m.group("msg")).strip()
        out.append(
            Finding(
                m.group("rule"),
                int(m.group("line")),
                msg,
                "warning",
                m.group("file").rsplit("/", 1)[-1],
            )
        )
    return out


def run_netanalyzers(proj: Path, config: str) -> tuple[list[Finding], str | None, str]:
    (proj / ".editorconfig").write_text(
        EDITORCONFIG_STOCK if config == "stock" else EDITORCONFIG_CONFIGURED
    )
    ok, log = dotnet_build(
        proj, f"bin_ca_{config}", ["-p:EnableNETAnalyzers=true", "-p:AnalysisLevel=latest"]
    )
    (proj / ".editorconfig").unlink(missing_ok=True)
    if not ok:
        return [], "UNSUPPORTED", "build failed: " + log[-600:]
    return parse_build_warnings(log), None, ""


def run_idisp(
    proj: Path, tfm: str, packages: list[tuple[str, str]]
) -> tuple[list[Finding], str | None, str]:
    p2 = proj.parent / (proj.name + "-idisp")
    if p2.exists():
        shutil.rmtree(p2)
    shutil.copytree(proj, p2, ignore=shutil.ignore_patterns("bin*", "obj", ".editorconfig"))
    pf = project_file(p2)
    if pf == "Case.csproj":
        (p2 / pf).write_text(csproj(tfm, packages, False, True), encoding="utf-8")
    else:
        txt = (p2 / pf).read_text()
        txt = txt.replace(
            "</Project>",
            '  <ItemGroup><PackageReference Include="IDisposableAnalyzers" Version="4.0.8">'
            "<PrivateAssets>all</PrivateAssets></PackageReference></ItemGroup>\n</Project>",
        )
        (p2 / pf).write_text(txt)
    ok, log = dotnet_build(p2, "bin_idisp")
    if not ok:
        return [], "UNSUPPORTED", "build failed: " + log[-600:]
    return parse_build_warnings(log), None, ""


def run_infersharp(proj: Path, work: Path) -> tuple[list[Finding], str | None, str]:
    home = Path(os.environ.get("INFERSHARP_HOME", ""))
    if not (home / "Cilsil" / "Cilsil").exists():
        return [], "CRASHED", "INFERSHARP_HOME not set / Cilsil missing"
    ok, log = dotnet_build(proj, "bin_infer")
    if not ok:
        return [], "UNSUPPORTED", "build failed: " + log[-600:]
    # The same steps run_infersharp.sh performs, with per-case staging/result
    # dirs so cases can run concurrently (the script hard-codes one dir).
    staging = work / "infer" / proj.name / "staging"
    results = work / "infer" / proj.name / "infer-out"
    for d in (staging, results):
        if d.exists():
            shutil.rmtree(d)
    staging.mkdir(parents=True)
    bindir = proj / "bin_infer"
    for dll in bindir.rglob("*.dll"):
        pdb = dll.with_suffix(".pdb")
        shutil.copy2(dll, staging / dll.name)
        if pdb.exists():
            shutil.copy2(pdb, staging / pdb.name)
    rc, out, err = sh(
        [
            str(home / "Cilsil" / "Cilsil"),
            "translate",
            str(staging),
            "--outcfg",
            str(staging / "cfg.json"),
            "--outtenv",
            str(staging / "tenv.json"),
            "--cfgtxt",
            str(staging / "cfg.txt"),
            "--extprogress",
        ],
        cwd=home,
        env=dotnet_env(),
    )
    if rc != 0:
        return [], "CRASHED", f"Cilsil rc={rc}: {(out + err)[-600:]}"
    env = dotnet_env()
    env["PATH"] = (
        str(home / "infer" / "bin") + os.pathsep + env.get("PATH", os.environ.get("PATH", ""))
    )
    rc, out, err = sh(
        [
            "infer",
            "run",
            "-o",
            str(results),
            "--cfg-json",
            str(staging / "cfg.json"),
            "--tenv-json",
            str(staging / "tenv.json"),
        ],
        cwd=home,
        env=env,
    )
    rep = results / "report.sarif"
    if not rep.exists():
        return [], "CRASHED", f"infer rc={rc}: {(out + err)[-600:]}"
    return parse_sarif(rep.read_text(), proj), None, ""


def run_codeql(proj: Path, work: Path) -> tuple[list[Finding], str | None, str, Path | None]:
    home = Path(os.environ.get("CODEQL_HOME", ""))
    ql = home / "codeql"
    if not ql.exists():
        return [], "CRASHED", "CODEQL_HOME not set", None
    db = work / "codeql" / proj.name / "db"
    db.parent.mkdir(parents=True, exist_ok=True)
    rc, out, err = sh(
        [
            str(ql),
            "database",
            "create",
            str(db),
            "--language=csharp",
            "--build-mode=none",
            f"--source-root={proj}",
            "--overwrite",
            "--threads=2",
        ],
        cwd=proj,
        env=dotnet_env(),
    )
    if rc != 0:
        return [], "CRASHED", f"db create rc={rc}: {(out + err)[-800:]}", None
    sarif = db.parent / "stock.sarif"
    rc, out, err = sh(
        [
            str(ql),
            "database",
            "analyze",
            str(db),
            "codeql/csharp-queries:codeql-suites/csharp-security-and-quality.qls",
            "--format=sarif-latest",
            f"--output={sarif}",
            "--threads=2",
        ],
        cwd=proj,
        env=dotnet_env(),
    )
    if rc != 0 or not sarif.exists():
        return [], "CRASHED", f"analyze rc={rc}: {(out + err)[-800:]}", db
    return parse_sarif(sarif.read_text(), proj), None, "", db


_PACK_LOCK = threading.Lock()


def _rlc_pack(work: Path, extra_rows: list[str]) -> Path:
    """Copy the shipped RLC# sources into a qlpack and splice the external
    readAnnotation predicate exactly as scripts/RLC-inferred-annotations.sh
    does: library annotations + inferred rows (+ custom rows for the CUSTOM
    config). Nothing in the query text itself is modified. Packs are keyed by
    the annotation set so identical query texts share one compiled cache."""
    rlc = Path(os.environ.get("RLC_HOME", ""))
    key = hashlib.sha1("\n".join(extra_rows).encode()).hexdigest()[:12]
    pack = work / "rlc-packs" / key
    with _PACK_LOCK:
        if (pack / "ready").exists():
            return pack
        if pack.exists():
            shutil.rmtree(pack)
        pack.mkdir(parents=True)
        for f in ("RLC.ql", "Dispose.qll", "infer.ql"):
            shutil.copy2(rlc / "src" / f, pack / f)
        (pack / "qlpack.yml").write_text(
            "name: ownnet/rlc-sharp-bakeoff-"
            + key
            + "\nversion: 0.0.1\nlibraryPathDependencies: codeql/csharp-all\n"
        )
        lib = (rlc / "docs" / "library-annotations.txt").read_text()
        body = (
            "\n\npredicate readAnnotation(string filename, string lineNumber, "
            "string programElementType, string programElementName, string annotation) {\n"
        )
        body += lib.rstrip("\n") + "\n"
        for row in extra_rows:
            body += "     or " + row.strip() + "\n"
        body += "}\n"
        with (pack / "RLC.ql").open("a") as fh:
            fh.write(body)
        (pack / "ready").write_text("\n".join(extra_rows) + "\n")
    return pack


def _rlc_row(a: dict[str, str]) -> str:
    return (
        f'(filename = "{a["filename"]}" and lineNumber = "{a["line"]}" '
        f'and programElementType = "{a["type"]}" '
        f'and programElementName = "{a["name"]}" and annotation = "{a["annotation"]}")'
    )


def run_rlc(
    proj: Path, work: Path, custom: list[dict[str, str]]
) -> dict[str, tuple[list[Finding], str | None, str]]:
    """RLC# as shipped, on the period-correct CodeQL: traced build -> infer.ql
    (spec inference) -> RLC.ql with library + inferred annotations (STOCK);
    then, when the manifest carries per-case annotations, RLC.ql again with
    those rows added (CUSTOM_MODEL)."""
    home = Path(os.environ.get("CODEQL2022_HOME", ""))
    ql = home / "codeql"
    res: dict[str, tuple[list[Finding], str | None, str]] = {}
    if not ql.exists():
        return {"stock": ([], "CRASHED", "CODEQL2022_HOME not set")}
    search = ["--search-path=" + str(home / "qlpacks")]
    db = work / "rlc" / proj.name / "db"
    db.parent.mkdir(parents=True, exist_ok=True)
    rc, out, err = sh(
        [
            str(ql),
            "database",
            "create",
            str(db),
            "--language=csharp",
            f"--source-root={proj}",
            f"--command=dotnet build {project_file(proj)} -c Debug -o bin_rlc --no-incremental "
            "-p:TreatWarningsAsErrors=false",
            "--overwrite",
            "--threads=2",
        ],
        cwd=proj,
        env=dotnet_env(),
    )
    if rc != 0:
        full = out + err
        build_failed = "error CS" in full or "Build FAILED" in full or "exited with code" in full
        msg = (
            "\n".join(
                line for line in full.splitlines() if "error CS" in line or "Build FAILED" in line
            )[-800:]
            or full[-800:]
        )
        fail = "UNSUPPORTED" if build_failed else "CRASHED"
        return {"stock": ([], fail, f"traced build/db create rc={rc}: {msg}")}
    base = _rlc_pack(work, [])
    inf = db.parent / "infer.csv"
    rc, out, err = sh(
        [
            str(ql),
            "database",
            "analyze",
            str(db),
            *search,
            "--format=csv",
            f"--output={inf}",
            "--threads=2",
            str(base / "infer.ql"),
        ],
        cwd=proj,
        env=dotnet_env(),
    )
    inferred: list[str] = []
    if rc == 0 and inf.exists():
        # scripts/inference.sh: keep the "Inference ..." rows' recommendation bodies
        for row in csv.reader(inf.open()):
            if len(row) > 3 and row[0].startswith("Inference"):
                m = re.search(r"\((filename = .*)\)\s*$", row[3])
                if m:
                    inferred.append("(" + m.group(1) + ")")
        inferred = sorted(set(inferred))
    else:
        res["inference_note"] = ([], None, f"infer.ql rc={rc}: {(out + err)[-400:]}")
    (db.parent / "inferred-annotations.txt").write_text("\n".join(inferred) + "\n")

    def analyze(tag: str, rows: list[str]) -> tuple[list[Finding], str | None, str]:
        pack = _rlc_pack(work, rows)
        csvp = db.parent / f"rlc-{tag}.csv"
        rc, out, err = sh(
            [
                str(ql),
                "database",
                "analyze",
                str(db),
                *search,
                "--format=csv",
                f"--output={csvp}",
                "--threads=2",
                str(pack / "RLC.ql"),
            ],
            cwd=proj,
            env=dotnet_env(),
        )
        if rc != 0 or not csvp.exists():
            return [], "CRASHED", f"RLC.ql rc={rc}: {(out + err)[-800:]}"
        fs: list[Finding] = []
        for row in csv.reader(csvp.open()):
            if len(row) < 6:
                continue
            fs.append(
                Finding(
                    "rlc/" + ("resource-leak" if "Resource Leak" in row[3] else "annotation-check"),
                    int(row[5] or 0),
                    row[3],
                    row[2],
                    row[4].rsplit("/", 1)[-1],
                )
            )
        note = f"inferred annotations: {len(inferred)}"
        return fs, None, note

    res["stock"] = analyze("stock", inferred)
    if custom:
        res["custom_model"] = analyze("custom", inferred + [_rlc_row(a) for a in custom])
    return res


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------


def run_case(
    case: dict[str, Any], side: str, tools: list[str], work: Path, raw: Path
) -> list[RunResult]:
    results: list[RunResult] = []
    proj, files, tfm = materialize(case, side, work)
    src = (proj / files[0]).read_text(encoding="utf-8")
    packages = packages_for(src, tfm, case)
    na = case.get("na", {})

    def emit(
        tool: str, config: str, fs: list[Finding], failure: str | None, note: str, t0: float
    ) -> None:
        leak, other = split_findings(tool, fs)
        st = status_for(side, config, leak, failure)
        if tool in na and st in ("MISSED", "CLEAN"):
            st = "NOT_APPLICABLE"
            note = (note + "; " if note else "") + "n/a: " + na[tool]
        r = RunResult(
            case["id"], side, tool, config, st, leak, other, round(time.time() - t0, 2), note
        )
        results.append(r)
        (raw / tool).mkdir(parents=True, exist_ok=True)
        (raw / tool / f"{case['id']}.{side}.{config}.json").write_text(
            json.dumps(
                {
                    "case": case["id"],
                    "side": side,
                    "tool": tool,
                    "config": config,
                    "status": st,
                    "findings": [asdict(f) for f in fs],
                    "note": note,
                    "elapsed_s": r.elapsed_s,
                    "timing_label": TIMING_LABEL,
                },
                indent=1,
            )
        )

    if "owen" in tools:
        t0 = time.time()
        fs, fail, note = run_owen(proj, files)
        emit("owen", "stock", fs, fail, note, t0)
    if "netanalyzers" in tools:
        for cfg in ("stock", "configured"):
            t0 = time.time()
            fs, fail, note = run_netanalyzers(proj, cfg)
            emit("netanalyzers", cfg, fs, fail, note, t0)
    if "idisp" in tools:
        t0 = time.time()
        fs, fail, note = run_idisp(proj, tfm, packages)
        emit("idisp", "stock", fs, fail, note, t0)
    if "infersharp" in tools:
        t0 = time.time()
        fs, fail, note = run_infersharp(proj, work)
        emit("infersharp", "stock", fs, fail, note, t0)
    if "codeql" in tools:
        t0 = time.time()
        fs, fail, note, _db = run_codeql(proj, work)
        emit("codeql", "stock", fs, fail, note, t0)
    if "rlc" in tools:
        t0 = time.time()
        res = run_rlc(proj, work, case.get("rlc_annotations", []))
        for cfg, (fs, fail, note) in res.items():
            if cfg == "inference_note":
                continue
            emit("rlc", cfg, fs, fail, note, t0)
    return results


CUSTOM_QUERIES = {
    "custom_query_naive": "SubscriptionNeverRemoved.ql",
    "custom_query_teardown": "SubscriptionNotReleasedInTeardown.ql",
}


def run_custom_queries(
    queries_dir: Path, cases: list[dict[str, Any]], sides: list[str], work: Path, raw: Path
) -> list[RunResult]:
    """Post-pass: run the bakeoff-written CodeQL queries over the 2.27
    databases the main pass built. Scored DETECTED_CUSTOM_QUERY — never stock.
    The manifest's NOT_APPLICABLE declarations do not apply here: the custom
    query IS a rule for the subscription class."""
    home = Path(os.environ.get("CODEQL_HOME", ""))
    ql = home / "codeql"
    pack = work / "custom-ql"
    if pack.exists():
        shutil.rmtree(pack)
    shutil.copytree(queries_dir, pack, ignore=shutil.ignore_patterns(".codeql", "*.lock.yml"))
    sh([str(ql), "pack", "install"], cwd=pack, env=dotnet_env())
    results: list[RunResult] = []
    for c in cases:
        for side in sides:
            proj_name = f"{c['id']}-{side}"
            db = work / "codeql" / proj_name / "db"
            for cfg, qfile in CUSTOM_QUERIES.items():
                t0 = time.time()
                if not db.exists():
                    fs, fail, note = [], "UNSUPPORTED", "no CodeQL database from the main pass"
                else:
                    sarif = db.parent / f"{cfg}.sarif"
                    rc, out, err = sh(
                        [
                            str(ql),
                            "database",
                            "analyze",
                            str(db),
                            str(pack / qfile),
                            "--format=sarif-latest",
                            f"--output={sarif}",
                            "--threads=2",
                        ],
                        cwd=pack,
                        env=dotnet_env(),
                    )
                    if rc != 0 or not sarif.exists():
                        fs, fail, note = (
                            [],
                            "CRASHED",
                            f"custom analyze rc={rc}: {(out + err)[-600:]}",
                        )
                    else:
                        fs, fail, note = parse_sarif(sarif.read_text()), None, ""
                leak, other = split_findings("codeql", fs)
                st = status_for(side, cfg, leak, fail)
                r = RunResult(
                    c["id"], side, "codeql", cfg, st, leak, other, round(time.time() - t0, 2), note
                )
                results.append(r)
                (raw / "codeql").mkdir(parents=True, exist_ok=True)
                (raw / "codeql" / f"{c['id']}.{side}.{cfg}.json").write_text(
                    json.dumps(
                        {
                            "case": c["id"],
                            "side": side,
                            "tool": "codeql",
                            "config": cfg,
                            "status": st,
                            "findings": [asdict(f) for f in fs],
                            "note": note,
                            "elapsed_s": r.elapsed_s,
                            "timing_label": TIMING_LABEL,
                        },
                        indent=1,
                    )
                )
            print(
                f"[{c['id']} {side}] custom: "
                + "  ".join(
                    f"{r.config}={r.status}({len(r.findings)})"
                    for r in results[-len(CUSTOM_QUERIES) :]
                ),
                flush=True,
            )
    return results


D2_SCOPE_FAMILIES = {"F4", "F5", "F6"}  # plus the class-4 F3 cases (preregistration §0.6)


def decision_inputs(results: list[RunResult], cases: list[dict[str, Any]]) -> dict[str, Any]:
    """The MECHANICAL inputs to the preregistered predicates D1, D2, D4 (docs/notes/
    p036-bakeoff.md §0.6), computed from statuses only so an auditor can recompute
    them without reading the note. D3 (necessity) and D6 (admissibility) are
    judgments and are not computed here. Custom-query configs never count."""
    idx = {(r.case, r.side, r.tool, r.config): r for r in results}
    comparator_cfgs = sorted(
        {
            (r.tool, r.config)
            for r in results
            if r.tool != "owen" and not r.config.startswith("custom_query")
        }
    )

    def status(cid: str, side: str, tool: str, cfg: str) -> str:
        r = idx.get((cid, side, tool, cfg))
        return r.status if r else "ABSENT"

    def disc(cid: str, tool: str, cfg: str) -> bool:
        # NOT_APPLICABLE is only ever assigned over a CLEAN/MISSED raw status,
        # so an after side labelled N/A was clean: a detection on before counts.
        return status(cid, "before", tool, cfg).startswith("DETECTED") and status(
            cid, "after", tool, cfg
        ) in ("CLEAN", "ABSENT", "NOT_APPLICABLE")

    fams: dict[str, list[dict[str, Any]]] = {}
    for c in cases:
        fams.setdefault(c["family"], []).append(c)
    out: dict[str, Any] = {
        "rules": {
            "discriminates": "before status starts with DETECTED and after status is one "
            "of CLEAN, NOT_APPLICABLE, ABSENT (NOT_APPLICABLE is only ever assigned over a "
            "raw CLEAN/MISSED, so an N/A fix side was clean; ABSENT = no result row for "
            "that side)",
            "D1_family": "Owen discriminates >= 1 case, Owen has no FALSE_POSITIVE on any "
            "fix, and no comparator stock/configured config discriminates any case",
            "D2_scope": "cases in F4/F5/F6 plus class-4 F3 cases whose Owen before status "
            "is MISSED",
            "D2_global": "no D2-scope case is discriminated by any comparator "
            "stock/configured config",
            "D2_per_family": "same, restricted to each family",
            "D4_evidenced": "family holds a class-1 case AND no comparator config "
            "discriminates any case in it",
        },
        "comparator_configs": [f"{t}/{g}" for t, g in comparator_cfgs],
        "families": {},
    }
    for f, cs in sorted(fams.items()):
        owen_disc = [c["id"] for c in cs if disc(c["id"], "owen", "stock")]
        owen_fp = [
            c["id"]
            for c in cs
            if status(c["id"], "after", "owen", "stock").startswith("FALSE_POSITIVE")
        ]
        owen_missed = [
            c["id"] for c in cs if status(c["id"], "before", "owen", "stock") == "MISSED"
        ]
        owen_na = [
            c["id"]
            for c in cs
            if status(c["id"], "before", "owen", "stock")
            in ("NOT_APPLICABLE", "UNSUPPORTED", "CRASHED")
        ]
        comp = {
            f"{t}/{g}": [c["id"] for c in cs if disc(c["id"], t, g)] for t, g in comparator_cfgs
        }
        comp_fp = {
            f"{t}/{g}": [
                c["id"] for c in cs if status(c["id"], "after", t, g).startswith("FALSE_POSITIVE")
            ]
            for t, g in comparator_cfgs
        }
        class1 = [c["id"] for c in cs if c["provenance"] == 1]
        any_comp = any(v for v in comp.values())
        out["families"][f] = {
            "cases": [c["id"] for c in cs],
            "class1_cases": class1,
            "owen_discriminates": owen_disc,
            "owen_false_positive_on_fix": owen_fp,
            "owen_missed": owen_missed,
            "owen_not_run_or_na": owen_na,
            "comparator_discriminates": comp,
            "comparator_false_positive_on_fix": comp_fp,
            "D1_holds_for_family": bool(owen_disc) and not owen_fp and not any_comp,
            "D4_evidenced": bool(class1) and not any_comp,
        }
    d2_cases = [
        c
        for c in cases
        if (c["family"] in D2_SCOPE_FAMILIES or (c["family"] == "F3" and c["provenance"] == 4))
        and status(c["id"], "before", "owen", "stock") == "MISSED"
    ]
    d2: dict[str, Any] = {}
    for c in d2_cases:
        d2[c["id"]] = {
            "family": c["family"],
            "commoditised_by": [f"{t}/{g}" for t, g in comparator_cfgs if disc(c["id"], t, g)],
            "comparator_before_status": {
                f"{t}/{g}": status(c["id"], "before", t, g) for t, g in comparator_cfgs
            },
        }
    out["D2"] = {
        "scope_cases": d2,
        "global_holds": all(not v["commoditised_by"] for v in d2.values()),
        "per_family_holds": {
            f: all(not v["commoditised_by"] for v in d2.values() if v["family"] == f)
            for f in sorted({v["family"] for v in d2.values()})
        },
    }
    out["D1"] = {
        "families_holding": [f for f, v in out["families"].items() if v["D1_holds_for_family"]]
    }
    out["D4"] = {"families_evidenced": [f for f, v in out["families"].items() if v["D4_evidenced"]]}
    return out


def summarize(results: list[RunResult], cases: list[dict[str, Any]], out: Path) -> None:
    # a case with no fix side (the July console fixture) has no `after` row: drop
    # any stray result for a side the manifest does not declare
    allowed = {(c["id"], s) for c in cases for s in c.get("sides", ["before", "after"])}
    results = [r for r in results if (r.case, r.side) in allowed]
    tools_cfg = sorted({(r.tool, r.config) for r in results}, key=lambda x: (x[0], x[1]))
    lines = [
        "# P-036 bakeoff — status matrix (generated by scripts/p036_bakeoff.py)",
        "",
        f"Timing label for every elapsed value: {TIMING_LABEL}",
        "",
        "| case | family | prov | side | " + " | ".join(f"{t}/{c}" for t, c in tools_cfg) + " |",
        "|---|---|---|---|" + "|".join("---" for _ in tools_cfg) + "|",
    ]
    idx: dict[tuple[str, str, str, str], RunResult] = {
        (r.case, r.side, r.tool, r.config): r for r in results
    }
    for c in cases:
        for side in ("before", "after"):
            cells = []
            for t, cfg in tools_cfg:
                r = idx.get((c["id"], side, t, cfg))
                cells.append("" if r is None else f"{r.status} ({len(r.findings)})")
            lines.append(
                f"| {c['id']} | {c['family']} | {c['provenance']} | {side} | "
                + " | ".join(cells)
                + " |"
            )
    # Discrimination: a tool discriminates a case only when it flags `before`
    # AND stays silent on `after`. A detection paired with a false positive on
    # the fix is evidence the tool never modelled the mechanism under test.
    disc: dict[str, dict[str, Any]] = {}
    for t, cfg in tools_cfg:
        key = f"{t}/{cfg}"
        d = disc.setdefault(
            key,
            {
                "discriminates": [],
                "detected_but_fp_on_fix": [],
                "missed": [],
                "not_applicable": [],
                "unsupported_or_crashed": [],
            },
        )
        for c in cases:
            b = idx.get((c["id"], "before", t, cfg))
            a = idx.get((c["id"], "after", t, cfg))
            if b is None:
                continue
            if b.status.startswith("DETECTED") and (
                a is None or a.status in ("CLEAN", "NOT_APPLICABLE")
            ):
                d["discriminates"].append(c["id"])
            elif b.status.startswith("DETECTED"):
                d["detected_but_fp_on_fix"].append(c["id"])
            elif b.status == "MISSED":
                d["missed"].append(c["id"])
            elif b.status == "NOT_APPLICABLE":
                d["not_applicable"].append(c["id"])
            else:
                d["unsupported_or_crashed"].append(c["id"])
    lines += [
        "",
        "## Discrimination per tool/config (before flagged AND fix silent)",
        "",
        "| tool/config | discriminates | detected but FP on fix | missed | n/a "
        "| unsupported/crashed |",
        "|---|---|---|---|---|---|",
    ]
    for key, d in disc.items():
        lines.append(
            f"| {key} | {len(d['discriminates'])}: {' '.join(d['discriminates'])} "
            f"| {len(d['detected_but_fp_on_fix'])}: {' '.join(d['detected_but_fp_on_fix'])} "
            f"| {len(d['missed'])}: {' '.join(d['missed'])} | {len(d['not_applicable'])} "
            f"| {len(d['unsupported_or_crashed'])}: {' '.join(d['unsupported_or_crashed'])} |"
        )
    dec = decision_inputs(results, cases)
    lines += [
        "",
        "## Mechanical decision inputs (D1 / D2 / D4; D3 and D6 are judgments in the note)",
        "",
        f"- D1 holds for families: {dec['D1']['families_holding']}",
        f"- D2 global: {dec['D2']['global_holds']}; per family: {dec['D2']['per_family_holds']}",
        f"- D4 evidenced families: {dec['D4']['families_evidenced']}",
        "",
        "| family | class-1 | Owen discriminates | Owen FP on fix | Owen missed "
        "| comparators discriminating (stock/configured) |",
        "|---|---|---|---|---|---|",
    ]
    for f, v in dec["families"].items():
        comps = (
            "; ".join(
                f"{k}: {' '.join(ids)}" for k, ids in v["comparator_discriminates"].items() if ids
            )
            or "none"
        )
        lines.append(
            f"| {f} | {len(v['class1_cases'])} "
            f"| {len(v['owen_discriminates'])}: {' '.join(v['owen_discriminates'])} "
            f"| {len(v['owen_false_positive_on_fix'])}: "
            f"{' '.join(v['owen_false_positive_on_fix'])} "
            f"| {len(v['owen_missed'])}: {' '.join(v['owen_missed'])} | {comps} |"
        )
    lines += [
        "",
        "D2-scope cases (Owen MISSED inside the P-036 scope) and who commoditises them:",
        "",
    ]
    for cid, v in dec["D2"]["scope_cases"].items():
        lines.append(f"- {cid} ({v['family']}): " + (", ".join(v["commoditised_by"]) or "nobody"))
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    (out / "results.json").write_text(
        json.dumps(
            {
                "head": sh(["git", "rev-parse", "HEAD"], cwd=ROOT)[1].strip(),
                "timing_label": TIMING_LABEL,
                "discrimination": disc,
                "decision_inputs": dec,
                "results": [asdict(r) for r in results],
            },
            indent=1,
        )
    )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--write-manifest", metavar="PATH")
    ap.add_argument("--manifest", metavar="PATH")
    ap.add_argument("--work", metavar="DIR")
    ap.add_argument("--out", metavar="DIR")
    ap.add_argument("--tools", default="owen,netanalyzers,idisp,infersharp,codeql,rlc")
    ap.add_argument("--cases", default="")
    ap.add_argument("--sides", default="before,after")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument(
        "--resummarize",
        action="store_true",
        help="rewrite summary.md / results.json from the existing results.json, no tool runs",
    )
    ap.add_argument(
        "--merge",
        action="store_true",
        help="merge this (partial) run into the existing results.json",
    )
    ap.add_argument(
        "--custom-queries",
        metavar="DIR",
        help="post-pass: run the bakeoff CodeQL queries in DIR over existing databases",
    )
    a = ap.parse_args(argv)
    if a.write_manifest:
        Path(a.write_manifest).write_text(
            json.dumps({"preregistered_at": "70189a3", "cases": CASES}, indent=1) + "\n"
        )
        print(f"wrote {a.write_manifest} ({len(CASES)} cases)")
        return 0
    if not (a.manifest and a.work and a.out):
        ap.error("--manifest, --work and --out are required to run")
    cases = json.loads(Path(a.manifest).read_text())["cases"]
    if a.cases:
        want = set(a.cases.split(","))
        cases = [c for c in cases if c["id"] in want]
    tools = a.tools.split(",")
    sides = a.sides.split(",")
    work = Path(a.work)
    out = Path(a.out)
    raw = out / "raw"
    (work / "proj").mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)
    if a.resummarize:
        prior = json.loads((out / "results.json").read_text())["results"]
        results = [
            RunResult(
                **{
                    **r,
                    "findings": [Finding(**f) for f in r["findings"]],
                    "other": [Finding(**f) for f in r["other"]],
                }
            )
            for r in prior
        ]
        allcases = json.loads(Path(a.manifest).read_text())["cases"]
        summarize(results, allcases, out)
        print(f"rewrote {out / 'summary.md'} and {out / 'results.json'}")
        return 0
    if a.custom_queries:
        prior = json.loads((out / "results.json").read_text())["results"]
        results = [
            RunResult(
                **{
                    **r,
                    "findings": [Finding(**f) for f in r["findings"]],
                    "other": [Finding(**f) for f in r["other"]],
                }
            )
            for r in prior
        ]
        allcases = json.loads(Path(a.manifest).read_text())["cases"]
        fresh = run_custom_queries(Path(a.custom_queries), cases, sides, work, raw)
        keep = {(r.case, r.side, r.tool, r.config) for r in fresh}
        results = [r for r in results if (r.case, r.side, r.tool, r.config) not in keep] + fresh
        results.sort(key=lambda r: (r.case, r.side, r.tool, r.config))
        summarize(results, allcases, out)
        print(f"wrote {out / 'summary.md'} and {out / 'results.json'}")
        return 0
    jobs = [(c, s) for c in cases for s in sides if s in c.get("sides", ["before", "after"])]
    results: list[RunResult] = []
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        futs = {ex.submit(run_case, c, s, tools, work, raw): (c["id"], s) for c, s in jobs}
        for f in futs:
            cid, s = futs[f]
            try:
                rs = f.result()
            except Exception as e:
                rs = [
                    RunResult(cid, s, t, "stock", "CRASHED", [], [], 0.0, f"harness: {e!r}")
                    for t in tools
                ]
            results.extend(rs)
            print(
                f"[{cid} {s}] "
                + "  ".join(f"{r.tool}/{r.config}={r.status}({len(r.findings)})" for r in rs),
                flush=True,
            )
    if a.merge and (out / "results.json").exists():
        prior = json.loads((out / "results.json").read_text())["results"]
        keep = {(r.case, r.side, r.tool, r.config) for r in results}
        results += [
            RunResult(
                **{
                    **r,
                    "findings": [Finding(**f) for f in r["findings"]],
                    "other": [Finding(**f) for f in r["other"]],
                }
            )
            for r in prior
            if (r["case"], r["side"], r["tool"], r["config"]) not in keep
        ]
        cases = json.loads(Path(a.manifest).read_text())["cases"]
    results.sort(key=lambda r: (r.case, r.side, r.tool, r.config))
    summarize(results, cases, out)
    print(f"wrote {out / 'summary.md'} and {out / 'results.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
