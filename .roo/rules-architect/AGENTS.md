# Project Architecture Rules (Non-Obvious Only)

- Architecture invariant: frontends are fact producers only; duplicating verdict logic outside the Python core is considered checker drift.
- Token/resource leaks use acquire/release ownership, but tokenless long-lived captures route through `lifetimes.py` region escape (OWN014), not through fake resources.
- DI facts can provide region lifetimes for injected subscription sources, allowing OWN014 escalation only when the source lifetime is known to outlive the subscriber.
- The Roslyn project resolver is intentionally dependency-free text/XML/glob handling, not full MSBuild evaluation; design around honest coverage gaps rather than pretending a project graph exists.
- Low false-positive posture is deliberate: unresolved events become OWN050, flow-locals skip unsupported constructs, and audit categories without reliable tools stay NO-TOOL.
- `audit/` is architecturally decoupled from `ownlang`; normalize/score/report consume external tool SARIF and rank by cross-tool agreement, not by analyzer severity alone.
- Runtime audit for net472/WPF uses ETW/procdump/ClrMD rather than `dotnet-*` diagnostics because CoreCLR tools do not attach to .NET Framework targets.
