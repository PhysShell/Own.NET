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
        self.owned_resource: dict[str, str] = {}
        # borrow binding name -> owner resource type (so calls know the C# view)
        self.binding_owner_res: dict[str, str] = {}
        for p in fn.params:
            if not p.type.borrowed and p.type.name in self.res:
                self.owned_resource[p.name] = p.type.name

    # -- shape detection ----------------------------------------------------

    def _is_simple(self) -> bool:
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
        out: list[str] = []
        for st in stmts:
            out.extend(self._stmt_inline(st, ind))
        return "".join(l + "\n" for l in out)

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
            body: list[str] = []
            for inner in st.body:
                body.extend(self._stmt_inline(inner, ind + "    "))
            return head + body + [f"{ind}}}"]
        if isinstance(st, A.If):
            out = [f"{ind}if ({st.cond_text or 'cond'})", f"{ind}{{"]
            for s in st.then_body:
                out.extend(self._stmt_inline(s, ind + "    "))
            out.append(f"{ind}}}")
            if st.else_body:
                out.append(f"{ind}else")
                out.append(f"{ind}{{")
                for s in st.else_body:
                    out.extend(self._stmt_inline(s, ind + "    "))
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


def _usings(mod: A.Module) -> list[str]:
    out = ["using System;"]
    blob = " ".join(
        (r.emit_acquire or "") + (r.emit_release or "") + (r.emit_type or "")
        for r in mod.resources
    )
    if "ArrayPool" in blob:
        out.append("using System.Buffers;")
    return out


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
    return "\n".join(parts) + "\n"
