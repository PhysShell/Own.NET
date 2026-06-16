# How-to: run Own.NET on your C# (CLI · CI · Visual Studio)

Own.NET finds lifetime/resource leaks C# can't express (event/timer leaks,
undisposed `IDisposable`, ignored `Subscribe()` tokens, `ArrayPool` rent-without-
return). This guide shows the three ways to actually *run* it on your code.

> **There is no VSIX and no Roslyn analyzer.** On purpose — the checker is one
> Python core, and an in-process analyzer would force a second checker in C# (or
> shell out to Python on every keystroke). Instead the same finding is rendered
> in a format the host already understands: GitHub annotations for CI, and the
> **MSBuild diagnostic format** (`file(line): error CODE: …`) that the Visual
> Studio **Error List** parses for free. See
> [P-013](proposals/P-013-distribution-surface.md) for the why.

## 0. Prerequisites

The pipeline is two stages — a Roslyn extractor (C#) and the Python core — so you
need both runtimes plus an Own.NET checkout:

- **.NET SDK** 8.0+ (`dotnet`) — builds/runs the extractor.
- **Python** 3.11+ — runs the core.
- An **Own.NET checkout** somewhere on disk; below it is `$OWN` (e.g.
  `git clone https://github.com/PhysShell/Own.NET ~/own.net`).

Nothing is installed into your project — the tool reads your `.cs`, it does not
add a dependency.

## 1. From a terminal (the foundation everything else wraps)

```bash
# human-readable (default)
"$OWN/scripts/own-check.sh" -- path/to/your/Project

# Visual Studio / MSBuild Error List format
"$OWN/scripts/own-check.sh" --format msbuild -- path/to/your/Project

# CI annotations; non-zero exit on any finding
"$OWN/scripts/own-check.sh" --format github --fail-on-finding -- .

# advisory: render findings as warnings (won't fail a build)
"$OWN/scripts/own-check.sh" --format msbuild --severity warning -- path/to/your/Project
```

`own-check.sh` walks the path for `*.cs` (skipping `bin`/`obj`/`.git`/
`node_modules`/`packages` and generated files), runs the extractor → the core,
and prints findings. `--format msbuild` prints exactly:

```text
src/Vm/CustomerViewModel.cs(12): error OWN001: event 'bus.CustomerChanged' is subscribed (handler 'OnCustomerChanged') but never unsubscribed — the source keeps 'CustomerViewModel' alive (leak) [resource: subscription token]
```

That line shape is the canonical MSBuild diagnostic — which is the whole trick
for Visual Studio.

Exit codes: `0` clean · `1` findings (only with `--fail-on-finding`) · `≥2` a
hard error (bad facts). Without `--fail-on-finding` the script always exits `0`
so it never breaks a wrapping build by accident.

## 2. In Visual Studio

Two approaches, cheapest first.

### Option A — External Tool (on-demand, no build coupling) — recommended

Run the check from a menu item and get clickable results. **Tools → External
Tools… → Add:**

| Field | Value |
| --- | --- |
| Title | `Own.NET leak check` |
| Command | `bash` (Linux/macOS), or `C:\Program Files\Git\bin\bash.exe` (Git Bash on Windows) |
| Arguments | `"<OWN>/scripts/own-check.sh" --format msbuild -- "$(ProjectDir)"` |
| Initial directory | `$(SolutionDir)` |
| ✔ **Use Output window** | checked |

Run it from **Tools → Own.NET leak check**. Output appears in the Output window,
and because the lines are in canonical MSBuild format, Visual Studio makes each
one **double-click-to-navigate** to the exact file and line.

> On Windows the script needs a bash (WSL or Git Bash). If you'd rather not, use
> the raw two-command form from §4 in a `.cmd`/PowerShell External Tool instead.

### Option B — MSBuild target (findings in the Error List on every build)

Drop a `Directory.Build.targets` next to your solution (or add the `<Target>` to
a `.csproj`):

```xml
<Project>
  <PropertyGroup>
    <!-- Path to your Own.NET checkout. -->
    <OwnNetRoot>/abs/path/to/own.net</OwnNetRoot>
  </PropertyGroup>

  <Target Name="OwnNetLeakCheck" BeforeTargets="Build">
    <Exec Command="bash &quot;$(OwnNetRoot)/scripts/own-check.sh&quot; --format msbuild --severity warning -- &quot;$(MSBuildProjectDirectory)&quot;"
          ContinueOnError="true" />
  </Target>
</Project>
```

The MSBuild `Exec` task scans the command's output for canonical diagnostic
lines and raises them as build diagnostics, so they land in the **Error List**
and the build log without any analyzer.

**Severity:** `--severity` chooses how the host shows a finding. The target
above uses `--severity warning` so findings are **advisory** — they appear in
the Error List but don't fail the build, which is what you want on every
inner-loop build. Drop `--severity warning` (the default is `error`) if you'd
rather a leak break the build, e.g. on a release/CI configuration.

> Note: this runs the extractor build (`dotnet run`) as part of your build, which
> adds a few seconds. For large solutions prefer Option A or the CI job (§3) over
> a `BeforeTargets="Build"` hook on every inner-loop build.

## 3. In CI (GitHub Actions)

The reusable composite action annotates the PR diff. Add to a workflow (full
example in [`examples/ci/own-check.yml`](../examples/ci/own-check.yml)):

```yaml
- uses: actions/checkout@v4
- uses: PhysShell/own.net@main      # pin a tag for stability
  with:
    path: .
    format: github
    fail-on-finding: "true"
```

Findings appear as inline `error` annotations on the changed lines, and the
check goes red. This is the path that needs no local setup at all.

## 4. Windows without bash (PowerShell)

If you have no bash, use the bundled PowerShell twin — same flags, same output,
no shell dependency:

```powershell
& "$OWN\scripts\own-check.ps1" -Format msbuild -- src\MyApp
& "$OWN\scripts\own-check.ps1" -Format github -Severity warning -FailOnFinding -- .
```

Point a Visual Studio External Tool (§2A) at `powershell.exe` with arguments
`-File "<OWN>\scripts\own-check.ps1" -Format msbuild -- "$(ProjectDir)"`, or an
MSBuild `Exec` (§2B) at `powershell -File "$(OwnNetRoot)\scripts\own-check.ps1" …`,
instead of the bash command.

## Caveats

- **Heuristic findings can be false positives** (e.g. ownership handed to a
  callee). Treat output as a reviewer, not a gate, until you've calibrated it on
  your codebase — and prefer `--fail-on-finding` only once it's quiet.
- **One method at a time, type-aware (project-local `SemanticModel`).** The
  extractor does not do interprocedural/`async`/whole-program analysis yet (by
  design — see the ROADMAP). It honestly skips what it can't model rather than
  guessing.
- **`bin`/`obj`/generated files are skipped**; paths are reported relative to the
  scan root so they resolve in the editor and on the PR.

For the design rationale and the full surface ladder, see
[P-013](proposals/P-013-distribution-surface.md).
