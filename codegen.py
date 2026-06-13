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
        head = f"public static {ret} {self.fn.name}({params})"
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
        """Emit a statement list. A buffer let consumes the statements up to its
        matching `release` and lowers them inside its storage prelude + finally."""
        out: list[str] = []
        i = 0
        while i < len(stmts):
            st = stmts[i]
            if isinstance(st, A.Let) and isinstance(st.rhs, A.BufferIntent):
                j = self._find_release(stmts, i + 1, st.name)
                body = stmts[i + 1:j] if j is not None else stmts[i + 1:]
                # no matching `release` => the buffer escapes (it was returned or
                # consumed; the checker already proved this is the only clean
                # reason). Ownership transferred, so cleanup must NOT run here.
                escapes = j is None
                out.extend(self._emit_buffer(st.name, st.rhs, body, ind, escapes))
                i = (j + 1) if j is not None else len(stmts)
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

    def _emit_buffer(self, name: str, intent: A.BufferIntent,
                     body: list[A.Stmt], ind: str,
                     escapes: bool = False) -> list[str]:
        info, _ = resolve_buffer(intent, self.policies)
        self.buffer_vars[name] = info
        fn = self.fn.name
        size = self._size_expr(info)
        L = info.inline_bytes
        pre: list[str] = []   # declarations + trace/counters, before the try
        fin: list[str] = []   # cleanup, inside the finally
        native = info.mode == BufferMode.NATIVE
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

        elif native:
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

        if escapes:
            # ownership left the function (return / consume): the new owner is
            # responsible for Return/Free, so drop this frame's cleanup entirely.
            fin = []
        return self._wrap_buffer(pre, body, fin, ind, native)

    def _wrap_buffer(self, pre: list[str], body: list[A.Stmt],
                     fin: list[str], ind: str, native: bool) -> list[str]:
        lines: list[str] = []
        base = ind
        if native:
            lines.append(f"{base}unsafe")
            lines.append(f"{base}{{")
            inner = base + "    "
        else:
            inner = base
        for p in pre:
            lines.append(inner + p)
        body_lines = self._emit_block(body, inner + "    ")
        if fin:
            lines.append(f"{inner}try")
            lines.append(f"{inner}{{")
            lines.extend(body_lines)
            lines.append(f"{inner}}}")
            lines.append(f"{inner}finally")
            lines.append(f"{inner}{{")
            for f in fin:
                lines.append(inner + "    " + f)
            lines.append(f"{inner}}}")
        else:
            # nothing to clean up (e.g. a stack buffer with no clear and no
            # counters): the body runs straight, the frame reclaims the bytes.
            for bl in body_lines:
                # de-indent one level since there is no try block
                lines.append(bl[4:] if bl.startswith("    ") else bl)
        if native:
            lines.append(f"{base}}}")
        return lines

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
                self.owned_resource[st.name] = self.owned_resource.get(st.rhs.var, "")
                return [f"{ind}var {st.name} = {st.rhs.var}; "
                        f"// ownership moved from {st.rhs.var}"]
            if isinstance(st.rhs, A.IntLit):
                return [f"{ind}var {st.name} = {st.rhs.value};"]
            if isinstance(st.rhs, A.VarRef):
                return [f"{ind}var {st.name} = {st.rhs.name};"]
        if isinstance(st, A.Release):
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
