# P-014 Tiny PoC — context only (not a criterion): today's extractor, built offline from main, on the same .csproj inputs,
# 3 runs each with --flow-locals (the own-check default). Records wall time, peak working set, and the SHA-256 of the
# facts document, so the existing OwnIR facts can be shown byte-identical across runs (the PoC never touches them).
# usage: pwsh run_extractor_context.ps1 -Extractor <ownsharp-extract.dll> -Research <dir> -Out <dir>
param([Parameter(Mandatory)][string]$Extractor, [Parameter(Mandatory)][string]$Research, [Parameter(Mandatory)][string]$Out)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force $Out | Out-Null
$projects = @{
    P4 = 'evidence\pairs\BoBoBaSs84_BB84.IPTV__36\base\src\BB84.IPTV.M3U.Editor\BB84.IPTV.M3U.Editor.csproj'
    P5 = 'evidence\pairs\MERURUXD_FluentFlyout__3\base\FluentFlyoutWPF\FluentFlyout.csproj'
}
foreach ($id in 'P4', 'P5') {
    foreach ($run in 1, 2, 3) {
        $facts = Join-Path $Out "$id.facts.run$run.json"
        $psi = [Diagnostics.ProcessStartInfo]::new('dotnet')
        foreach ($a in @($Extractor, (Join-Path $Research $projects[$id]), '--flow-locals', '--no-project-refs', '-o', $facts)) { $psi.ArgumentList.Add($a) }
        $psi.WorkingDirectory = $Research; $psi.RedirectStandardError = $true; $psi.RedirectStandardOutput = $true
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $p = [Diagnostics.Process]::Start($psi)
        $peak = 0
        while (-not $p.HasExited) { try { $p.Refresh(); $peak = [Math]::Max($peak, $p.PeakWorkingSet64) } catch { }; Start-Sleep -Milliseconds 20 }
        $p.WaitForExit(); $sw.Stop()
        "$id extractor run$run rc=$($p.ExitCode) wall=$($sw.ElapsedMilliseconds)ms peak_ws>=$([math]::Round($peak/1MB))MB facts_sha256=$((Get-FileHash $facts -Algorithm SHA256).Hash.Substring(0,16))"
    }
}
