<#
.SYNOPSIS
  Own.NET Audit - Roslyn analyzer-pack runner (build-required tier).

.DESCRIPTION
  Builds the target ONCE with the audit analyzer cache injected (one build, many
  analyzers) and collects a per-project SARIF via <ErrorLog>. This is the
  build-required tier (Plan.md 3.2/3.3): it needs a successful MSBuild build, so
  it runs on the LOCAL WINDOWS MACHINE (VS Build Tools + DevExpress 12.2). There is
  no CI run of the target.

  Mechanism (Plan.md 3.1): a throwaway `git worktree` of the target with
  OwnAudit.Directory.Build.props/.targets copied in under MSBuild's recognized
  names, all gated on /p:OwnAudit=true so developer builds are untouched. The
  analyzer DLLs come from a pre-restored audit cache pointed to by
  $OwnAuditAnalyzers, NOT a PackageReference in the 12-year-old project tree.

  Pin analyzer-pack versions whose Roslyn runtime matches the target's MSBuild
  toolchain; an incompatible pack is recorded NO-TOOL, never forced.

.PARAMETER Solution
  Path to the target .sln (inside the audit worktree).

.PARAMETER AnalyzerCache
  Directory of pre-restored analyzer DLLs (sets $OwnAuditAnalyzers).

.PARAMETER Out
  Artifacts directory for the per-project SARIF (default artifacts\own-audit).

.EXAMPLE
  .\roslyn_pack.ps1 -Solution ..\target-audit\Target.sln -AnalyzerCache .\cache -Out artifacts\own-audit
#>
param(
  [Parameter(Mandatory = $true)][string]$Solution,
  [Parameter(Mandatory = $true)][string]$AnalyzerCache,
  [string]$Out = "artifacts\own-audit"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command msbuild -ErrorAction SilentlyContinue)) {
  Write-Error "NO-TOOL: msbuild not on PATH - install VS Build Tools (build-required tier runs on Windows)."
  exit 3
}

# Resolve -Out to an absolute path so the per-project ErrorLog (which the injected
# props anchors at $(OwnAuditOutDir)) lands here, not next to each project dir.
$OutFull = (New-Item -ItemType Directory -Force -Path $Out).FullName

# continue-on-error: a failed build still yields whatever per-project SARIFs were
# produced before the failure - a partial, honest report, not an empty one.
# /p:OwnAuditOutDir makes the injected props write SARIF under $OutFull\roslyn\.
msbuild $Solution `
  /p:OwnAudit=true `
  /p:OwnAuditAnalyzers=$AnalyzerCache `
  /p:OwnAuditOutDir=$OutFull `
  /p:Configuration=Release `
  /bl:"$OutFull\build.binlog"

Write-Host "roslyn_pack.ps1: per-project SARIF under $OutFull\roslyn (merged by audit/aggregate/)."
