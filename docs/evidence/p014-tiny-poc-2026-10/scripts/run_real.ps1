# P-014 Tiny PoC — P4/P5 (#419 anchors), read-only: no restore, no build of their code. Per project and mode, 3 separate
# processes x (cold + warm) iterations; then the legacy->exact lost-site list.
# usage: pwsh run_real.ps1 -Work <scratch dir> -Poc <p014poc.dll> -Research <ownnet-direction-research dir>
param([Parameter(Mandatory)][string]$Work, [Parameter(Mandatory)][string]$Poc, [Parameter(Mandatory)][string]$Research)
$ErrorActionPreference = 'Stop'
$R = Join-Path $Work 'real'; if (Test-Path $R) { Remove-Item -Recurse -Force $R }; New-Item -ItemType Directory -Force $R | Out-Null
$projects = @{
    P4 = 'evidence\pairs\BoBoBaSs84_BB84.IPTV__36\base\src\BB84.IPTV.M3U.Editor\BB84.IPTV.M3U.Editor.csproj'
    P5 = 'evidence\pairs\MERURUXD_FluentFlyout__3\base\FluentFlyoutWPF\FluentFlyout.csproj'
}
foreach ($id in 'P4', 'P5') {
    $csproj = Join-Path $Research $projects[$id]
    foreach ($mode in 'legacy', 'exact') {
        foreach ($run in 1, 2, 3) {
            dotnet $Poc project $csproj --mode $mode --root $Research --iters 2 `
                --sidecar "$R\$id.$mode.run$run.sidecar.json" --timing "$R\$id.$mode.run$run.timing.json"
            if ($LASTEXITCODE -ne 0) { throw "$id $mode run $run failed" }
            $t = Get-Content "$R\$id.$mode.run$run.timing.json" -Raw | ConvertFrom-Json
            "$id $mode run$run " + (($t.timing | ForEach-Object { "$($_.kind)=$($_.wall_ms)ms/$([math]::Round($_.peak_working_set_mb))MB" }) -join ' ')
        }
        $h = 1..3 | ForEach-Object { (Get-FileHash "$R\$id.$mode.run$_.sidecar.json").Hash } | Select-Object -Unique
        "$id $mode sidecar identical across 3 runs: $(@($h).Count -eq 1)"
    }
    dotnet $Poc lost $csproj --root $Research --out "$R\$id.lost.json"
}
