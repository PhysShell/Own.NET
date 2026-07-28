<#
.SYNOPSIS
  own-check — run the Own.NET C# leak check over a path (Windows/PowerShell).

.DESCRIPTION
  The PowerShell twin of own-check.sh, for Windows/Visual Studio users who have
  no bash. Chains the two stages of the P-001 pipeline into one command:

    *.cs --[OwnSharp.Extractor (Roslyn)]--> facts.json --[python -m ownlang ownir]--> findings

  There is one checker — the Python core; the C# side only extracts facts.
  Requires a .NET SDK (`dotnet`) and Python 3.11+ on PATH.

.PARAMETER Root
  The Own.NET checkout (where the extractor + ownlang live). Defaults to the
  repo this script lives in (scripts\..).

.PARAMETER Format
  Finding surface: human (default), github, or msbuild (Visual Studio Error List).

.PARAMETER Severity
  How a host shows findings: error (default) or warning (advisory).

.PARAMETER Verbosity
  How much to print: quiet (errors only — hide the advisory OWN050 "leakage
  analysis skipped" notes, P-014 Tier A), normal (default), or verbose (also a
  per-code breakdown).

.PARAMETER Legacy
  Use the legacy flat local-IDisposable detector instead of the default
  path-sensitive flow analysis (--flow-locals). The flow analysis is more precise
  (no Task/DataTable false positives; catches use-after-dispose / double-dispose /
  leak-on-a-path, and any IDisposable type) but honestly skips methods with loops /
  try until P-016 A1 lands. -Legacy is the broad, name-based fallback.

.PARAMETER FailOnFinding
  Exit non-zero (the core's code) when any leak is found.

.PARAMETER Paths
  Files or directories to scan (directories are walked for *.cs). Defaults to ".".

.EXAMPLE
  scripts\own-check.ps1 -Format msbuild -- src\MyApp
.EXAMPLE
  scripts\own-check.ps1 -Format github -Severity warning -FailOnFinding -- .
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$Root,
    [string]$Format = "human",
    [string]$Severity = "error",
    [ValidateSet("quiet", "normal", "verbose")]
    [string]$Verbosity = "normal",
    [switch]$Legacy,
    [switch]$FailOnFinding,
    # Position 0 is claimed EXPLICITLY, and automatic positional binding is off
    # for everything else (PositionalBinding = $false). Without both halves the
    # scan target lands in $Root — the first declared parameter took position 0
    # — and own-check then hunts for the extractor inside the tree it was asked
    # to scan, or silently scans "." instead. Declaring the contract beats
    # relying on declaration order to keep meaning it.
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$Paths
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Default root = the Own.NET checkout this script lives in (scripts\..).
if ([string]::IsNullOrEmpty($Root)) {
    $Root = Split-Path -Parent $PSScriptRoot
}
# A bare "--" separator (shell habit) is harmless; drop it. In an interactive
# session PowerShell eats the token itself, so this is a no-op there — it earns
# its keep when the arguments are splatted (`& own-check.ps1 @args`), where a
# literal "--" does arrive as a value.
if ($Paths) { $Paths = @($Paths | Where-Object { $_ -ne "--" }) }
if (-not $Paths -or $Paths.Count -eq 0) { $Paths = @(".") }

$extractor = Join-Path $Root "frontend\roslyn\OwnSharp.Extractor"
$facts = New-TemporaryFile
try {
    # Stage 1: extract facts. dotnet's build chatter is sent to the host (not
    # stdout) so stdout stays clean for the host-parseable findings; -o writes
    # the facts to a file. Default: the path-sensitive flow detector for local
    # IDisposables (--flow-locals); -Legacy keeps the flat name-based detector.
    $exArgs = @($Paths) + @("-o", $facts.FullName)
    if (-not $Legacy) { $exArgs += "--flow-locals" }
    & dotnet run --project $extractor -- @exArgs 1>$null
    if ($LASTEXITCODE -ne 0) {
        # Stage 1 failed: no verdict was produced. Exit 1 is reserved for
        # "analysed, findings present", so a broken build must not borrow it —
        # a caller that does not gate on findings would read it as clean. Map
        # it into the hard-error tier (the extractor's own 2/4 pass through).
        $stage1 = $LASTEXITCODE
        if ($stage1 -eq 1) { $stage1 = 2 }
        exit $stage1
    }

    # Stage 2: the one checker produces the verdict at the C# location.
    $env:PYTHONPATH = $Root
    $ownirArgs = @($facts.FullName, "--format", $Format, "--severity", $Severity,
                   "--verbosity", $Verbosity)
    & python -m ownlang ownir @ownirArgs
    $rc = $LASTEXITCODE
}
finally {
    Remove-Item $facts.FullName -ErrorAction SilentlyContinue
}

# rc: 0 = clean, 1 = findings, >=2 = a hard error (bad facts / drifted contract).
if ($FailOnFinding) { exit $rc }
if ($rc -ge 2) { exit $rc }
exit 0
