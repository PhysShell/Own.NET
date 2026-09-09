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

.PARAMETER Engine
  Which analysis engine runs (#262 Stage 1): python (DEFAULT and reference),
  rust (the Rust core `own-cli ownir`), or compare (both over one captured
  input, exposing the reference's result only when they agree byte for byte).
  rust and compare require the candidate binary's absolute path in
  OWEN_RUST_CORE — there is no discovery of any kind, so an unset or unusable
  OWEN_RUST_CORE is a configuration error (exit 2), never a silent fall back to
  Python. A Rust failure is never turned into a Python success in any mode.

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
    # D1: Python is the Stage-1 default on every launcher surface. ValidateSet
    # makes an unknown engine a parameter-binding failure rather than a value
    # that reaches the dispatch below.
    [ValidateSet("python", "rust", "compare")]
    [string]$Engine = "python",
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

# D3/D3.1 — the Stage-1 Rust candidate locator, resolved BEFORE anything is
# extracted. OWEN_RUST_CORE is the one ratified spelling and there is NO
# discovery (no PATH lookup, no rust\target probing), because discovery is how
# a stale binary silently stands in for the one under test. Every rejection is
# a configuration error (exit 2) — not 3 (Python-specific), not 5 (an internal
# failure) — and none of them falls back to Python.
$rustCore = ""
if ($Engine -eq "rust" -or $Engine -eq "compare") {
    $rustCore = $env:OWEN_RUST_CORE
    $problem = ""
    if ([string]::IsNullOrWhiteSpace($rustCore)) {
        $problem = "is not set (or is empty)"
    }
    elseif (Test-Path -LiteralPath $rustCore -PathType Container) {
        $problem = "points at a directory, not a file: '$rustCore'"
    }
    elseif (-not (Test-Path -LiteralPath $rustCore -PathType Leaf)) {
        $problem = "points at a path that does not exist: '$rustCore'"
    }
    if ($problem -ne "") {
        # Windows has no execute bit: an existing regular file is accepted here
        # and a genuinely broken image fails at spawn, which is the other side
        # of the D3.1 seam and already maps to the internal-error path.
        [Console]::Error.WriteLine(("own-check: --engine $Engine needs the candidate ``own-cli`` binary, but " +
            "OWEN_RUST_CORE $problem. Set OWEN_RUST_CORE to the absolute path of the ``own-cli`` " +
            "executable to run. Owen did not fall back to Python."))
        exit 2
    }
}

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

    # Stage 2: the SELECTED engine produces the verdict at the C# location.
    $env:PYTHONPATH = $Root
    $ownirArgs = @($facts.FullName, "--format", $Format, "--severity", $Severity,
                   "--verbosity", $Verbosity)

    if ($Engine -eq "python") {
        & python -m ownlang ownir @ownirArgs
        $rc = $LASTEXITCODE
    }
    elseif ($Engine -eq "rust") {
        # The PRODUCTION Rust executable, never own-shadow-engine.
        $rustArgs = @("ownir") + $ownirArgs
        & $rustCore @rustArgs
        $rc = $LASTEXITCODE
        # 0/1/2 are verdicts and pass through; anything else is not a verdict
        # and takes the public internal-error path (5) with the raw child
        # status named. It never runs Python instead.
        if ($rc -ne 0 -and $rc -ne 1 -and $rc -ne 2) {
            [Console]::Error.WriteLine(("own-check: the Rust analysis core exited $rc, which is not a " +
                "verdict (raw child status: $rc). Owen did not fall back to Python."))
            exit 5
        }
    }
    else {
        # D4/D4.1 — both engines over ONE capture, proved byte-identical.
        $cmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("owen-compare-" + [guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $cmpDir | Out-Null
        # Declared before the try so the finally can read it under
        # Set-StrictMode -Version Latest, where touching an undefined variable
        # is an error rather than $null.
        $keep = $false
        try {
            $capture = Join-Path $cmpDir "capture.json"
            Copy-Item -LiteralPath $facts.FullName -Destination $capture
            $captureSha = (Get-FileHash -LiteralPath $capture -Algorithm SHA256).Hash.ToLowerInvariant()

            # A compare that judged nothing agrees about nothing.
            $doc = $null
            try { $doc = Get-Content -LiteralPath $capture -Raw -Encoding utf8 | ConvertFrom-Json } catch { $doc = $null }
            if ($null -ne $doc) {
                $hasUnit = $false
                foreach ($k in @("components", "functions", "services", "effects", "protocols", "protocol_functions")) {
                    $v = $doc.PSObject.Properties[$k]
                    if ($null -ne $v -and $null -ne $v.Value -and @($v.Value).Count -gt 0) { $hasUnit = $true; break }
                }
                if (-not $hasUnit) {
                    [Console]::Error.WriteLine(("own-check: --engine compare: the captured OwnIR contains nothing to " +
                        "analyse — a compare over zero documents proves nothing and is a failure, not an " +
                        "agreement."))
                    exit 5
                }
            }

            $pyIn = Join-Path $cmpDir "python-input.json"
            $rsIn = Join-Path $cmpDir "rust-input.json"
            Copy-Item -LiteralPath $capture -Destination $pyIn
            Copy-Item -LiteralPath $capture -Destination $rsIn
            $pyInSha = (Get-FileHash -LiteralPath $pyIn -Algorithm SHA256).Hash.ToLowerInvariant()
            $rsInSha = (Get-FileHash -LiteralPath $rsIn -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($pyInSha -ne $captureSha -or $rsInSha -ne $captureSha) {
                [Console]::Error.WriteLine(("own-check: --engine compare: the two engine inputs are not byte-identical " +
                    "to the single capture (capture $captureSha, python $pyInSha, rust $rsInSha) — the " +
                    "same-input invariant failed, so no comparison may be reported."))
                exit 5
            }

            # Start-Process redirects the children's RAW bytes to files: a
            # claim about byte-identical output cannot be measured through
            # PowerShell's own string pipeline.
            $pyArgs = @("-m", "ownlang", "ownir", $pyIn, "--format", $Format, "--severity", $Severity,
                        "--verbosity", $Verbosity)
            $p1 = Start-Process -FilePath "python" -ArgumentList $pyArgs -NoNewWindow -Wait -PassThru `
                -RedirectStandardOutput (Join-Path $cmpDir "python.out") `
                -RedirectStandardError (Join-Path $cmpDir "python.err")
            $rsArgs = @("ownir", $rsIn, "--format", $Format, "--severity", $Severity,
                        "--verbosity", $Verbosity)
            $p2 = Start-Process -FilePath $rustCore -ArgumentList $rsArgs -NoNewWindow -Wait -PassThru `
                -RedirectStandardOutput (Join-Path $cmpDir "rust.out") `
                -RedirectStandardError (Join-Path $cmpDir "rust.err")
            $pyRc = $p1.ExitCode
            $rsRc = $p2.ExitCode

            # D4.1 (c): execution failure first — two results are comparable
            # only once both exist.
            $pyLegal = ($pyRc -eq 0 -or $pyRc -eq 1 -or $pyRc -eq 2)
            $rsLegal = ($rsRc -eq 0 -or $rsRc -eq 1 -or $rsRc -eq 2)
            if (-not $pyLegal -or -not $rsLegal) {
                [Console]::Error.WriteLine(("own-check: --engine compare: compare execution failure (python exit " +
                    "$pyRc, rust exit $rsRc). No engine's result was substituted for the other's failure. " +
                    "Reproduction — input sha256 $captureSha, candidate $rustCore, artifacts in $cmpDir"))
                if (-not $rsLegal) { [Console]::Error.WriteLine("own-check: raw Rust child status: $rsRc") }
                exit 5
            }

            # D4.1 (a)/(b): agreement or divergence, on bytes and the exit code.
            $diverged = @()
            if ($pyRc -ne $rsRc) { $diverged += "exit ($pyRc vs $rsRc)" }
            $pyOutH = (Get-FileHash -LiteralPath (Join-Path $cmpDir "python.out") -Algorithm SHA256).Hash
            $rsOutH = (Get-FileHash -LiteralPath (Join-Path $cmpDir "rust.out") -Algorithm SHA256).Hash
            $pyErrH = (Get-FileHash -LiteralPath (Join-Path $cmpDir "python.err") -Algorithm SHA256).Hash
            $rsErrH = (Get-FileHash -LiteralPath (Join-Path $cmpDir "rust.err") -Algorithm SHA256).Hash
            if ($pyOutH -ne $rsOutH) { $diverged += "stdout" }
            if ($pyErrH -ne $rsErrH) { $diverged += "stderr" }
            if ($diverged.Count -gt 0) {
                [Console]::Error.WriteLine(("own-check: --engine compare: engine divergence — the reference and the " +
                    "candidate disagree on " + ($diverged -join ", ") + ". Neither verdict is exposed as " +
                    "authoritative. Reproduction — input sha256 $captureSha, candidate $rustCore, artifacts " +
                    "in $cmpDir"))
                # Keep the artifacts for reproduction rather than deleting them.
                $keep = $true
                exit 5
            }

            # Agreement: the externally observed result is the reference's.
            Get-Content -LiteralPath (Join-Path $cmpDir "python.out") -Raw -ErrorAction SilentlyContinue | Write-Output
            $rc = $pyRc
        }
        finally {
            if (-not $keep) {
                Remove-Item -LiteralPath $cmpDir -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }
}
finally {
    Remove-Item $facts.FullName -ErrorAction SilentlyContinue
}

# rc: 0 = clean, 1 = findings, >=2 = a hard error (bad facts / drifted contract).
if ($FailOnFinding) { exit $rc }
if ($rc -ge 2) { exit $rc }
exit 0
