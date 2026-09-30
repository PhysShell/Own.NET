# ownership-semantics-lab: runtime-effective dependency identity falsifier

Three builds of one library with an identical public surface — `LibA` (assembly 1.0.0.0, `Make()` returns a fresh
owned resource), `LibB` (assembly 1.0.0.0, a "patch" whose `Make()` returns a cached shared resource), `LibC`
(assembly 2.0.0.0, cached) — and an `App` compiled against `LibA` that disposes each `Make()` result. Substituting
`LibB` or `LibC` in the app directory (no rebuild) or loading them through a plugin `AssemblyLoadContext` changes the
effective ownership semantics while `App.deps.json` still says `Lib/1.0.0.0`. Evidence in Own.NET-paperwork
`paper-eval/ownership-lab/depid-v1.json`. Research-only; not part of any build.
