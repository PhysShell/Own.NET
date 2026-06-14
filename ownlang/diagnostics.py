"""Diagnostics for OwnLang. One place for every code and its human title.

Numbering scheme (renumbered in this revision — see README changelog):

  001-013  flow-sensitive ownership & loan/permission violations
  020      unsupported construct (loops / async)
  030-034  name resolution & structural
  040-041  extern / call-boundary

The split between *definite* (002 use-after-release, 005 use-after-move) and
*maybe* (009, 010) codes is deliberate: a fault that holds on every path is a
different, sharper message than one that holds on only some path through a
branch. That distinction was the reviewer's strongest point and it falls out
naturally from the set-of-states lattice.
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
    # ---- buffer storage policies (stackalloc / scratch / pool / native) ----
    "OWN015": "stack-backed buffer cannot escape the current function",
    "OWN016": "stack-backed buffer moved to a longer-lived owner",
    "OWN017": "movable buffer escape is not supported by code generation (PoC limitation)",
    "OWN018": "buffer size must be an integer",
    "OWN019": "inline capacity too large for a stack-backed policy",
    "OWN021": "stack allocation requires a statically known bound",
    "OWN023": "scratch fallback forbidden but the size may exceed the inline limit",
    "OWN024": "sensitive buffer is not cleared on release",
    # ---- unsupported ----
    "OWN020": "unsupported construct (out of scope for the MVP)",
    # ---- name resolution & structural ----
    "OWN030": "undefined name",
    "OWN031": "name already defined in this scope",
    "OWN032": "owned resource copied without 'move'",
    "OWN033": "function must return a value on all paths",
    "OWN034": "operation requires an owned resource",
    "OWN035": "return type mismatch",
    # ---- extern / call boundary ----
    "OWN040": "call to an undeclared function (unknown calls are forbidden)",
    "OWN041": "call argument mismatch",
}


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    line: int
    severity: Severity = Severity.ERROR
    # for buffer diagnostics: a stable identity (name#line) of the buffer the
    # diagnostic is about, so the report attributes it by symbol, not by name.
    subject: str | None = None

    @property
    def title(self) -> str:
        return TITLES.get(self.code, "")

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

    def render(self, filename: str = "<input>") -> str:
        """Plain one-line rendering: `file:line: severity: [code] message`."""
        return (
            f"{filename}:{self.line}: {self.severity.value}: "
            f"[{self.code}] {self.message}"
        )

    def render_pretty(self, filename: str, source: str) -> str:
        """A rustc-style rendering: a `file:line:col` header, the offending
        source line, and a caret under the named identifier. Falls back to the
        plain header when the line/column cannot be resolved."""
        lines = source.splitlines()
        src_line = lines[self.line - 1] if 1 <= self.line <= len(lines) else ""
        col = self._caret_col(src_line)
        loc = f"{filename}:{self.line}" + (f":{col}" if col else "")
        out = [f"{loc}: {self.severity.value}: [{self.code}] {self.message}"]
        if src_line.strip():
            gutter = f"  {self.line} | "
            out.append(f"{gutter}{src_line}")
            if col:
                out.append(" " * (len(gutter) + col - 1) + "^")
        return "\n".join(out)
