"""
Buffer storage policies — the stackalloc / scratch / pool / native line.

A *buffer* is an owned resource (it is checked for release-exactly-once, escape,
and borrow conflicts just like any `acquire`d resource), but it additionally
carries an explicit **storage policy**. The policy is something the user states
as an intent; the checker proves the lifetime/ownership rules; the backend either
chooses or strictly honours the storage; codegen emits safe C#; and — the part
that matters — the choice is *logged* so nobody has to guess whether a "stack"
buffer quietly went to the heap.

Modes (intent the user writes as `Buffer.<mode>(...)`):

  stack(N) / stack(size, max = M)
      stack only. fallback to the heap is FORBIDDEN. cannot escape. the bound
      must be statically known (a literal, or a `max =` guard for a dynamic size).

  scratch(size, inline = L, fallback = pool)
      prefer the stack; fall back to ArrayPool when the request exceeds the
      inline limit. local-only (may be stack-backed, so it cannot escape).

  pooled(size)
      ArrayPool only. a movable owned resource (it may escape via consume/return).
      Return is mandatory — enforced by the ownership checker.

  native(size)
      unmanaged memory via NativeMemory. an unsafe owned resource. Free is
      mandatory. movable.

  inline(N)
      a fixed compile-time stack buffer. the most predictable mode. cannot escape.

The single rule the whole design rests on: `stack` never falls into the heap;
`scratch` may, because the user explicitly allowed it. An API that lies about
where memory lives is not an abstraction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from . import ast_nodes as A
from .diagnostics import Diagnostic


class BufferMode(Enum):
    STACK = "stack"
    SCRATCH = "scratch"
    POOLED = "pooled"
    NATIVE = "native"
    INLINE = "inline"


MODE_NAMES = {m.value for m in BufferMode}

# Recognized named options on a buffer intent, and recognized keys in a policy
# block. An unknown name (a typo like `fallbak`) must be rejected, not silently
# ignored — otherwise a misspelled `fallback = forbidden` quietly defaults to the
# heap, defeating the explicit storage guarantee.
VALID_OPTIONS = frozenset({
    "policy", "inline", "inline_bytes", "max", "max_bytes",
    "fallback", "clear", "trace", "counters", "sensitive",
})
VALID_POLICY_KEYS = frozenset({
    "inline_bytes", "max_bytes", "fallback", "clear_on_release",
    "trace", "counters", "sensitive",
})

# Modes whose backing storage may live on the stack. A stack-backed buffer must
# not escape the function: it would be a dangling span the instant the frame
# pops. `scratch` is included because at runtime it *might* be the stack arm.
STACK_BACKED = {BufferMode.STACK, BufferMode.SCRATCH, BufferMode.INLINE}

# Default inline limit for scratch when the user omits `inline =`.
DEFAULT_INLINE_BYTES = 1024

# Hard ceiling on how many bytes a stack-backed mode may reserve on the frame.
# Past this you are not optimising, you are inviting a stack overflow. Tunable.
MAX_STACK_BYTES = 4096


@dataclass
class BufferInfo:
    """Resolved, validated metadata for one buffer intent. Attached to the
    owning Symbol and to the AcquireBuffer instruction, and read by codegen and
    the report writer. Resolution is total: by the time this exists, any policy
    contradiction has already been turned into a diagnostic."""
    mode: BufferMode
    elem: str                      # element type, e.g. "byte"
    # size: exactly one of const / var is set (or both None for a no-arg mode)
    size_const: int | None
    size_var: str | None
    inline_bytes: int              # inline capacity / stack bound, in elements
    fallback_pool: bool            # scratch: heap fallback allowed
    fallback_forbidden: bool       # stack: heap fallback explicitly forbidden
    clear_on_release: bool         # zero the bytes before returning/releasing
    sensitive: bool                # holds secret data: must be cleared on release
    trace: bool                    # emit OwnTrace hooks
    counters: bool                 # emit OwnCounters hooks
    policy_name: str | None
    line: int

    @property
    def stack_backed(self) -> bool:
        return self.mode in STACK_BACKED

    @property
    def size_is_const(self) -> bool:
        return self.size_const is not None

    @property
    def escape_policy(self) -> str:
        return "local-only" if self.stack_backed else "movable"

    def branches(self) -> list[dict]:
        """The runtime backend branches, for the compile-time report."""
        if self.mode == BufferMode.SCRATCH and self.fallback_pool:
            return [
                {"condition": f"size <= {self.inline_bytes}", "backend": "stackalloc"},
                {"condition": f"size > {self.inline_bytes}", "backend": "ArrayPool"},
            ]
        if self.mode in (BufferMode.STACK, BufferMode.INLINE) or (
                self.mode == BufferMode.SCRATCH and not self.fallback_pool):
            # a scratch that forbids the heap fallback is, at runtime, stack-only;
            # the report must not advertise an ArrayPool branch that cannot occur.
            return [{"condition": "always", "backend": "stackalloc"}]
        if self.mode == BufferMode.POOLED:
            return [{"condition": "always", "backend": "ArrayPool"}]
        return [{"condition": "always", "backend": "NativeMemory"}]


@dataclass
class Policy:
    """A named, reusable `policy { ... }` block of defaults."""
    name: str
    settings: dict[str, object] = field(default_factory=dict)
    line: int = 0
    dups: tuple = ()   # setting keys that appeared more than once


# --------------------------------------------------------------------------
# Option parsing helpers (turn raw AST option values into Python values)
# --------------------------------------------------------------------------


def _as_int(expr) -> int | None:
    return expr.value if isinstance(expr, A.IntLit) else None


def _as_ident(expr) -> str | None:
    return expr.name if isinstance(expr, A.VarRef) else None


# --------------------------------------------------------------------------
# Resolution: intent + policies -> validated BufferInfo + diagnostics
# --------------------------------------------------------------------------


def validate_policies(policies: dict[str, Policy]) -> list[Diagnostic]:
    """Reject unknown keys in `policy` blocks (a typo like `fallbak` must not be
    silently ignored). Reported once, at the policy's declaration."""
    diags: list[Diagnostic] = []
    for pol in policies.values():
        for key in pol.settings:
            if key not in VALID_POLICY_KEYS:
                diags.append(Diagnostic(
                    "OWN030",
                    f"unknown policy setting '{key}' in policy '{pol.name}'; "
                    f"expected one of {', '.join(sorted(VALID_POLICY_KEYS))}",
                    pol.line))
        for key in pol.dups:
            diags.append(Diagnostic(
                "OWN030",
                f"duplicate policy setting '{key}' in policy '{pol.name}'",
                pol.line))
    return diags


def resolve(intent: "A.BufferIntent", policies: dict[str, Policy]
            ) -> tuple[BufferInfo, list[Diagnostic]]:
    """Resolve one buffer intent against the available policies. Returns the
    metadata plus any policy/bound diagnostics (OWN019/021/023). Always returns
    a usable BufferInfo so later stages have something to lower."""
    diags: list[Diagnostic] = []
    line = intent.line

    mode = BufferMode(intent.mode)
    opts = dict(intent.options)

    # reject misspelled / unknown option names before any defaults are applied,
    # so e.g. `fallbak = forbidden` cannot silently fall back to the pool.
    for key in intent.options:
        if key not in VALID_OPTIONS:
            diags.append(Diagnostic(
                "OWN030",
                f"unknown buffer option '{key}'; expected one of "
                f"{', '.join(sorted(VALID_OPTIONS))}", line))
    # a repeated option (e.g. fallback = forbidden, fallback = pool) is a
    # conflicting storage promise; reject it instead of letting the last win.
    for key in intent.dups:
        diags.append(Diagnostic(
            "OWN030", f"duplicate buffer option '{key}'", line))

    # Start from a referenced policy's defaults, then let inline options win.
    base: dict[str, object] = {}
    pol_name: str | None = None
    pol_expr = opts.pop("policy", None)
    if pol_expr is not None:
        pol_name = _as_ident(pol_expr)
        if pol_name is None:
            # present but not a policy name (e.g. policy = 0): never fall through
            # to defaults silently — that could bypass an intended policy.
            diags.append(Diagnostic(
                "OWN030",
                f"invalid policy reference '{_fallback_token(pol_expr)}'; "
                f"expected a policy name", line))
        elif pol_name in policies:
            base = dict(policies[pol_name].settings)
        else:
            diags.append(Diagnostic(
                "OWN030", f"undefined policy '{pol_name}'", line))

    def opt_int(name: str, default: int) -> int:
        # present-but-not-an-integer (e.g. inline = bogus) must fail safe and
        # diagnose, not silently fall through to the default and change the policy.
        if name in opts:
            v = _as_int(opts[name])
            if v is not None:
                return v
            diags.append(Diagnostic(
                "OWN030",
                f"invalid '{name}' value '{_fallback_token(opts[name])}'; "
                f"expected an integer", line))
            return default
        if name in base:
            bv = base[name]
            if isinstance(bv, int) and not isinstance(bv, bool):
                return bv
            diags.append(Diagnostic(
                "OWN030",
                f"invalid '{name}' value '{bv}' in policy; expected an integer",
                line))
            return default
        return default

    def first_int(sources: list[tuple[bool, str]], label: str,
                  default: int) -> int:
        """First *present* source, in priority order, as an integer. Only that
        source is validated/diagnosed — lower-priority sources are ignored once a
        higher-priority one is present, so an inline option overrides a policy
        default even when the (now-irrelevant) policy value is malformed."""
        for from_opts, key in sources:
            container = opts if from_opts else base
            if key not in container:
                continue
            raw = container[key]
            v = (_as_int(raw) if from_opts
                 else (raw if isinstance(raw, int) and not isinstance(raw, bool)
                       else None))
            if v is not None:
                return v
            where = "" if from_opts else " in policy"
            diags.append(Diagnostic(
                "OWN030",
                f"invalid '{label}' value '{_fallback_token(raw)}'{where}; "
                f"expected an integer", line))
            return default
        return default

    # ---- size --------------------------------------------------------------
    size_const = _as_int(intent.size) if intent.size is not None else None
    size_var = _as_ident(intent.size) if intent.size is not None else None

    # ---- per-mode resolution ----------------------------------------------
    inline_bytes = DEFAULT_INLINE_BYTES
    fallback_pool = False
    fallback_forbidden = False

    if mode in (BufferMode.STACK, BufferMode.INLINE):
        fallback_forbidden = True
        if size_const is not None:
            inline_bytes = size_const
        elif mode == BufferMode.INLINE:
            # inline is a fixed compile-time stack buffer: the size MUST be an
            # integer literal. A dynamic size (even with `max`) is `stack`, not
            # `inline`.
            diags.append(Diagnostic(
                "OWN021",
                "'inline' buffer requires a compile-time integer literal size; "
                "use 'stack' with a 'max =' bound for a dynamic size", line))
            inline_bytes = MAX_STACK_BYTES
        else:
            # dynamic size: needs an explicit, integer max bound.
            inline_bytes = MAX_STACK_BYTES  # safe default while we validate
            if "max" in opts and _as_int(opts["max"]) is None:
                diags.append(Diagnostic(
                    "OWN030",
                    f"invalid 'max' value '{_fallback_token(opts['max'])}'; "
                    f"expected an integer", line))
            else:
                mx_val = (_as_int(opts["max"]) if "max" in opts
                          else opt_int("max_bytes", -1))
                if mx_val < 0:
                    diags.append(Diagnostic(
                        "OWN021",
                        f"'{mode.value}' allocation of a dynamic size requires a "
                        f"statically known bound (add 'max = N')", line))
                else:
                    inline_bytes = mx_val

    elif mode == BufferMode.SCRATCH:
        inline_bytes = first_int(
            [(True, "inline"), (True, "inline_bytes"), (False, "inline_bytes")],
            "inline", DEFAULT_INLINE_BYTES)
        # distinguish "absent" (default to pool) from "present but malformed".
        # A present-but-malformed value — a string typo (`forbiden`) OR a
        # non-identifier (`fallback = 0`) — must fail safe and diagnose, never
        # silently fall through to enabling the heap.
        fb_present = "fallback" in opts or "fallback" in base
        if fb_present:
            raw = opts["fallback"] if "fallback" in opts else base["fallback"]
            fb = _fallback_token(raw)
        else:
            fb = "pool"  # scratch defaults to a pool fallback
        fb_valid = fb in ("pool", "forbidden")
        if fb_present and not fb_valid:
            diags.append(Diagnostic(
                "OWN030",
                f"invalid fallback '{fb}' for scratch buffer; expected 'pool' "
                f"or 'forbidden'", line))
        if fb == "pool":
            fallback_pool = True
        else:
            # 'forbidden', or an invalid value handled fail-safe (no heap)
            fallback_forbidden = True
            # scratch with no heap fallback and a size that may exceed the inline
            # limit cannot honour the "stack only" promise.
            if fb_valid and (size_const is None or size_const > inline_bytes):
                diags.append(Diagnostic(
                    "OWN023",
                    f"scratch buffer forbids a heap fallback but its size may "
                    f"exceed the inline limit of {inline_bytes}; use 'stack' "
                    f"with a 'max =' bound instead", line))

    elif mode == BufferMode.POOLED:
        fallback_pool = True

    # native: heap-via-unmanaged, nothing extra to resolve here.

    # ---- shared bound check on stack-backed modes -------------------------
    if mode in STACK_BACKED and inline_bytes > MAX_STACK_BYTES:
        diags.append(Diagnostic(
            "OWN019",
            f"inline capacity {inline_bytes} bytes is too large for a "
            f"stack-backed buffer (limit {MAX_STACK_BYTES}); use 'pooled' or "
            f"raise the policy ceiling deliberately", line))

    # ---- flags from options / policy --------------------------------------
    clear = _bool_flag(opts.get("clear"), base.get("clear_on_release"),
                       False, "clear_on_release", diags, line)
    sensitive = _bool_flag(opts.get("sensitive"), base.get("sensitive"),
                           False, "sensitive", diags, line)
    trace = _trace_flag(opts.get("trace"), base.get("trace"), True, diags, line)
    counters = _bool_flag(opts.get("counters"), base.get("counters"),
                          True, "counters", diags, line)

    # A buffer marked sensitive must be zeroed before its backing memory can be
    # observed again — pooled/scratch arrays go back to a shared ArrayPool, native
    # memory is handed back to the allocator, and even a stack frame is reused by
    # the next call. Marking it sensitive without clearing is the silent leak the
    # flag exists to prevent, so require an explicit `clear = true`.
    if sensitive and not clear:
        diags.append(Diagnostic(
            "OWN024",
            "buffer is marked sensitive but is not cleared on release; add "
            "'clear = true' so its bytes are zeroed before the backing memory "
            "is reused", line))

    info = BufferInfo(
        mode=mode,
        elem="byte",
        size_const=size_const,
        size_var=size_var,
        inline_bytes=inline_bytes,
        fallback_pool=fallback_pool,
        fallback_forbidden=fallback_forbidden,
        clear_on_release=clear,
        sensitive=sensitive,
        trace=trace,
        counters=counters,
        policy_name=pol_name,
        line=line,
    )
    return info, diags


def _fallback_token(v) -> str:
    """Render a fallback value (an AST expr from an inline option, or a Python
    value from a policy) as a display token for validation/diagnostics."""
    if isinstance(v, A.IntLit):
        return str(v.value)
    if isinstance(v, A.VarRef):
        return v.name
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _bool_flag(opt_expr, policy_val, default: bool, label: str,
               diags, line: int) -> bool:
    # a malformed boolean (a typo like `ture`, or any non-bool) must be rejected,
    # not silently treated as the default — for a sensitive buffer that would
    # quietly turn off clear-on-release.
    if opt_expr is not None:
        name = _as_ident(opt_expr)
        if name == "true":
            return True
        if name == "false":
            return False
        diags.append(Diagnostic(
            "OWN030",
            f"invalid '{label}' value '{_fallback_token(opt_expr)}'; "
            f"expected true or false", line))
        return default
    if policy_val is not None:
        if isinstance(policy_val, bool):
            return policy_val
        diags.append(Diagnostic(
            "OWN030",
            f"invalid '{label}' value '{policy_val}' in policy; expected true "
            f"or false", line))
        return default
    return default


_TRACE_ON = ("debug", "on", "true")
_TRACE_OFF = ("off", "none", "false")


def _trace_flag(opt_expr, policy_val, default: bool, diags, line: int) -> bool:
    # `trace = debug` / `trace = off` / `trace = false`; on/off/none/true/false
    # toggle the (Conditional) hooks. A malformed value is rejected, not assumed
    # on. An inline option wins over the policy value.
    if opt_expr is not None:
        name = _as_ident(opt_expr)
        if name in _TRACE_ON:
            return True
        if name in _TRACE_OFF:
            return False
        diags.append(Diagnostic(
            "OWN030",
            f"invalid 'trace' value '{_fallback_token(opt_expr)}'; expected one "
            f"of debug/on/off/none/true/false", line))
        return default
    if policy_val is not None:
        if isinstance(policy_val, bool):
            return policy_val
        if policy_val in _TRACE_ON:
            return True
        if policy_val in _TRACE_OFF:
            return False
        diags.append(Diagnostic(
            "OWN030",
            f"invalid 'trace' value '{policy_val}' in policy; expected one of "
            f"debug/on/off/none/true/false", line))
        return default
    return default
