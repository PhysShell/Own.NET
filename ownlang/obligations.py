"""Obligation-protocol analysis — project-specific temporal invariants (P-025).

A legacy method often breaks one of its *own* invariants on purpose, briefly:
`IsLoaded = false` while the document tree is rebuilt, `_suppressNotifications =
true` around a batch update, `BeginUpdate()` before a bulk edit. The invariant is
allowed to be false — *locally*. The bug is publishing that broken state to the
outside world: raising `PropertyChanged("Document")`, returning, or throwing
while the flag is still down. No general-purpose checker knows that `IsLoaded`
means "the document is consistent"; the project does.

This analyzer checks exactly that shape, declared per project as an **obligation
protocol**:

  - an *opening* event creates the obligation (`IsLoaded = false`);
  - a *closing* event discharges it (`IsLoaded = true`);
  - a *barrier* is a point the obligation must not cross while open — a
    configured call (`OnPropertyChanged("Document")`) or a method exit
    (`return` / `throw` / falling off the end).

Like `di.py` over the DI registration graph and `effects.py` over the
render-scope binding graph, this is its own small analysis the OwnIR bridge
feeds facts to — one checker, several analyses. The frontend (Roslyn extractor
or a hand-written fixture) only reports *what the method does*, as an ordered
event tree (`protocol_functions[]`); the protocol *rules* (`protocols[]`) are
project configuration; the verdict is decided here.

The walk is path-sensitive over the structured event tree (`if`/`while` mirror
the flow-op shape of OwnIR §5): the obligation state is a **set** over
{OPEN, CLOSED} joined by union at merges, so the definite/maybe split falls out
of the lattice exactly as it does for OWN002 vs OWN009 in the core. Loops are
solved to a local fixpoint silently and their bodies re-walked once on the
converged header state, so a barrier inside a loop reports once — the same
two-phase emission discipline as `analysis._Analyzer`.

Precision policy (the project's standing red line — never invent a violation):

  - an *opaque* write to a tracked flag (`IsLoaded = Compute()`) may discharge
    the obligation but never creates one: if OPEN is possible the state gains
    CLOSED (the write may have closed it), but a closed state stays closed;
  - a call the protocol does not name is neutral — it neither discharges nor
    crosses. A callee that flips the flag internally is invisible in v1
    (interprocedural obligation summaries are the P-025 phase-3 slice, on the
    MOS channel of `ownership.py`);
  - protocols are explicitly scoped (`scope.methods`) — a rule only ever fires
    where the project asked for it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# obligation state lattice: a set over {OPEN, CLOSED}, joined by union.
OPEN = "open"
CLOSED = "closed"

# the closed event vocabulary of `protocol_functions[].events` — the `ev`
# discriminator. Mirrors the flow-op rule (OwnIR §5): a present-but-unknown
# value is rejected, never skipped (spec/ownir.schema.json pins this set).
EVENT_KINDS = frozenset({"assign", "call", "return", "throw", "if", "while"})

# matcher vocabulary for `opens`/`closes`/`barriers`/`allow`.
MATCHER_KINDS = frozenset({"assign", "call"})


class ProtocolFactsError(ValueError):
    """A malformed protocol/event fact. `load()` wraps this in `OwnIRError`
    (fail-loud); the direct `check_facts` path skips the malformed entry
    (defensive, mirroring `_effect_findings`)."""


# ---------------------------------------------------------------------------
# rule side: matchers and protocols (`protocols[]`)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Matcher:
    """One event pattern. `kind` selects the shape:

    - `assign`: matches an assign event with the same `target`; `value`
      narrows to a specific written boolean (None = any value, including an
      opaque one).
    - `call`: matches a call event with the same `callee`; a non-empty `args`
      narrows to calls whose distinguished argument is in the set (a call
      with an *unknown* argument does not match a narrowed matcher — we do
      not invent a barrier crossing we cannot prove).
    """

    kind: str
    target: str = ""            # assign: member name; call: callee name
    value: bool | None = None   # assign only
    args: frozenset[str] = frozenset()  # call only

    def matches(self, ev: AssignEv | CallEv) -> bool:
        if self.kind == "assign" and isinstance(ev, AssignEv):
            if ev.target != self.target:
                return False
            return self.value is None or ev.value is self.value
        if self.kind == "call" and isinstance(ev, CallEv):
            if ev.callee != self.target:
                return False
            if not self.args:
                return True
            return ev.arg is not None and ev.arg in self.args
        return False

    def describe(self) -> str:
        """A stable, line-free human phrase for messages ('IsLoaded = true',
        'EndUpdate()')."""
        if self.kind == "assign":
            if self.value is None:
                return f"{self.target} = ..."
            return f"{self.target} = {str(self.value).lower()}"
        return f"{self.target}()"


@dataclass(frozen=True)
class Protocol:
    """One project-declared obligation protocol (see the module docstring)."""

    name: str
    opens: Matcher
    closes: Matcher
    barriers: tuple[Matcher, ...] = ()
    allow: tuple[Matcher, ...] = ()
    # `return` / `throw` / end-of-body are barriers too (the OWN001 shape:
    # an obligation may not leak out of the method).
    exit_barriers: bool = True
    # explicit scope: method names the protocol applies to (exact, or a
    # trailing `Type.Method` suffix so fixtures need not spell namespaces).
    # Empty = every method that reports events. Tight scoping is the false-
    # positive control: a rule only fires where the project asked.
    methods: tuple[str, ...] = ()
    description: str = ""

    def applies_to(self, fn_name: str) -> bool:
        if not self.methods:
            return True
        return any(fn_name == m or fn_name.endswith("." + m) for m in self.methods)

    def tracks_target(self, target: str) -> bool:
        """Is `target` one of the flags whose assigns drive this protocol?
        (Used for the opaque-write discharge rule.)"""
        return any(m.kind == "assign" and m.target == target
                   for m in (self.opens, self.closes))


# ---------------------------------------------------------------------------
# fact side: the ordered event tree (`protocol_functions[]`)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AssignEv:
    target: str
    value: bool | None  # None = opaque (the frontend saw a non-literal RHS)
    line: int


@dataclass(frozen=True)
class CallEv:
    callee: str
    arg: str | None  # the distinguished argument (nameof/string literal), if known
    line: int


@dataclass(frozen=True)
class ReturnEv:
    line: int


@dataclass(frozen=True)
class ThrowEv:
    line: int


@dataclass(frozen=True)
class IfEv:
    line: int
    then: tuple[Event, ...]
    orelse: tuple[Event, ...]


@dataclass(frozen=True)
class WhileEv:
    line: int
    body: tuple[Event, ...]


Event = AssignEv | CallEv | ReturnEv | ThrowEv | IfEv | WhileEv


@dataclass(frozen=True)
class MethodEvents:
    """One method's ordered event tree, as reported by a frontend."""

    name: str
    file: str
    events: tuple[Event, ...]


# ---------------------------------------------------------------------------
# parsing (shared by load()'s fail-loud gate and the defensive bridge path)
# ---------------------------------------------------------------------------

def _require_str(raw: dict[str, Any], key: str, ctx: str) -> str:
    v = raw.get(key)
    if not isinstance(v, str) or not v:
        raise ProtocolFactsError(f"{ctx}: '{key}' must be a non-empty string, got {v!r}")
    return v


def _opt_line(raw: dict[str, Any], ctx: str) -> int:
    v = raw.get("line", 0)
    if not isinstance(v, int) or isinstance(v, bool):
        raise ProtocolFactsError(f"{ctx}: 'line' must be an integer, got {v!r}")
    return v


def parse_matcher(raw: Any, ctx: str, require_value: bool = False) -> Matcher:
    """Parse one matcher object. `require_value` is set for `opens`/`closes`
    assign matchers: an open/close condition must name the written boolean —
    'any write opens' is not a checkable protocol."""
    if not isinstance(raw, dict):
        raise ProtocolFactsError(f"{ctx} must be an object, got {raw!r}")
    kind = raw.get("kind")
    if kind not in MATCHER_KINDS:
        raise ProtocolFactsError(
            f"{ctx}: unknown matcher kind {kind!r} — the vocabulary is "
            f"{sorted(MATCHER_KINDS)} (spec/OwnIR.md §8)")
    if kind == "assign":
        target = _require_str(raw, "target", ctx)
        value = raw.get("value")
        if value is not None and not isinstance(value, bool):
            raise ProtocolFactsError(
                f"{ctx}: assign 'value' must be a boolean, got {value!r}")
        if require_value and value is None:
            raise ProtocolFactsError(
                f"{ctx}: an opens/closes assign matcher must state the written "
                f"boolean 'value' — 'any write' cannot open or close an obligation")
        return Matcher(kind="assign", target=target, value=value)
    callee = _require_str(raw, "callee", ctx)
    args_raw = raw.get("args", [])
    if not isinstance(args_raw, list) or not all(isinstance(a, str) for a in args_raw):
        raise ProtocolFactsError(f"{ctx}: call 'args' must be an array of strings")
    return Matcher(kind="call", target=callee, args=frozenset(args_raw))


def parse_protocol(raw: Any) -> Protocol:
    """Parse one `protocols[]` entry, fail-loud on any shape violation."""
    if not isinstance(raw, dict):
        raise ProtocolFactsError(f"a protocol must be an object, got {raw!r}")
    name = _require_str(raw, "name", "protocol")
    ctx = f"protocol '{name}'"
    if "opens" not in raw or "closes" not in raw:
        raise ProtocolFactsError(f"{ctx}: 'opens' and 'closes' are both required")
    opens = parse_matcher(raw["opens"], f"{ctx} 'opens'", require_value=True)
    closes = parse_matcher(raw["closes"], f"{ctx} 'closes'", require_value=True)
    barriers_raw = raw.get("barriers", [])
    if not isinstance(barriers_raw, list):
        raise ProtocolFactsError(f"{ctx}: 'barriers' must be an array")
    barriers = tuple(parse_matcher(b, f"{ctx} barrier") for b in barriers_raw)
    allow_raw = raw.get("allow", [])
    if not isinstance(allow_raw, list):
        raise ProtocolFactsError(f"{ctx}: 'allow' must be an array")
    allow = tuple(parse_matcher(a, f"{ctx} allow") for a in allow_raw)
    exit_barriers = raw.get("exit_barriers", True)
    if not isinstance(exit_barriers, bool):
        raise ProtocolFactsError(f"{ctx}: 'exit_barriers' must be a boolean")
    if not barriers and not exit_barriers:
        raise ProtocolFactsError(
            f"{ctx}: no barriers and exit_barriers is false — the protocol can "
            f"never fire (a rule that structurally never fires is decoration)")
    if opens in barriers:
        # the walk checks opens before barriers, so this barrier is silently
        # dead — the same never-fires rule as above. (A barrier equal to
        # `closes` is merely redundant: the close discharges at that point,
        # which is exactly what the barrier asks for.) Re-entrancy rules
        # ("BeginUpdate while already updating") are a later feature, not a
        # silently ignored config.
        raise ProtocolFactsError(
            f"{ctx}: a barrier equals the 'opens' matcher — the open wins and "
            f"the barrier can never fire (re-entrancy checks are not "
            f"supported yet)")
    scope = raw.get("scope", {})
    if not isinstance(scope, dict):
        raise ProtocolFactsError(f"{ctx}: 'scope' must be an object")
    methods_raw = scope.get("methods", [])
    if not isinstance(methods_raw, list) or not all(
            isinstance(m, str) and m for m in methods_raw):
        raise ProtocolFactsError(
            f"{ctx}: 'scope.methods' must be an array of non-empty strings")
    desc = raw.get("description", "")
    if not isinstance(desc, str):
        raise ProtocolFactsError(f"{ctx}: 'description' must be a string")
    return Protocol(name=name, opens=opens, closes=closes, barriers=barriers,
                    allow=allow, exit_barriers=exit_barriers,
                    methods=tuple(methods_raw), description=desc)


def parse_events(raw: Any, ctx: str) -> tuple[Event, ...]:
    """Parse an ordered event list (recursive over `if`/`while`), fail-loud on
    an unknown `ev` — the same rule as an unknown flow op (OwnIR IR4)."""
    if not isinstance(raw, list):
        raise ProtocolFactsError(f"{ctx}: events must be an array, got {raw!r}")
    out: list[Event] = []
    for e in raw:
        if not isinstance(e, dict):
            raise ProtocolFactsError(f"{ctx}: each event must be an object, got {e!r}")
        ev = e.get("ev")
        if ev not in EVENT_KINDS:
            raise ProtocolFactsError(
                f"{ctx}: unknown protocol event {ev!r} — the vocabulary is "
                f"{sorted(EVENT_KINDS)} (spec/OwnIR.md §8)")
        line = _opt_line(e, ctx)
        if ev == "assign":
            target = _require_str(e, "target", f"{ctx} assign")
            value = e.get("value")
            if value is not None and not isinstance(value, bool):
                raise ProtocolFactsError(
                    f"{ctx}: assign 'value' must be a boolean or absent "
                    f"(absent = opaque write), got {value!r}")
            out.append(AssignEv(target=target, value=value, line=line))
        elif ev == "call":
            callee = _require_str(e, "callee", f"{ctx} call")
            arg = e.get("arg")
            if arg is not None and not isinstance(arg, str):
                raise ProtocolFactsError(
                    f"{ctx}: call 'arg' must be a string or absent, got {arg!r}")
            out.append(CallEv(callee=callee, arg=arg, line=line))
        elif ev == "return":
            out.append(ReturnEv(line=line))
        elif ev == "throw":
            out.append(ThrowEv(line=line))
        elif ev == "if":
            out.append(IfEv(line=line,
                            then=parse_events(e.get("then", []), ctx),
                            orelse=parse_events(e.get("else", []), ctx)))
        else:  # "while" — EVENT_KINDS is closed, checked above
            out.append(WhileEv(line=line, body=parse_events(e.get("body", []), ctx)))
    return tuple(out)


def parse_method(raw: Any) -> MethodEvents:
    """Parse one `protocol_functions[]` entry."""
    if not isinstance(raw, dict):
        raise ProtocolFactsError(f"a protocol function must be an object, got {raw!r}")
    name = _require_str(raw, "name", "protocol function")
    file = raw.get("file", "?")
    if not isinstance(file, str):
        raise ProtocolFactsError(f"protocol function '{name}': 'file' must be a string")
    events = parse_events(raw.get("events", []), f"protocol function '{name}'")
    return MethodEvents(name=name, file=file, events=events)


# ---------------------------------------------------------------------------
# the checker
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Violation:
    """One obligation-protocol violation, ready for the bridge to phrase.

    `line` anchors where the violation manifests: the barrier site for a
    `barrier`/`return`/`throw` crossing, the *open* site for an obligation
    leaking off the end of the method (the OWN001 precedent: a leak anchors at
    the acquire). `definite` is the lattice split: True when the obligation is
    open on *every* path reaching the point, False when only on some path.
    `close_line` is the earliest close site after `line`, if one exists — the
    "closed only here, after the barrier" evidence hop."""

    protocol: str
    method: str
    file: str
    line: int
    kind: str            # "barrier" | "exit"
    definite: bool
    open_line: int
    barrier_desc: str    # "OnPropertyChanged(Document)" | "return" | "throw" | "end of method"
    close_line: int | None = None


# a path state: which obligation states are possible, plus the earliest open
# site among the paths where it is open (evidence provenance, min-line joined
# like analysis._join_sites).
_State = tuple[frozenset[str], int | None]

_BOTTOM: _State = (frozenset(), None)


def _join(a: _State, b: _State) -> _State:
    states = a[0] | b[0]
    lines = [ln for ln in (a[1], b[1]) if ln is not None]
    return (states, min(lines) if lines else None)


class _Walker:
    """Path-sensitive walk of one method's event tree against one protocol.

    Sequences and branches are walked exactly once (the emitting pass); a loop
    body is iterated to a fixpoint with emission off, then re-walked once on
    the converged header state — the two-phase discipline of the core
    analyzer, applied per loop."""

    def __init__(self, proto: Protocol, method: MethodEvents) -> None:
        self.proto = proto
        self.method = method
        self.silent = False
        self.violations: list[Violation] = []

    # -- event handling ----------------------------------------------------

    def _emit(self, kind: str, line: int, st: _State, desc: str) -> None:
        if self.silent:
            return
        states, open_line = st
        self.violations.append(Violation(
            protocol=self.proto.name, method=self.method.name,
            file=self.method.file, line=line, kind=kind,
            definite=(states == frozenset({OPEN})),
            open_line=open_line if open_line is not None else line,
            barrier_desc=desc))

    def _leaf(self, ev: AssignEv | CallEv, st: _State) -> _State:
        p = self.proto
        if p.opens.matches(ev):
            # (re-)open: keep the earliest open site as provenance.
            prev = st[1]
            return (frozenset({OPEN}),
                    ev.line if prev is None else min(prev, ev.line))
        if p.closes.matches(ev):
            return (frozenset({CLOSED}), None)
        states, open_line = st
        if OPEN in states:
            # allow beats barrier: an explicitly safe event never crosses.
            if not any(a.matches(ev) for a in p.allow):
                for b in p.barriers:
                    if b.matches(ev):
                        desc = (f"{ev.callee}({ev.arg or ''})"
                                if isinstance(ev, CallEv) else ev.target + " = ...")
                        self._emit("barrier", ev.line, st, desc)
                        break
            # opaque write to a tracked flag: may discharge, never opens
            # (the never-invent asymmetry — see the module docstring).
            if (isinstance(ev, AssignEv) and ev.value is None
                    and p.tracks_target(ev.target)):
                return (states | {CLOSED}, open_line)
        return st

    def _exit(self, line: int, st: _State, desc: str) -> None:
        if self.proto.exit_barriers and OPEN in st[0]:
            self._emit("exit", line, st, desc)

    # -- tree walk -----------------------------------------------------------

    def walk_seq(self, events: tuple[Event, ...], st: _State) -> tuple[_State, bool]:
        """Returns (state, alive): alive is False when every path through the
        sequence has already left the method."""
        alive = True
        for ev in events:
            st, alive = self.walk(ev, st)
            if not alive:
                break
        return st, alive

    def walk(self, ev: Event, st: _State) -> tuple[_State, bool]:
        if isinstance(ev, (AssignEv, CallEv)):
            return self._leaf(ev, st), True
        if isinstance(ev, ReturnEv):
            self._exit(ev.line, st, "return")
            return _BOTTOM, False
        if isinstance(ev, ThrowEv):
            self._exit(ev.line, st, "throw")
            return _BOTTOM, False
        if isinstance(ev, IfEv):
            s1, a1 = self.walk_seq(ev.then, st)
            s2, a2 = self.walk_seq(ev.orelse, st)
            if not a1 and not a2:
                return _BOTTOM, False
            merged = _join(s1 if a1 else _BOTTOM, s2 if a2 else _BOTTOM)
            return merged, True
        if isinstance(ev, WhileEv):
            # local fixpoint on the header state, silently (finite lattice:
            # states only grow under union, so this terminates).
            header = st
            was_silent = self.silent
            self.silent = True
            while True:
                out, body_alive = self.walk_seq(ev.body, header)
                nxt = _join(header, out if body_alive else _BOTTOM)
                if nxt == header:
                    break
                header = nxt
            self.silent = was_silent
            # one emitting pass over the body on the converged header state
            # (skipped when an enclosing loop is still in its silent phase).
            if not self.silent:
                self.walk_seq(ev.body, header)
            # zero iterations are always possible: the exit state is the header.
            return header, True
        raise AssertionError(f"unhandled protocol event {ev!r}")

    def run(self) -> list[Violation]:
        st, alive = self.walk_seq(self.method.events, (frozenset({CLOSED}), None))
        if alive:
            states, open_line = st
            if self.proto.exit_barriers and OPEN in states:
                # anchor the leak at the open site (the OWN001 precedent).
                anchor = open_line if open_line is not None else 0
                self._emit("exit", anchor, st, "end of method")
        return self.violations


def _close_lines(proto: Protocol, events: tuple[Event, ...]) -> list[int]:
    """Every close-event line in the tree, reachability ignored — evidence for
    the 'closed only here, after the barrier' hop."""
    out: list[int] = []
    for ev in events:
        if isinstance(ev, (AssignEv, CallEv)):
            if proto.closes.matches(ev):
                out.append(ev.line)
        elif isinstance(ev, IfEv):
            out.extend(_close_lines(proto, ev.then))
            out.extend(_close_lines(proto, ev.orelse))
        elif isinstance(ev, WhileEv):
            out.extend(_close_lines(proto, ev.body))
    return out


def check_protocols(protocols: list[Protocol],
                    methods: list[MethodEvents]) -> list[Violation]:
    """Check every protocol against every method in its scope. Deterministic;
    sorted by location."""
    out: list[Violation] = []
    for proto in protocols:
        for method in methods:
            if not proto.applies_to(method.name):
                continue
            violations = _Walker(proto, method).run()
            if violations:
                closes = sorted(_close_lines(proto, method.events))
                for v in violations:
                    # the late-close evidence hop only makes sense for a
                    # barrier crossing ("the close exists, but after the
                    # publish"); an exit leak has no barrier to be late for.
                    late = (next((c for c in closes if c > v.line), None)
                            if v.kind == "barrier" else None)
                    if late is not None:
                        v = Violation(
                            protocol=v.protocol, method=v.method, file=v.file,
                            line=v.line, kind=v.kind, definite=v.definite,
                            open_line=v.open_line, barrier_desc=v.barrier_desc,
                            close_line=late)
                    out.append(v)
    out.sort(key=lambda v: (v.file, v.line, v.protocol, v.barrier_desc))
    return out


def unmatched_scopes(protocols: list[Protocol],
                     methods: list[MethodEvents]) -> list[Protocol]:
    """Protocols whose scope matched no reported method — a dead rule (likely a
    typo'd scope). Surfaced as an advisory, never a verdict: a rule that
    structurally never fires is decoration, and silently dead project rules are
    worse than none."""
    return [p for p in protocols
            if p.methods and not any(p.applies_to(m.name) for m in methods)]
