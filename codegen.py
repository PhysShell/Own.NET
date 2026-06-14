"""
C# code generator for OwnLang.

Two modes, chosen automatically per function:

* **try/finally hoist** — when a function has no branches, no `move`, and no
  owned `return`, every owned resource is acquired and released exactly once.
  We lower it to the textbook exception-safe pattern: acquire, `try { ... }`,
  `finally { release }`, nested for multiple resources. The checker has already
  proven release-exactly-once; the `finally` additionally makes it hold across
  C# exceptions. Note we do NOT emit a runtime "released?" flag: because the
  release is hoisted *out* of the `try` (it is not also in the body), it runs
  exactly once with no guard needed. A runtime flag would only make sense if we
  didn't trust the static result — and if we don't trust it, we shouldn't ship.

* **faithful inline** — for functions with branches or ownership transfer,
  releases are emitted inline exactly where the source put them. Hoisting
  releases out of arbitrary control flow into `finally` is real work, flagged as
  a next step in the README rather than faked.

Resource lowering: if a `resource` declares `emit_type` / `emit_acquire` /
`emit_release` / `emit_borrow` templates, those produce REAL .NET (e.g.
`ArrayPool<byte>.Shared.Rent/Return`, `byte[]`, `.AsSpan()`). Otherwise the
schematic `Resource.method()` form is used, with method names taken from the
declaration. `extern fn` calls lower to `Name(args)`; a borrow binding renders
as its C# local (the span / ref), an owned argument as its variable.
"""

from __future__ import annotations

from . import ast_nodes as A
from .buffers import BufferMode, Policy, resolve as resolve_buffer


class CodegenError(Exception):
    pass


def _csharp_type(t: A.TypeRef) -> str:
    base = {"int": "int", "bool": "bool"}.get(t.name, t.name)
    if t.borrowed:
        return ("ref " if t.mutable else "ref readonly ") + base
    return base


class _FnGen:
    def __init__(self, mod: A.Module, fn: A.FnDecl):
        self.mod = mod
        self.fn = fn
        self.res = {r.name: r for r in mod.resources}
        self.policies: dict[str, Policy] = {
            p.name: Policy(p.name, dict(p.settings), p.line) for p in mod.policies
        }
        self.owned_resource: dict[str, str] = {}
        # borrow binding name -> owner resource type (so calls know the C# view)
        self.binding_owner_res: dict[str, str] = {}
        # buffer local name -> resolved BufferInfo (so borrows/args render right)
        self.buffer_vars: dict[str, object] = {}
        # buffer local name -> cleanup lines, for buffers whose `release` is
        # nested in branches (emitted at each release site, not in a finally)
        self.buffer_cleanup: dict[str, list[str]] = {}
        for p in fn.params:
            if not p.type.borrowed and p.type.name in self.res:
                self.owned_resource[p.name] = p.type.name

    # -- shape detection ----------------------------------------------------

    def _is_simple(self) -> bool:
        # Buffers always take the inline path: their stackalloc/pool prelude and
        # try/finally are emitted per-buffer, not by the straight-line hoister.
        if _fn_has_buffer(self.fn.body):
            return False
        return not _contains_branch_or_transfer(self.fn.body)

    # -- emit ---------------------------------------------------------------

    def emit(self) -> str:
        ret = _csharp_type(self.fn.ret) if self.fn.ret else "void"
        params = ", ".join(f"{_csharp_type(p.type)} {p.name}" for p in self.fn.params)
        # a function that allocates a native buffer needs pointers, so the whole
        # method is `unsafe` (cleaner than scoping each pointer in its own block,
        # and it lets native buffers follow the same lifetime shapes as the rest).
        unsafe = "unsafe " if _fn_has_native(self.fn.body) else ""
        head = f"public static {unsafe}{ret} {self.fn.name}({params})"
        if self._is_simple():
            body = self._emit_simple(self.fn.body)
        else:
            body = self._emit_inline(self.fn.body, indent=1)
        return f"{head}\n{{\n{body}}}\n"

    # -- simple (try/finally hoist) ----------------------------------------

    def _emit_simple(self, stmts: list[A.Stmt]) -> str:
        acquired: list[tuple[str, str, str]] = []  # (var, resource, args_csv)
        other: list[A.Stmt] = []
        for st in stmts:
            if isinstance(st, A.Let) and isinstance(st.rhs, A.Acquire):
                rt = st.rhs.resource
                self.owned_resource[st.name] = rt
                args_csv = ", ".join(self._arg(x) for x in st.rhs.args)
                acquired.append((st.name, rt, args_csv))
            elif isinstance(st, A.Release):
                pass  # consumed by the finally
            else:
                other.append(st)

        lines: list[str] = []
        ind = "    "

        def open_resource(idx: int, base: str) -> None:
            var, rt, args_csv = acquired[idx]
            lines.append(f"{base}{self._local_type(rt)} {var} = {self._acquire_expr(rt, args_csv)};")
            lines.append(f"{base}try")
            lines.append(f"{base}{{")
            inner = base + ind
            if idx + 1 < len(acquired):
                open_resource(idx + 1, inner)
            else:
                for st in other:
                    lines.extend(self._stmt_inline(st, inner))
            lines.append(f"{base}}}")
            lines.append(f"{base}finally")
            lines.append(f"{base}{{")
            lines.append(f"{base}{ind}{self._release_stmt(var, rt)}")
            lines.append(f"{base}}}")

        if acquired:
            open_resource(0, ind)
        else:
            for st in other:
                lines.extend(self._stmt_inline(st, ind))
        return "".join(l + "\n" for l in lines)

    # -- faithful inline ----------------------------------------------------

    def _emit_inline(self, stmts: list[A.Stmt], indent: int) -> str:
        ind = "    " * indent
        out = self._emit_block(stmts, ind)
        return "".join(l + "\n" for l in out)

    def _emit_block(self, stmts: list[A.Stmt], ind: str) -> list[str]:
        """Emit a statement list, lowering each buffer let by its lifetime shape.

        A buffer gets the exception-safe try/finally only when it nests cleanly:
        its `release` is straight-line at this level AND no other buffer is
        acquired inside its body (which would make the lifetimes overlap in
        non-LIFO order). Otherwise — overlapping lifetimes, or a release nested in
        branches — it uses inline-release: the prelude here, the real cleanup
        emitted at each `release` site (no hoist into finally; the same trade-off
        the codegen already makes for branchy ordinary resources)."""
        out: list[str] = []
        i = 0
        while i < len(stmts):
            st = stmts[i]
            if isinstance(st, A.Let) and isinstance(st.rhs, A.BufferIntent):
                rest = stmts[i + 1:]
                name = st.name
                j = self._find_release(rest, 0, name)
                if j is not None and not _fn_has_buffer(rest[:j]):
                    out.extend(self._emit_buffer_scoped(name, st.rhs, rest[:j], ind))
                    i += 1 + j + 1   # consume the let, its body, and its release
                    continue
                if not _buffer_released(rest, name):
                    # leak or escape — both rejected by the checker first
                    # (OWN001 / OWN015 / OWN016 / OWN017); unreachable cleanly.
                    raise CodegenError(
                        f"buffer '{name}' is never released and does not escape "
                        f"cleanly; the checker should have rejected this")
                out.extend(self._emit_buffer_inline(name, st.rhs, ind))
                i += 1
                continue
            out.extend(self._stmt_inline(st, ind))
            i += 1
        return out

    @staticmethod
    def _find_release(stmts: list[A.Stmt], start: int, name: str) -> int | None:
        for k in range(start, len(stmts)):
            st = stmts[k]
            if isinstance(st, A.Release) and st.var == name:
                return k
        return None

    # -- buffer lowering (the stackalloc / scratch / pool / native line) -----

    def _buffer_lowering(self, name: str, intent: A.BufferIntent
                         ) -> tuple[list[str], list[str]]:
        """Lower one buffer to its (prelude, cleanup) C# lines. The prelude holds
        the allocation + trace/counter hooks; the cleanup is the pool Return /
        native Free / clear. How they are placed (try/finally vs inline) is the
        caller's decision."""
        info, _ = resolve_buffer(intent, self.policies)
        self.buffer_vars[name] = info
        fn = self.fn.name
        size = self._size_expr(info)
        L = info.inline_bytes
        pre: list[str] = []   # declarations + trace/counters, before the try
        fin: list[str] = []   # cleanup, inside the finally / at release sites
        scratch_pool = info.mode == BufferMode.SCRATCH and info.fallback_pool

        if info.mode in (BufferMode.STACK, BufferMode.INLINE) or (
                info.mode == BufferMode.SCRATCH and not info.fallback_pool):
            if info.size_is_const:
                if info.trace:
                    pre.append(f'OwnTrace.StackSelected("{fn}", "{name}", {size}, {L});')
                if info.counters:
                    pre.append("OwnCounters.StackHit();")
                if info.size_const == L:
                    pre.append(f"Span<byte> {name} = stackalloc byte[{L}];")
                else:
                    # reserve the inline capacity but expose only the requested
                    # length (e.g. scratch(64, inline = 1024, fallback = forbidden)).
                    pre.append(f"Span<byte> {name}_backing = stackalloc byte[{L}];")
                    pre.append(f"Span<byte> {name} = {name}_backing[..{size}];")
            else:
                pre.append(f"if ((uint){size} > {L})")
                pre.append(f"    throw new ArgumentOutOfRangeException(nameof({size}));")
                if info.trace:
                    pre.append(f'OwnTrace.StackSelected("{fn}", "{name}", {size}, {L});')
                if info.counters:
                    pre.append("OwnCounters.StackHit();")
                pre.append(f"Span<byte> {name}_backing = stackalloc byte[{L}];")
                pre.append(f"Span<byte> {name} = {name}_backing[..{size}];")
            if info.clear_on_release:
                fin.append(f"{name}.Clear();")

        elif scratch_pool:
            pre.append(f"byte[]? {name}_rented = null;")
            pre.append(f"Span<byte> {name}_backing = stackalloc byte[{L}];")
            pre.append(f"Span<byte> {name};")
            pre.append(f"if ({size} <= {L})")
            pre.append("{")
            if info.trace:
                pre.append(f'    OwnTrace.ScratchSelected("{fn}", "{name}", {size}, {L}, "stackalloc");')
            if info.counters:
                pre.append("    OwnCounters.StackHit();")
            pre.append(f"    {name} = {name}_backing[..{size}];")
            pre.append("}")
            pre.append("else")
            pre.append("{")
            if info.trace:
                pre.append(f'    OwnTrace.ScratchSelected("{fn}", "{name}", {size}, {L}, "ArrayPool");')
            if info.counters:
                pre.append(f"    OwnCounters.PoolFallback({size});")
            pre.append(f"    {name}_rented = ArrayPool<byte>.Shared.Rent({size});")
            pre.append(f"    {name} = {name}_rented.AsSpan(0, {size});")
            pre.append("}")
            if info.counters:
                fin.append("OwnCounters.Release();")
            if info.clear_on_release:
                fin.append(f"{name}.Clear();")
            fin.append(f"if ({name}_rented is not null)")
            fin.append(f"    ArrayPool<byte>.Shared.Return({name}_rented);")

        elif info.mode == BufferMode.POOLED:
            if info.trace:
                pre.append(f'OwnTrace.PooledSelected("{fn}", "{name}", {size});')
            if info.counters:
                pre.append(f"OwnCounters.PoolFallback({size});")
            pre.append(f"byte[] {name}_array = ArrayPool<byte>.Shared.Rent({size});")
            pre.append(f"Span<byte> {name} = {name}_array.AsSpan(0, {size});")
            if info.counters:
                fin.append("OwnCounters.Release();")
            if info.clear_on_release:
                fin.append(f"{name}.Clear();")
            fin.append(f"ArrayPool<byte>.Shared.Return({name}_array);")

        elif info.mode == BufferMode.NATIVE:
            # the method is emitted `unsafe`, so the pointer needs no local block.
            if info.trace:
                pre.append(f'OwnTrace.NativeSelected("{fn}", "{name}", {size});')
            pre.append(f"byte* {name} = (byte*)System.Runtime.InteropServices."
                       f"NativeMemory.Alloc((nuint){size});")
            if info.counters:
                fin.append("OwnCounters.Release();")
            if info.clear_on_release:
                fin.append(f"System.Runtime.InteropServices.NativeMemory."
                           f"Clear({name}, (nuint){size});")
            fin.append(f"System.Runtime.InteropServices.NativeMemory.Free({name});")

        return pre, fin

    def _emit_buffer_scoped(self, name: str, intent: A.BufferIntent,
                            body: list[A.Stmt], ind: str) -> list[str]:
        """The buffer nests cleanly: wrap its body in an exception-safe
        try/finally (this is the golden scratch shape)."""
        pre, fin = self._buffer_lowering(name, intent)
        lines = [ind + p for p in pre]
        body_lines = self._emit_block(body, ind + "    ")
        if fin:
            lines.append(f"{ind}try")
            lines.append(f"{ind}{{")
            lines.extend(body_lines)
            lines.append(f"{ind}}}")
            lines.append(f"{ind}finally")
            lines.append(f"{ind}{{")
            for f in fin:
                lines.append(ind + "    " + f)
            lines.append(f"{ind}}}")
        else:
            # nothing to clean up (e.g. a stack buffer with no clear and no
            # counters): the body runs straight, the frame reclaims the bytes.
            for bl in body_lines:
                lines.append(bl[4:] if bl.startswith("    ") else bl)
        return lines

    def _emit_buffer_inline(self, name: str, intent: A.BufferIntent,
                            ind: str) -> list[str]:
        """Overlapping or branchy lifetime: emit the prelude here and attach the
        cleanup to each `release` site (handled by _stmt_inline). No try/finally —
        the same exception-safety trade-off as branchy ordinary resources."""
        pre, fin = self._buffer_lowering(name, intent)
        self.buffer_cleanup[name] = fin
        return [ind + p for p in pre]

    def _size_expr(self, info) -> str:
        if info.size_is_const:
            return str(info.size_const)
        if info.size_var:
            return info.size_var
        return "0"

    def _stmt_inline(self, st: A.Stmt, ind: str) -> list[str]:
        if isinstance(st, A.Let):
            if isinstance(st.rhs, A.Acquire):
                rt = st.rhs.resource
                self.owned_resource[st.name] = rt
                args_csv = ", ".join(self._arg(x) for x in st.rhs.args)
                return [f"{ind}{self._local_type(rt)} {st.name} = {self._acquire_expr(rt, args_csv)};"]
            if isinstance(st.rhs, A.Move):
                # a moved buffer carries its identity to the new owner: transfer
                # the pending cleanup so a later `release <new>` returns/frees the
                # original backing, and alias the C# local.
                if st.rhs.var in self.buffer_cleanup:
                    self.buffer_cleanup[st.name] = self.buffer_cleanup.pop(st.rhs.var)
                if st.rhs.var in self.buffer_vars:
                    self.buffer_vars[st.name] = self.buffer_vars[st.rhs.var]
                self.owned_resource[st.name] = self.owned_resource.get(st.rhs.var, "")
                return [f"{ind}var {st.name} = {st.rhs.var}; "
                        f"// ownership moved from {st.rhs.var}"]
            if isinstance(st.rhs, A.IntLit):
                return [f"{ind}var {st.name} = {st.rhs.value};"]
            if isinstance(st.rhs, A.VarRef):
                return [f"{ind}var {st.name} = {st.rhs.name};"]
        if isinstance(st, A.Release):
            if st.var in self.buffer_cleanup:
                # a branchy buffer release: emit this buffer's real cleanup
                # (pool Return / native Free / clear), not a generic Dispose.
                return [ind + line for line in self.buffer_cleanup[st.var]]
            rt = self.owned_resource.get(st.var, "")
            return [f"{ind}{self._release_stmt(st.var, rt)}"]
        if isinstance(st, A.Use):
            return [f"{ind}Use({st.var});"]
        if isinstance(st, A.Call):
            return [f"{ind}{st.callee}({', '.join(self._arg(a) for a in st.args)});"]
        if isinstance(st, A.BorrowBlock):
            kind = "mutable" if st.kind == A.BorrowKind.MUT else "shared"
            rt = self.owned_resource.get(st.owner, "")
            self.binding_owner_res[st.binding] = rt
            head = [f"{ind}{{ // {kind} borrow of {st.owner} as {st.binding}",
                    f"{ind}    var {st.binding} = {self._borrow_expr(st.owner, rt)};"]
            body = self._emit_block(st.body, ind + "    ")
            return head + body + [f"{ind}}}"]
        if isinstance(st, A.If):
            out = [f"{ind}if ({st.cond_text or 'cond'})", f"{ind}{{"]
            out.extend(self._emit_block(st.then_body, ind + "    "))
            out.append(f"{ind}}}")
            if st.else_body:
                out.append(f"{ind}else")
                out.append(f"{ind}{{")
                out.extend(self._emit_block(st.else_body, ind + "    "))
                out.append(f"{ind}}}")
            return out
        if isinstance(st, A.Return):
            return [f"{ind}return {st.var};" if st.var else f"{ind}return;"]
        raise CodegenError(f"cannot codegen {st!r}")

    # -- template helpers ---------------------------------------------------

    def _local_type(self, resource: str) -> str:
        r = self.res.get(resource)
        if r and r.emit_type:
            return r.emit_type
        return "var"

    def _acquire_expr(self, resource: str, args_csv: str) -> str:
        r = self.res.get(resource)
        if r and r.emit_acquire:
            return r.emit_acquire.replace("{args}", args_csv)
        method = _member(r, "acquire") if r else "Create"
        return f"{resource}.{method}({args_csv})"

    def _release_stmt(self, var: str, resource: str) -> str:
        r = self.res.get(resource)
        if r and r.emit_release:
            return r.emit_release.replace("{0}", var) + ";"
        method = _member(r, "release") if r else "Dispose"
        return f"{var}.{method}();"

    def _borrow_expr(self, owner_var: str, resource: str) -> str:
        r = self.res.get(resource)
        if r and r.emit_borrow:
            return r.emit_borrow.replace("{0}", owner_var)
        return owner_var

    def _arg(self, e: A.Expr) -> str:
        if isinstance(e, A.IntLit):
            return str(e.value)
        if isinstance(e, A.VarRef):
            return e.name
        return "/* expr */"


def _member(r: A.ResourceDecl, role: str) -> str:
    for m in r.members:
        if m.role == role:
            return m.name
    return "Create" if role == "acquire" else "Dispose"


def _contains_branch_or_transfer(stmts: list[A.Stmt]) -> bool:
    for st in stmts:
        if isinstance(st, A.If):
            return True
        if isinstance(st, A.Return) and st.var is not None:
            return True
        if isinstance(st, A.Let) and isinstance(st.rhs, A.Move):
            return True
        if isinstance(st, A.BorrowBlock):
            if _contains_branch_or_transfer(st.body):
                return True
    return False


def _iter_stmts(stmts: list[A.Stmt]):
    """Yield every statement in the tree, descending into if-branches and
    borrow blocks."""
    for st in stmts:
        yield st
        if isinstance(st, A.If):
            yield from _iter_stmts(st.then_body)
            yield from _iter_stmts(st.else_body)
        elif isinstance(st, A.BorrowBlock):
            yield from _iter_stmts(st.body)


def _move_aliases(stmts: list[A.Stmt], name: str) -> set[str]:
    """The set of names a buffer flows into via `let X = move <alias>`, starting
    from its declaration name (transitive)."""
    aliases = {name}
    changed = True
    while changed:
        changed = False
        for st in _iter_stmts(stmts):
            if (isinstance(st, A.Let) and isinstance(st.rhs, A.Move)
                    and st.rhs.var in aliases and st.name not in aliases):
                aliases.add(st.name)
                changed = True
    return aliases


def _buffer_released(stmts: list[A.Stmt], name: str) -> bool:
    """Is the buffer released somewhere — possibly through a moved alias?"""
    aliases = _move_aliases(stmts, name)
    return any(isinstance(st, A.Release) and st.var in aliases
               for st in _iter_stmts(stmts))


def _fn_has_buffer(stmts: list[A.Stmt]) -> bool:
    for st in stmts:
        if isinstance(st, A.Let) and isinstance(st.rhs, A.BufferIntent):
            return True
        if isinstance(st, A.If):
            if _fn_has_buffer(st.then_body) or _fn_has_buffer(st.else_body):
                return True
        if isinstance(st, A.BorrowBlock):
            if _fn_has_buffer(st.body):
                return True
    return False


def _fn_has_native(stmts: list[A.Stmt]) -> bool:
    for st in stmts:
        if (isinstance(st, A.Let) and isinstance(st.rhs, A.BufferIntent)
                and st.rhs.mode == "native"):
            return True
        if isinstance(st, A.If):
            if _fn_has_native(st.then_body) or _fn_has_native(st.else_body):
                return True
        if isinstance(st, A.BorrowBlock):
            if _fn_has_native(st.body):
                return True
    return False


def _buffer_modes(mod: A.Module) -> set[str]:
    modes: set[str] = set()

    def walk(stmts):
        for st in stmts:
            if isinstance(st, A.Let) and isinstance(st.rhs, A.BufferIntent):
                modes.add(st.rhs.mode)
            elif isinstance(st, A.If):
                walk(st.then_body)
                walk(st.else_body)
            elif isinstance(st, A.BorrowBlock):
                walk(st.body)

    for fn in mod.functions:
        walk(fn.body)
    return modes


def _usings(mod: A.Module) -> list[str]:
    out = ["using System;"]
    blob = " ".join(
        (r.emit_acquire or "") + (r.emit_release or "") + (r.emit_type or "")
        for r in mod.resources
    )
    modes = _buffer_modes(mod)
    if "ArrayPool" in blob or (modes & {"scratch", "pooled"}):
        out.append("using System.Buffers;")
    return out


# Runtime logging support emitted alongside any module that uses buffers. The
# two hooks are the runtime half of the design: a text trace of which backend a
# scratch/stack request actually selected, and counters answering "how often do
# we really hit the stack?". Both are [Conditional]: a normal Release build that
# defines neither symbol pays nothing — you do not want logging to become the
# new bottleneck on a hot path.
_RUNTIME_SUPPORT = '''\
internal static class OwnTrace
{
    [System.Diagnostics.Conditional("OWNSHARP_TRACE")]
    public static void ScratchSelected(string function, string buffer,
        int requestedBytes, int inlineLimit, string backend)
        => System.Diagnostics.Trace.WriteLine(
            $"[OwnSharp] {function}.{buffer}: requested={requestedBytes}, " +
            $"inline={inlineLimit}, backend={backend}");

    [System.Diagnostics.Conditional("OWNSHARP_TRACE")]
    public static void StackSelected(string function, string buffer,
        int requestedBytes, int inlineLimit)
        => System.Diagnostics.Trace.WriteLine(
            $"[OwnSharp] {function}.{buffer}: requested={requestedBytes}, " +
            $"inline={inlineLimit}, backend=stackalloc");

    [System.Diagnostics.Conditional("OWNSHARP_TRACE")]
    public static void PooledSelected(string function, string buffer, int requestedBytes)
        => System.Diagnostics.Trace.WriteLine(
            $"[OwnSharp] {function}.{buffer}: requested={requestedBytes}, backend=ArrayPool");

    [System.Diagnostics.Conditional("OWNSHARP_TRACE")]
    public static void NativeSelected(string function, string buffer, int requestedBytes)
        => System.Diagnostics.Trace.WriteLine(
            $"[OwnSharp] {function}.{buffer}: requested={requestedBytes}, backend=NativeMemory");
}

internal static class OwnCounters
{
    public static long ScratchStackHits;
    public static long ScratchPoolFallbacks;
    public static long ScratchPoolBytesRented;
    public static long ScratchReleaseCount;

    [System.Diagnostics.Conditional("OWNSHARP_COUNTERS")]
    public static void StackHit()
        => System.Threading.Interlocked.Increment(ref ScratchStackHits);

    [System.Diagnostics.Conditional("OWNSHARP_COUNTERS")]
    public static void PoolFallback(int bytes)
    {
        System.Threading.Interlocked.Increment(ref ScratchPoolFallbacks);
        System.Threading.Interlocked.Add(ref ScratchPoolBytesRented, bytes);
    }

    [System.Diagnostics.Conditional("OWNSHARP_COUNTERS")]
    public static void Release()
        => System.Threading.Interlocked.Increment(ref ScratchReleaseCount);
}
'''


def generate(mod: A.Module) -> str:
    parts = [
        "// <auto-generated> by OwnLang PoC. Ownership was checked at the .own",
        "// level; this C# is the lowering. Do not hand-edit.",
    ]
    parts.extend(_usings(mod))
    parts.append("")
    parts.append(f"public static class {mod.name}")
    parts.append("{")
    bodies = [_FnGen(mod, fn).emit() for fn in mod.functions]
    indented = []
    for b in bodies:
        indented.append("\n".join("    " + line if line else line
                                  for line in b.splitlines()))
    parts.append("\n\n".join(indented))
    parts.append("}")
    if _buffer_modes(mod):
        parts.append("")
        parts.append(_RUNTIME_SUPPORT)
    return "\n".join(parts) + "\n"
