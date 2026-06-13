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

from dataclasses import dataclass
from enum import Enum


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
    # ---- unsupported ----
    "OWN020": "unsupported construct (out of scope for the MVP)",
    # ---- name resolution & structural ----
    "OWN030": "undefined name",
    "OWN031": "name already defined in this scope",
    "OWN032": "owned resource copied without 'move'",
    "OWN033": "function must return a value on all paths",
    "OWN034": "operation requires an owned resource",
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

    @property
    def title(self) -> str:
        return TITLES.get(self.code, "")

    def render(self, filename: str = "<input>") -> str:
        return (
            f"{filename}:{self.line}: {self.severity.value}: "
            f"[{self.code}] {self.message}"
        )
