"""Diagnostics for OwnLang. One place for every code and its human title.

Numbering scheme (renumbered in this revision -- see README changelog):

  001-013  flow-sensitive ownership & loan/permission violations
  020      unsupported construct (loops / async)
  030-034  name resolution & structural
  040-041  extern / call-boundary
  050      C# front-end resolution coverage (P-014; advisory, never a verdict)

Sidecar analysis families carry their own prefixes (DI, EFF, OBL) — each is a
separate analysis the OwnIR bridge routes facts to, not the core lattice.

The split between *definite* (002 use-after-release, 005 use-after-move) and
*maybe* (009, 010) codes is deliberate: a fault that holds on every path is a
different, sharper message than one that holds on only some path through a
branch. That distinction was the reviewer's strongest point and it falls out
naturally from the set-of-states lattice.

A diagnostic can also carry an ordered *reachability slice* (``Evidence``): the
chain of program points that explains *why* it holds -- where a resource was
acquired, where a borrow escapes, where the missing release should go. This is
the structured successor to the textual ``[consumed by ... at file:line]``
riders the DI findings append: same information, but a place a tool can point at
instead of a string to parse (P-015). See ``ownlang.evidence`` for the SARIF
projection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

# the first single-quoted identifier in a message is the thing it is about
# ('b' in "use 'b' after it was released"); used to place a caret under it.
_SUBJECT_RE = re.compile(r"'([^']+)'")


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"


TITLES = {
    # ---- flow-sensitive ownership / loans / permissions ----
    "OWN001": "owned resource not released on all paths (possible leak)",
    "OWN002": "use after release",
    "OWN003": "double release",
    "OWN004": "borrow escapes its scope",
    "OWN005": "use after move",
    "OWN006": "mutable borrow while a shared borrow is live",
    "OWN007": "move while borrowed",
    "OWN008": "release while borrowed",
    "OWN009": "use after possible release (released on some path)",
    "OWN010": "use after possible move (moved on some path)",
    "OWN011": "mutable borrow while another mutable borrow is live",
    "OWN012": "shared borrow while a mutable borrow is live",
    "OWN013": "owner accessed while it is mutably borrowed",
    "OWN014": "value escapes to a longer-lived region (lifetime promotion)",
    # ---- buffer storage policies (stackalloc / scratch / pool / native) ----
    "OWN015": "stack-backed buffer cannot escape the current function",
    "OWN016": "stack-backed buffer moved to a longer-lived owner",
    "OWN017": "movable buffer escape is not supported by code generation (PoC limitation)",
    "OWN018": "buffer size must be an integer",
    "OWN019": "inline capacity too large for a stack-backed policy",
    "OWN021": "stack allocation requires a statically known bound",
    "OWN023": "scratch fallback forbidden but the size may exceed the inline limit",
    "OWN024": "sensitive buffer is not cleared on release",
    "OWN025": "full-length view of a pooled buffer reaches past its logical length",
    # ---- unsupported ----
    "OWN020": "unsupported construct (out of scope for the MVP)",
    # ---- name resolution & structural ----
    "OWN030": "undefined name",
    "OWN031": "name already defined in this scope",
    "OWN032": "owned resource copied without 'move'",
    "OWN033": "function must return a value on all paths",
    "OWN034": "operation requires an owned resource",
    "OWN035": "return type mismatch",
    "OWN036": "cyclic lifetime ordering",
    # ---- extern / call boundary ----
    "OWN040": "call to an undeclared function (unknown calls are forbidden)",
    "OWN041": "call argument mismatch",
    # ---- C# front-end resolution coverage (P-014; advisory) ----
    "OWN050": "declaring type unresolved -- leakage analysis skipped",
    # ---- DI container lifetimes (P-006; emitted by the OwnIR bridge) ----
    "DI001": "captive dependency: a shorter-lived service is captured by a longer-lived one",
    "DI002": "singleton captures a scoped service (captive dependency)",
    "DI003": "singleton captures a transient service (captive dependency)",
    "DI004": "scoped service resolved from the root provider (captured for the app lifetime)",
    "DI005": "disposable transient resolved from a long-lived scope (delayed disposal)",
    # ---- reactive-effect stability (P-020; a separate analysis, like DI001) ----
    "EFF001": "reactive effect re-runs on an unstable dependency identity (render-time IO storm)",
    # ---- obligation protocols (P-025; a separate analysis, like DI001) ----
    "OBL001": "obligation still open when a barrier fires (open on every path)",
    "OBL002": "obligation may still be open when a barrier fires (open on some path)",
    "OBL003": "obligation not closed before the method exits (on every path)",
    "OBL004": "obligation may not be closed before the method exits (on some path)",
    "OBL005": "protocol scope matched no reported method -- rule is dead (advisory)",
}


# Long-form `explain` text: a paragraph of "what this means / why it leaks / how
# to fix", keyed by code. The `explain` command (`python -m ownlang explain OWN001`)
# prints this; a code with no entry here falls back to its one-line TITLE, so the
# command always answers. Kept deliberately to the codes a user actually meets via
# the Roslyn extractor pipeline (subscription/disposable/DI), not the whole grammar.
EXPLANATIONS = {
    "DI001": (
        "Captive dependency (the umbrella verdict): a longer-lived service holds a reference to a "
        "shorter-lived one, so the shorter-lived instance is pinned to the longer life — its "
        "intended per-scope/per-call semantics are lost and it may leak. DI002-DI005 are the "
        "specific shapes (singleton->scoped, singleton->transient, scoped-from-root, "
        "disposable-transient-from-a-long-scope).\n"
        "Fix: don't capture the shorter-lived service directly — inject `IServiceScopeFactory`, "
        "create a scope per use, and resolve from it (or align the lifetimes). A `Func<T>` "
        "factory also works but the built-in container does not auto-resolve `Func<T>` — you must "
        "register it (or use a container that does)."
    ),
    "OWN001": (
        "An owned resource is acquired but not released on every path out of its owner — "
        "a possible leak. For a C# event, `target += handler` with no matching `target -= "
        "handler` keeps the handler (and everything it captures) alive for as long as the "
        "event source lives.\n"
        "Fix: release on every path — unsubscribe (`-=`) in Dispose/Unloaded, dispose the "
        "owned field in the owner's Dispose, or capture and dispose the IDisposable a "
        "Subscribe() returns."
    ),
    "OWN002": (
        "A resource is used after it was released, so the access touches a freed/disposed "
        "object.\nFix: move the use before the release, or do not release while the value is "
        "still needed."
    ),
    "OWN003": (
        "A resource is released twice on some path (double dispose/return).\n"
        "Fix: release on exactly one path; guard the second release or restructure so the "
        "branches don't both release."
    ),
    "OWN009": (
        "A resource is used after a release that happens on only *some* paths, so whether the "
        "value is live depends on the branch taken.\n"
        "Fix: make release happen on all paths or none before the use, so the state is "
        "unambiguous at the use site."
    ),
    "OWN014": (
        "A value escapes into a longer-lived region than its own (lifetime promotion) — e.g. a "
        "ViewModel stored where it outlives the View that owns it.\n"
        "Fix: keep the value within its region, or transfer ownership explicitly to the "
        "longer-lived holder so its disposal is accounted for there."
    ),
    "OWN025": (
        "A full-length view (Span/Memory over the whole array) of a pooled buffer reaches past "
        "the buffer's logical length — ArrayPool.Rent may return a larger array than requested.\n"
        "Fix: slice to the logical length (`buf.AsSpan(0, len)`) before viewing the rented array."
    ),
    "OWN050": (
        "Advisory, not a leak verdict: the declaring type of a `+=`/`-=` (e.g. a third-party "
        "WPF/DevExpress event) could not be resolved, so leakage analysis was skipped for it "
        "rather than guessed (P-014 Tier A). It never fails a build.\n"
        "Fix (to check it): give the extractor the type's assembly via `--ref-dir <bin>` so the "
        "SemanticModel can bind the event."
    ),
    "DI002": (
        "A singleton captures a scoped service: the scoped instance is pinned to the singleton "
        "for the whole app lifetime, defeating per-scope (e.g. per-request) semantics and often "
        "leaking a DbContext-like object.\n"
        "Fix: don't inject the scoped service into the singleton — inject `IServiceScopeFactory`, "
        "create a scope per use, and resolve the scoped service from it. (A registered `Func<T>` "
        "factory also works, but the built-in container does not auto-resolve `Func<T>`.)"
    ),
    "DI003": (
        "A singleton captures a transient service: the transient is created once and lives for "
        "the app lifetime, so its intended short life is lost.\n"
        "Fix: resolve the transient per use from a scope (`IServiceScopeFactory`) instead of "
        "holding the instance — or inject a `Func<T>` factory you have registered (the built-in "
        "container does not auto-resolve `Func<T>`)."
    ),
    "DI004": (
        "A scoped service is resolved from the root provider, so it is captured for the whole "
        "application lifetime instead of the intended scope.\n"
        "Fix: resolve scoped services from a created scope (`IServiceScopeFactory.CreateScope()`), "
        "not from the root provider."
    ),
    "DI005": (
        "A disposable transient is resolved from a long-lived scope (often the root): the "
        "container tracks it and only disposes it when that scope ends, delaying disposal.\n"
        "Fix: resolve disposable transients within a short-lived scope you dispose, or manage "
        "their lifetime explicitly."
    ),
    "OBL001": (
        "A project-declared obligation protocol (e.g. \"`IsLoaded = false` must be closed by "
        "`IsLoaded = true`\") is still open when a declared barrier fires — on every path that "
        "reaches the barrier. The classic WPF shape: a method flips a consistency flag down, "
        "rebuilds state, and raises `PropertyChanged(\"Document\")` before flipping the flag "
        "back up, publishing an inconsistent object to bindings and listeners.\n"
        "Fix: close the obligation before the barrier (move the closing assignment/call above "
        "the notification), or — if that notification is genuinely safe while open — add it to "
        "the protocol's `allow` list."
    ),
    "OBL003": (
        "A project-declared obligation is opened but not closed before the method exits "
        "(return / throw / falling off the end) on every path — the object is left in its "
        "\"temporarily broken\" state for the outside world to observe. The exception path is "
        "the classic culprit: `IsLoaded = false; Load(); IsLoaded = true;` leaves the flag down "
        "forever when `Load()` throws.\n"
        "Fix: close in a `finally`, or on every early-return path."
    ),
    "OBL005": (
        "Advisory, not a verdict: a protocol's `scope.methods` matched none of the methods the "
        "frontend reported events for — the rule is dead (usually a typo'd or renamed method "
        "name). A silently dead project rule is worse than none: it reads as coverage that "
        "does not exist.\n"
        "Fix: correct the scope, or delete the rule."
    ),
    "EFF001": (
        "A React `useEffect` re-runs whenever one of its declared dependencies changes identity. "
        "A dependency that is an object/array literal created in render scope gets a fresh "
        "identity on every render, so the effect re-fires every render; if the effect does IO "
        "(a `fetch`), that is a render-rate request storm — not a memory leak, a request leak.\n"
        "Fix: stabilise the dependency — wrap the object/array in `useMemo`/`useCallback` (or a "
        "`useRef`), depend on the primitive fields instead of the object, or move the value out "
        "of render scope."
    ),
}


@dataclass(frozen=True)
class Evidence:
    """One secondary, structured location that explains a diagnostic -- a single step
    in its reachability slice: where the resource was acquired, where a borrow
    escapes, where the missing release should go, what consumed it. The primary
    ``Diagnostic.line`` stays the anchor; evidence rides alongside it (rendered as
    ``note:`` lines here; emitted as SARIF relatedLocations / codeFlows by
    ``ownlang.evidence``).

    This is the structured successor to the textual ``[consumed by ... at
    file:line]`` riders: the same information, but a place a tool can point at
    instead of a string to parse.
    """

    line: int
    label: str
    # the file of this step; None means "same file as the diagnostic's anchor".
    file: str | None = None
    # what this step is, for consumers that group/colour evidence: a plain "related"
    # by default, or a resource-protocol role (acquired/released/escaped/consumed/step).
    role: str = "related"

    def render(self, anchor_file: str) -> str:
        """A one-line ``note:`` rendering pointing at this step. ``anchor_file`` is
        the diagnostic's own file, used when this step shares it (``file is None``)."""
        where = self.file or anchor_file
        return f"  note: {self.label} at {where}:{self.line}"


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    line: int
    severity: Severity = Severity.ERROR
    # for buffer diagnostics: a stable identity (name#line) of the buffer the
    # diagnostic is about, so the report attributes it by symbol, not by name.
    subject: str | None = None
    # the resource's human "kind" (e.g. "subscription token"), when the finding
    # is about a tagged resource. Rendered as a ` [resource: <kind>]` suffix --
    # domain-neutral metadata a later profile (e.g. WPF) keys off.
    resource_kind: str | None = None
    # ordered reachability slice that explains this diagnostic (acquire site, escape
    # site, missing-release point, consuming call). Empty for a single-point finding.
    # Rendered as `note:` lines; a SARIF consumer maps it to relatedLocations /
    # codeFlows via ownlang.evidence. Declared LAST so the positional constructor
    # contract (code, message, line, severity, subject, resource_kind) is preserved.
    evidence: tuple[Evidence, ...] = ()

    def __post_init__(self) -> None:
        # A code with no TITLES entry is a bug, not a blank finding: `title` used to
        # silently return "" for a typo'd or forgotten code. Fail loudly at
        # construction so a mis-typed code can never ship a titleless diagnostic —
        # the one stringly-typed contract in a --strict codebase.
        if self.code not in TITLES:
            raise ValueError(
                f"unknown diagnostic code {self.code!r} (not in diagnostics.TITLES); "
                f"a code and its title must be added together"
            )

    @property
    def title(self) -> str:
        return TITLES[self.code]

    def _kind_suffix(self) -> str:
        return f" [resource: {self.resource_kind}]" if self.resource_kind else ""

    def _caret_col(self, src_line: str) -> int | None:
        """1-based column of this diagnostic in `src_line`: the position of the
        identifier it names. None if it cannot be located."""
        m = _SUBJECT_RE.search(self.message)
        if m:
            name = m.group(1)
            # prefer a whole-word match so 'a' lands on the argument in `Hash(a)`,
            # not on the 'a' inside `Hash`; fall back to a plain substring search.
            wb = re.search(rf"\b{re.escape(name)}\b", src_line)
            if wb:
                return wb.start() + 1
            idx = src_line.find(name)
            if idx >= 0:
                return idx + 1
        stripped = len(src_line) - len(src_line.lstrip())
        return stripped + 1 if src_line.strip() else None

    def _evidence_lines(self, filename: str) -> list[str]:
        """The `note:` lines for this diagnostic's reachability slice, in order.
        Empty when the finding carries no evidence (the common case), so the base
        renderings stay byte-for-byte unchanged."""
        return [e.render(filename) for e in self.evidence]

    def render(self, filename: str = "<input>") -> str:
        """Plain rendering: `file:line: severity: [code] message`, followed by one
        `note:` line per evidence step when present."""
        head = (
            f"{filename}:{self.line}: {self.severity.value}: "
            f"[{self.code}] {self.message}{self._kind_suffix()}"
        )
        return "\n".join([head, *self._evidence_lines(filename)])

    def render_pretty(self, filename: str, source: str) -> str:
        """A rustc-style rendering: a `file:line:col` header, the offending
        source line, a caret under the named identifier, and a `note:` line per
        evidence step. Falls back to the plain header when the line/column cannot
        be resolved."""
        lines = source.splitlines()
        src_line = lines[self.line - 1] if 1 <= self.line <= len(lines) else ""
        col = self._caret_col(src_line)
        loc = f"{filename}:{self.line}" + (f":{col}" if col else "")
        out = [f"{loc}: {self.severity.value}: [{self.code}] "
               f"{self.message}{self._kind_suffix()}"]
        if src_line.strip():
            gutter = f"  {self.line} | "
            out.append(f"{gutter}{src_line}")
            if col:
                out.append(" " * (len(gutter) + col - 1) + "^")
        out.extend(self._evidence_lines(filename))
        return "\n".join(out)
