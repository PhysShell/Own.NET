# P-014 Tiny PoC — build the instrument offline, run the in-memory controls, restore MY synthetic fixtures offline
# (the global packages folder is the only source), take the SDK oracle, run the instrument, compare.
# usage: pwsh run_fixtures.ps1 -Work <scratch dir> -Roslyn <dir with Microsoft.CodeAnalysis*.dll 4.9.2>
param([Parameter(Mandatory)][string]$Work, [Parameter(Mandatory)][string]$Roslyn)
$ErrorActionPreference = 'Stop'
$E = Split-Path -Parent $PSScriptRoot
$env:NoDefaultCurrentDirectoryInExePath = $null
$np = Join-Path $env:USERPROFILE '.nuget\packages'
$dotnet = 'C:\Program Files\dotnet'
$B = Join-Path $Work 'build'; $FX = Join-Path $Work 'fx'; $O = Join-Path $Work 'oracle'; $R = Join-Path $Work 'res'
foreach ($d in $B, $FX, $O, $R) { if (Test-Path $d) { Remove-Item -Recurse -Force $d }; New-Item -ItemType Directory -Force $d | Out-Null }

Copy-Item "$E\instrument\*" $B
Set-Content "$B\nuget.config" '<?xml version="1.0" encoding="utf-8"?><configuration><packageSources><clear /></packageSources></configuration>'
dotnet build "$B\P014Poc.csproj" -c Release -p:RoslynDir=$Roslyn -o "$B\out" -nologo -v:q | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'instrument build failed' }
$poc = "$B\out\p014poc.dll"

"== in-memory controls"
dotnet $poc controls --out "$R\controls.json"; "controls rc=$LASTEXITCODE"

Copy-Item -Recurse "$E\fixtures\*" $FX
Set-Content "$FX\nuget.config" "<?xml version=`"1.0`" encoding=`"utf-8`"?><configuration><packageSources><clear /><add key=`"cache`" value=`"$np`" /></packageSources></configuration>"
foreach ($p in 'K8a\K8a.csproj', 'K8b\K8b.csproj', 'K8c\K8c.csproj', 'K9\K9.csproj', 'K10\Root\Root.csproj') {
    dotnet restore "$FX\$p" --configfile "$FX\nuget.config" -v:q | Out-Null
    "restore $p rc=$LASTEXITCODE"
}

"== oracle vs instrument (K3, K8a, K8b, K8c, K9)"
$cases = @(@('K8a', 'K8a\K8a.csproj', ''), @('K8b', 'K8b\K8b.csproj', ''), @('K8c', 'K8c\K8c.csproj', ''),
           @('K9-net8.0', 'K9\K9.csproj', 'net8.0'), @('K9-net10.0', 'K9\K9.csproj', 'net10.0'))
foreach ($c in $cases) {
    $tf = if ($c[2]) { "-p:TargetFramework=$($c[2])" } else { '-p:P014Oracle=1' }
    dotnet msbuild "$FX\$($c[1])" -nologo -t:FindReferenceAssembliesForReferences -getItem:ReferencePathWithRefAssemblies $tf |
        Out-File -Encoding utf8 "$O\$($c[0]).json"
    $a = @('project', "$FX\$($c[1])", '--mode', 'exact', '--root', $FX, '--sidecar', "$R\$($c[0]).sidecar.json")
    if ($c[2]) { $a += @('--tfm', $c[2]) }
    dotnet $poc @a
    python -I "$E\scripts\compare_oracle.py" "$O\$($c[0]).json" "$R\$($c[0]).sidecar.json" $dotnet $np | Out-File -Encoding utf8 "$R\$($c[0]).compare.json"
    $j = Get-Content "$R\$($c[0]).compare.json" -Raw | ConvertFrom-Json
    "$($c[0]): pass=$($j.pass) oracle=$($j.oracle_refs) instrument=$($j.instrument_refs) only_oracle=$($j.only_oracle.Count) only_instrument=$($j.only_instrument.Count) tie=$($j.tie_framework_assumed) unit=$($j.unit_status) conflicts=$(($j.conflicts | ForEach-Object { "$($_.name)->$($_.winner)($($_.rule))" }) -join '; ')"
}
"== K9 without --tfm"
dotnet $poc project "$FX\K9\K9.csproj" --mode exact --root $FX --sidecar "$R\K9-notfm.sidecar.json"
python -I -c "import json,sys;u=json.load(open(sys.argv[1]))['units'][0];print(u['unit_status'],u['reasons']['unsupported'])" "$R\K9-notfm.sidecar.json"

"== K10 project reference: with child assets, then without"
dotnet $poc project "$FX\K10\Root\Root.csproj" --mode exact --root $FX --sidecar "$R\K10-with.sidecar.json"
Remove-Item -Recurse -Force "$FX\K10\Child\obj"
dotnet $poc project "$FX\K10\Root\Root.csproj" --mode exact --root $FX --sidecar "$R\K10-without.sidecar.json"
python -I -c @"
import json,sys
for f in sys.argv[1:]:
    us=json.load(open(f))['units']
    for u in us:
        print(f.split('\\')[-1], u['project'], u['unit_status'], u['reasons']['source_set'], 'event_assign=', (u['sites'] or {}).get('event_assign'), 'foreign=', u['foreign_binding'])
"@ "$R\K10-with.sidecar.json" "$R\K10-without.sidecar.json"
