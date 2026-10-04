# OX-02 P14 kill-first probe: can a hosted Windows runner start Visual Studio, open a
# solution in an experimental hive, edit a buffer through DTE and read the Error List?
$ErrorActionPreference = 'Continue'
$out = Join-Path $PWD 'vs-probe'
New-Item -ItemType Directory -Force $out | Out-Null
function Log($m) { $line = "[$(Get-Date -Format HH:mm:ss.fff)] $m"; Write-Host $line; Add-Content (Join-Path $out 'probe.log') $line }

$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$all = & $vswhere -all -prerelease -products * -format json | ConvertFrom-Json
foreach ($i in $all) { Log "VS: $($i.displayName) $($i.installationVersion) at $($i.installationPath)" }
$vs = & $vswhere -latest -products * -property installationPath
$ver = & $vswhere -latest -products * -property installationVersion
Log "latest: $vs ($ver)"
$ws = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Workload.VisualStudioExtension -property installationPath
Log "VSSDK workload: '$ws'"
$devenv = Join-Path $vs 'Common7\IDE\devenv.exe'
$vsix = Join-Path $vs 'Common7\IDE\VSIXInstaller.exe'
Log "devenv exists: $(Test-Path $devenv); VSIXInstaller exists: $(Test-Path $vsix)"
Log "session: $([Environment]::UserInteractive) user=$env:USERNAME"
& dotnet --list-sdks | ForEach-Object { Log "sdk $_" }

$work = Join-Path $env:RUNNER_TEMP 'probe'
New-Item -ItemType Directory -Force $work | Out-Null
Push-Location $work
& dotnet new console -n Probe --framework net8.0 -o Probe 2>&1 | Out-Null
& dotnet new sln -n Probe --format sln 2>&1 | Out-Null
& dotnet sln Probe.sln add Probe\Probe.csproj 2>&1 | Out-Null
& dotnet restore Probe.sln 2>&1 | Out-Null
Pop-Location
$sln = Join-Path $work 'Probe.sln'
$cs = Join-Path $work 'Probe\Program.cs'

$major = $ver.Split('.')[0]
$t0 = Get-Date
$p = Start-Process $devenv -ArgumentList "/rootsuffix", "Exp", "`"$sln`"" -PassThru
Log "devenv pid $($p.Id)"
Add-Type -AssemblyName System.Windows.Forms, System.Drawing, UIAutomationClient, UIAutomationTypes
$shot = 0
function Shot($name) {
  try {
    $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
    $bmp.Save((Join-Path $out "$name.png")); $g.Dispose(); $bmp.Dispose()
  } catch { Log "screenshot failed: $_" }
}
function Windows($procId) {
  $root = [System.Windows.Automation.AutomationElement]::RootElement
  $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $procId)
  foreach ($w in $root.FindAll([System.Windows.Automation.TreeScope]::Children, $cond)) {
    Log "  window: '$($w.Current.Name)' class=$($w.Current.ClassName)"
    foreach ($c in $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)) {
      $n = $c.Current.Name
      if ($n -and $c.Current.ControlType.ProgrammaticName -match 'Button|Hyperlink|Text|Window') { Log "    $($c.Current.ControlType.ProgrammaticName) '$n'" }
    }
  }
}
$dte = $null
for ($k = 0; $k -lt 120 -and -not $dte; $k++) {
  Start-Sleep -Seconds 2
  if ($k % 15 -eq 0) { Shot ("start-{0:D3}" -f $k); Log "t=$($k*2)s"; Windows $p.Id }
  try { $dte = [System.Runtime.InteropServices.Marshal]::GetActiveObject("VisualStudio.DTE.$major.0") } catch { }
}
Shot "dte"; Windows $p.Id
if (-not $dte) { Log "NO DTE after 240 s"; }
else {
  Log "DTE after $([int]((Get-Date) - $t0).TotalSeconds) s: $($dte.Version) $($dte.Edition)"
  function Retry([scriptblock]$b) { for ($r = 0; $r -lt 60; $r++) { try { return & $b } catch { Start-Sleep -Milliseconds 1000 } } ; throw "gave up" }
  for ($k = 0; $k -lt 60; $k++) { try { if ($dte.Solution.IsOpen -and $dte.Solution.Projects.Count -gt 0) { break } } catch { Log "dte call: $($_.Exception.Message)" } ; Start-Sleep 2; if ($k % 10 -eq 0) { Shot ("wait-{0:D3}" -f $k); Windows $p.Id } }
  Log "solution: $(Retry { $dte.Solution.FullName }) projects=$(Retry { $dte.Solution.Projects.Count })"
  $win = Retry { $dte.ItemOperations.OpenFile($cs) }
  $doc = Retry { $dte.ActiveDocument }
  Log "active: $(Retry { $doc.FullName })"
  $td = Retry { $doc.Object('TextDocument') }
  $ep = Retry { $td.EndPoint.CreateEditPoint() }
  Retry { $ep.Insert("`r`nclass Broken { void M() { int x = `"s`"; } }`r`n") } | Out-Null
  Log "inserted; saved=$(Retry { $doc.Saved })"
  Retry { $dte.ExecuteCommand('View.ErrorList') } | Out-Null
  for ($k = 0; $k -lt 30; $k++) {
    Start-Sleep 2
    $items = Retry { $dte.ToolWindows.ErrorList.ErrorItems }
    $n = Retry { $items.Count }
    Log "error items: $n"
    if ($n -gt 0) {
      for ($j = 1; $j -le $n; $j++) { $e = $items.Item($j); Log "  [$($e.ErrorLevel)] $($e.FileName)($($e.Line),$($e.Column)) $($e.Description) project=$($e.Project)" }
      $e = $items.Item(1)
      Retry { $e.Navigate() } | Out-Null
      Start-Sleep 1
      $sel = Retry { $dte.ActiveDocument.Selection }
      Log "after Navigate: line=$($sel.CurrentLine) col=$($sel.CurrentColumn)"
      break
    }
  }
  try {
    Add-Type -AssemblyName System.Windows.Forms, System.Drawing
    $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
    $bmp.Save((Join-Path $out 'screen.png')); Log "screenshot $($b.Width)x$($b.Height)"
  } catch { Log "screenshot failed: $_" }
}
Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
Log "end"
