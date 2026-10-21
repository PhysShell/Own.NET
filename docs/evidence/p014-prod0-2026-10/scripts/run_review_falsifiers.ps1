# P-014 PROD0 — F-PROD0-1..3 (01-review-falsifiers.md) against one built extractor.
# usage: pwsh run_review_falsifiers.ps1 -Extractor <ownsharp-extract.dll> -Work <dir> -Label <name>
param([Parameter(Mandatory)][string]$Extractor, [Parameter(Mandatory)][string]$Work, [Parameter(Mandatory)][string]$Label)
$ErrorActionPreference = 'Stop'
$E = Split-Path -Parent $PSScriptRoot
$env:NoDefaultCurrentDirectoryInExePath = $null
$np = Join-Path $env:USERPROFILE '.nuget\packages'
if (Test-Path $Work) { Remove-Item -Recurse -Force $Work }
New-Item -ItemType Directory "$Work\fx", "$Work\res" | Out-Null
Set-Content "$Work\nuget.config" "<?xml version=`"1.0`" encoding=`"utf-8`"?><configuration><packageSources><clear /><add key=`"cache`" value=`"$np`" /></packageSources></configuration>"
foreach ($n in 'F1', 'F2', 'F3') {
    Copy-Item -Recurse "$E\fixtures\$n" "$Work\fx\$n"
    dotnet restore "$Work\fx\$n\$n.csproj" --configfile "$Work\nuget.config" -v:q | Out-Null
}
$me = [Security.Principal.WindowsIdentity]::GetCurrent().Name
icacls "$Work\fx\F3\B.cs" /deny "${me}:(R)" | Out-Null
try {
    Push-Location "$Work\fx"
    foreach ($n in 'F1', 'F2', 'F3') {
        $side = "$Work\res\$Label.$n.sidecar.json"
        $err = dotnet $Extractor "$Work\fx\$n\$n.csproj" -o "$Work\res\$Label.$n.facts.json" --binding-coverage $side 2>&1 |
            Where-Object { $_ -match 'binding-coverage' } | Out-String
        $rc = $LASTEXITCODE
        if (Test-Path $side) {
            $u = (Get-Content $side -Raw | ConvertFrom-Json).units[0]
            "$Label $n rc=$rc sidecar=yes unit_status=$($u.unit_status) unreadable=$($u.files.unreadable) source_set=[$($u.reasons.source_set -join ',')]"
        }
        else { "$Label $n rc=$rc sidecar=NO stderr=$($err.Trim())" }
    }
    Pop-Location
}
finally { icacls "$Work\fx\F3\B.cs" /remove:d "$me" | Out-Null }
