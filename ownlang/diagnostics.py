"""Diagnostics for OwnLang. One place for every code and its human title.

Numbering scheme (renumbered in this revision -- see README changelog):

  001-013  flow-sensitive ownership & loan/permission violations
  020      unsupported construct (loops / async)
  030-034  name resolution & structural
  040-041  extern / call-boundary
  050      C# front-end resolution coverage (P-014; advisory, never a verdict)

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
    # ---- reactive-effect stability (P-020; a separate analysis, like DI001) ----
    "EFF001": "reactive effect re-runs on an unstable dependency identity (render-time IO storm)",
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

    @property
    def title(self) -> str:
        return TITLES.get(self.code, "")

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
