# P-014 PROD0 — gates G2 (compatibility) and G3 (cost) for the opt-in `--binding-coverage` flag.
#   * builds the extractor from main (baseline) and from this branch, offline (global packages folder only);
#   * facts byte-identity: main vs branch-without-flag vs branch-with-flag, on P4, P5 (.csproj) and the sample tree;
#   * in-memory controls against the production code (harness references the built extractor);
#   * fixtures K3/K8a/K8b/K8c/K9/K10/G0 through the production flag, against the SDK oracle (own fixtures only,
#     restored offline);
#   * P4/P5: sidecar determinism over 3 runs, wall time and peak working set with and without the flag.
# Nothing third-party is restored or built. usage: pwsh run_prod0.ps1 -Work <dir> -Research <ownnet-direction-research>
param([Parameter(Mandatory)][string]$Work, [Parameter(Mandatory)][string]$Research)
$ErrorActionPreference = 'Stop'
$E = Split-Path -Parent $PSScriptRoot
$Repo = (Resolve-Path "$E\..\..\..").Path
$env:NoDefaultCurrentDirectoryInExePath = $null
$np = Join-Path $env:USERPROFILE '.nuget\packages'
$dotnet = 'C:\Program Files\dotnet'
if (Test-Path $Work) { Remove-Item -Recurse -Force $Work }
$R = New-Item -ItemType Directory -Force "$Work\res"
$cfg = "$Work\nuget.config"
Set-Content $cfg "<?xml version=`"1.0`" encoding=`"utf-8`"?><configuration><packageSources><clear /><add key=`"cache`" value=`"$np`" /></packageSources></configuration>"

"== build extractor: main (22b29d5b) and this branch"
New-Item -ItemType Directory "$Work\src-main" | Out-Null
git -C $Repo archive 22b29d5b frontend/roslyn/OwnSharp.Extractor | tar -x -C "$Work\src-main"
Copy-Item -Recurse "$Repo\frontend\roslyn\OwnSharp.Extractor" "$Work\src-new"
dotnet build "$Work\src-main\frontend\roslyn\OwnSharp.Extractor\OwnSharp.Extractor.csproj" -c Release -o "$Work\x-main" --configfile $cfg -nologo -v:q | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'main build failed' }
dotnet build "$Work\src-new\OwnSharp.Extractor.csproj" -c Release -o "$Work\x-new" --configfile $cfg -nologo -v:q | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'branch build failed' }
$xm = "$Work\x-main\ownsharp-extract.dll"; $xn = "$Work\x-new\ownsharp-extract.dll"

"== G2.1 facts byte-identity"
$inputs = @{
    P4 = Join-Path $Research 'evidence\pairs\BoBoBaSs84_BB84.IPTV__36\base\src\BB84.IPTV.M3U.Editor\BB84.IPTV.M3U.Editor.csproj'
    P5 = Join-Path $Research 'evidence\pairs\MERURUXD_FluentFlyout__3\base\FluentFlyoutWPF\FluentFlyout.csproj'
    samples = Join-Path $Repo 'frontend\roslyn\samples'
}
foreach ($id in 'P4', 'P5', 'samples') {
    $cwd = if ($id -eq 'samples') { $Repo } else { $Research }
    Push-Location $cwd
    dotnet $xm $inputs[$id] --flow-locals --no-project-refs -o "$R\$id.facts.main.json" 2>$null
    dotnet $xn $inputs[$id] --flow-locals --no-project-refs -o "$R\$id.facts.new.json" 2>$null
    dotnet $xn $inputs[$id] --flow-locals --no-project-refs -o "$R\$id.facts.flag.json" --binding-coverage "$R\$id.flag.sidecar.json" 2>$null
    $rcFlag = $LASTEXITCODE
    Pop-Location
    $h = 'main', 'new', 'flag' | ForEach-Object { (Get-FileHash "$R\$id.facts.$_.json" -Algorithm SHA256).Hash.Substring(0, 16) }
    "$id facts main/new/flag = $($h -join ' / ')  identical=$(@($h | Select-Object -Unique).Count -eq 1)  flag-run rc=$rcFlag"
}
python -I -c "import json,sys;u=json.load(open(sys.argv[1]))['units'];print('samples (directory) sidecar:',[(x['unit_status'],x['reasons']['unsupported']) for x in u])" "$R\samples.flag.sidecar.json"

"== G2.2 in-memory controls against the production code"
Copy-Item -Recurse "$E\harness" "$Work\harness"
Set-Content "$Work\harness\nuget.config" '<?xml version="1.0" encoding="utf-8"?><configuration><packageSources><clear /></packageSources></configuration>'
dotnet build "$Work\harness\P014Prod0Harness.csproj" -c Release -p:ExtractorDir="$Work\x-new" -o "$Work\harness-out" -nologo -v:q | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'harness build failed' }
dotnet "$Work\harness-out\p014prod0harness.dll" "$R\controls.json"; "controls rc=$LASTEXITCODE"

"== G2.2 fixtures through the production flag vs the SDK oracle"
Copy-Item -Recurse "$E\fixtures" "$Work\fx"
foreach ($p in 'K8a\K8a.csproj', 'K8b\K8b.csproj', 'K8c\K8c.csproj', 'K9\K9.csproj', 'K10\Root\Root.csproj', 'G0\G0.csproj') {
    dotnet restore "$Work\fx\$p" --configfile $cfg -v:q | Out-Null; "restore $p rc=$LASTEXITCODE"
}
$cases = @(@('K8a', 'K8a\K8a.csproj', ''), @('K8b', 'K8b\K8b.csproj', ''), @('K8c', 'K8c\K8c.csproj', ''), @('G0', 'G0\G0.csproj', ''),
           @('K9-net8.0', 'K9\K9.csproj', 'net8.0'), @('K9-net10.0', 'K9\K9.csproj', 'net10.0'))
Push-Location "$Work\fx"
foreach ($c in $cases) {
    $tf = if ($c[2]) { "-p:TargetFramework=$($c[2])" } else { '-p:P014Oracle=1' }
    dotnet msbuild "$Work\fx\$($c[1])" -nologo -t:FindReferenceAssembliesForReferences -getItem:ReferencePathWithRefAssemblies $tf | Out-File -Encoding utf8 "$R\$($c[0]).oracle.json"
    $a = @("$Work\fx\$($c[1])", '-o', "$R\$($c[0]).facts.json", '--binding-coverage', "$R\$($c[0]).sidecar.json")
    if ($c[2]) { $a += @('--binding-coverage-tfm', $c[2]) }
    dotnet $xn @a 2>$null
    python -I "$E\..\p014-tiny-poc-2026-10\scripts\compare_oracle.py" "$R\$($c[0]).oracle.json" "$R\$($c[0]).sidecar.json" $dotnet $np | Out-File -Encoding utf8 "$R\$($c[0]).compare.json"
    $j = Get-Content "$R\$($c[0]).compare.json" -Raw | ConvertFrom-Json
    "$($c[0]): pass=$($j.pass) oracle=$($j.oracle_refs) flag=$($j.instrument_refs) tie=$($j.tie_framework_assumed) unit=$($j.unit_status) conflicts=$(($j.conflicts | ForEach-Object { "$($_.name)->$($_.winner)($($_.rule))" }) -join '; ')"
}
dotnet $xn "$Work\fx\K9\K9.csproj" -o "$R\K9-notfm.facts.json" --binding-coverage "$R\K9-notfm.sidecar.json" 2>$null
dotnet $xn "$Work\fx\K10\Root\Root.csproj" -o "$R\K10-with.facts.json" --binding-coverage "$R\K10-with.sidecar.json" 2>$null
Remove-Item -Recurse -Force "$Work\fx\K10\Child\obj"
dotnet $xn "$Work\fx\K10\Root\Root.csproj" -o "$R\K10-without.facts.json" --binding-coverage "$R\K10-without.sidecar.json" 2>$null
Pop-Location
python -I -c @"
import json,sys
for f in sys.argv[1:]:
    for u in json.load(open(f))['units']:
        print(f.split('\\')[-1], u['project'], u['unit_status'], u['reasons'], 'event_assign=', (u.get('sites') or {}).get('event_assign'), 'foreign=', u.get('foreign_binding'))
"@ "$R\K9-notfm.sidecar.json" "$R\K10-with.sidecar.json" "$R\K10-without.sidecar.json"

"== G2.4 / G3 P4, P5: determinism and cost (3 processes each, with and without the flag)"
foreach ($id in 'P4', 'P5') {
    Push-Location $Research
    foreach ($mode in 'off', 'on') {
        foreach ($run in 1, 2, 3) {
            $psi = [Diagnostics.ProcessStartInfo]::new('dotnet')
            $al = @($xn, $inputs[$id], '--flow-locals', '--no-project-refs', '-o', "$R\$id.cost.$mode.$run.facts.json")
            if ($mode -eq 'on') { $al += @('--binding-coverage', "$R\$id.cost.$run.sidecar.json") }
            foreach ($x in $al) { $psi.ArgumentList.Add($x) }
            $psi.RedirectStandardError = $true; $psi.RedirectStandardOutput = $true; $psi.WorkingDirectory = $Research
            $sw = [Diagnostics.Stopwatch]::StartNew(); $p = [Diagnostics.Process]::Start($psi); $peak = 0
            while (-not $p.HasExited) { try { $p.Refresh(); $peak = [Math]::Max($peak, $p.PeakWorkingSet64) } catch { }; Start-Sleep -Milliseconds 20 }
            $p.WaitForExit(); $sw.Stop()
            "$id flag=$mode run$run rc=$($p.ExitCode) wall=$($sw.ElapsedMilliseconds)ms peak_ws>=$([math]::Round($peak/1MB))MB"
        }
    }
    Pop-Location
    $hs = 1..3 | ForEach-Object { (Get-FileHash "$R\$id.cost.$_.sidecar.json").Hash } | Select-Object -Unique
    $hf = 'off', 'on' | ForEach-Object { $m = $_; 1..3 | ForEach-Object { (Get-FileHash "$R\$id.cost.$m.$_.facts.json").Hash } } | Select-Object -Unique
    "$id sidecar identical across 3 runs: $(@($hs).Count -eq 1); facts identical across 6 runs (flag off/on): $(@($hf).Count -eq 1)"
}
