# OX-02 P11: what Owen.VisualStudio reuses from Snipper

Source: `PhysShell/snipper` at `43b395a`, MIT licence (its `LICENSE`). Only audited
infrastructure was taken, and only by **adaptation** (nothing is vendored or copied verbatim).
The OX-01 audit (`owen-extension-snipper-salvage.md`) rejected Snipper's long-lived process
lifecycle (stderr lost, crashes unwatched, orphans possible); none of it is used here.

| # | chunk in Owen.NET | origin in Snipper | verdict | what changed |
|---|---|---|---|---|
| 1 | `frontend/roslyn/Owen.VisualStudio/Owen.VisualStudio.csproj` (SDK-style VSIX project: `net472`, `Microsoft.VisualStudio.SDK` with `ExcludeAssets="runtime"`, `Microsoft.VSSDK.BuildTools`, `CreateVsixContainer`) | `extensions/snipper-vs/Snipper.VisualStudio/Snipper.VisualStudio.csproj` | ADAPT | no cargo build or bundled binary (the service comes from the project's `Owen.Build`); no pkgdef/VsPackage (MEF only); the build tools only on Windows so the project compiles on Linux |
| 2 | `frontend/roslyn/Owen.VisualStudio/source.extension.vsixmanifest` | `extensions/snipper-vs/Snipper.VisualStudio/source.extension.vsixmanifest` | ADAPT | MEF component only; targets 17.14–18.x; adds the Roslyn language-services prerequisite |
| 3 | `scripts/vs/owen-vs-acceptance.ps1`: vswhere instance selection, a dedicated root suffix (never the shared `Exp`), the `/log` activity log, relaunch after the registration restart | `extensions/snipper-vs/scripts/vs-smoke.ps1` | ADAPT | installs with `VSIXInstaller` instead of `DeployVsixExtensionFiles`; drives the IDE (DTE edits, UI Automation Error List, Owen's trace) instead of only checking that a process started |
| 4 | `tests/owen-live/LiveClientTests/LiveClientTests.csproj`: the VS-independent sources compiled into a test project by `<Compile Link>` | `extensions/snipper-vs/Snipper.VisualStudio.IntegrationTests/*.csproj` | ADAPT (pattern) | `net8.0` console runner on any OS instead of a `net472` mocked-VS xunit project; tests the real `owen serve` |

**Not reused**, by decision: the LSP client spine (`SnipperLanguageServerProvider`, StreamJsonRpc),
the PATH-fallback binary locator, Snipper's commands/options page, its process lifecycle.
`owen-live/1` is a small purpose-built framing (`Content-Length` + JSON, fatal on anything
malformed); the service lifecycle is new (`LiveService`/`LiveSupervisor`: stderr kept, death
detected and shown, restart budget, a Windows job object so the child never outlives devenv).
