# OX-02 P14: the real Visual Studio acceptance of Owen.VisualStudio
# (docs/notes/owen-visual-studio-preregistration.md §7, §8, §10).
#
# Installs the built VSIX into a dedicated root suffix, opens the prepared solution (restored,
# never built), and drives the IDE the way a user would: open Use.cs, type a second
# `draft.Submit(now);` WITHOUT saving, and require
#   * Owen's squiggle (the tagger's own tags, from the opt-in trace) on the inserted line and at
#     the finding's location,
#   * an OWN002 row in the Error List (read from the Error List control itself, UI Automation),
#   * double-clicking that row moves the caret to the row's file/line/column,
#   * a CS error and OWN002 side by side,
#   * deleting the line makes the row and the squiggles disappear,
# and measures edit -> squiggle and edit -> disappearance over repeated edits, and the longest
# UI-thread handler. Nothing is saved and nothing is built.
#
# ADAPTED from Snipper (PhysShell/snipper 43b395a, MIT, extensions/snipper-vs/scripts/vs-smoke.ps1):
# vswhere instance selection, a dedicated root suffix (never the shared Exp hive), the activity
# log, and the relaunch when VS restarts itself after registering an extension.
param(
    [Parameter(Mandatory = $true)][string]$Vsix,
    [Parameter(Mandatory = $true)][string]$Fixture,
    [Parameter(Mandatory = $true)][string]$Out,
    [string]$RootSuffix = "OwenLive",
    [int]$Repeats = 10
)

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force $Out | Out-Null
$results = [ordered]@{ checks = @(); measurements = [ordered]@{} }
$failed = $false
function Log($m) { $line = "[$(Get-Date -Format HH:mm:ss.fff)] $m"; Write-Host $line; Add-Content (Join-Path $Out 'acceptance.log') $line }
function Check($name, $holds, $detail) {
    $script:results.checks += [ordered]@{ name = $name; ok = [bool]$holds; detail = "$detail" }
    if ($holds) { Log "ok[$name]: $detail" } else { Log "FAIL[$name]: $detail"; $script:failed = $true }
}
function Now() { [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() }

Add-Type -AssemblyName System.Windows.Forms, System.Drawing, UIAutomationClient, UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class Mouse {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, UIntPtr e);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  public static void DoubleClick(int x, int y) {
    SetCursorPos(x, y);
    for (int i = 0; i < 2; i++) { mouse_event(2, 0, 0, 0, UIntPtr.Zero); mouse_event(4, 0, 0, 0, UIntPtr.Zero); }
  }
}
"@

function Shot($name) {
    try {
        $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
        $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
        $bmp.Save((Join-Path $Out "$name.png")); $g.Dispose(); $bmp.Dispose()
    } catch { Log "screenshot failed: $_" }
}

function Retry([scriptblock]$Block, [int]$Seconds = 60) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ($true) {
        try { return & $Block }
        catch {
            if ((Get-Date) -gt $deadline) { throw }
            Start-Sleep -Milliseconds 500
        }
    }
}

# Where an installed extension and the MEF composition's own errors live, for the evidence.
function Collect-Diagnostics {
    $hive = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Microsoft\VisualStudio') -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "*$RootSuffix" }
    foreach ($h in $hive) {
        Log "hive: $($h.FullName)"
        Get-ChildItem (Join-Path $h.FullName 'Extensions') -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like '*Owen*' -or $_.Name -like '*.vsixmanifest' -or $_.Name -like 'extensions.*' } |
            ForEach-Object { Log "  ext: $($_.FullName)" }
        Get-ChildItem (Join-Path $h.FullName 'ComponentModelCache') -ErrorAction SilentlyContinue | ForEach-Object {
            Log "  cache: $($_.Name) $($_.Length)"
            if ($_.Name -like '*.err') { Copy-Item $_.FullName (Join-Path $Out $_.Name) -ErrorAction SilentlyContinue }
        }
    }
    Get-ChildItem $env:TEMP -Filter 'dd_VSIXInstaller*' -ErrorAction SilentlyContinue | ForEach-Object { Copy-Item $_.FullName $Out -ErrorAction SilentlyContinue }
}

# ---- Visual Studio ----------------------------------------------------------------------------
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = (& $vswhere -latest -products * -format json | ConvertFrom-Json)[0]
Log "Visual Studio: $($vs.displayName) $($vs.installationVersion) [$($vs.instanceId)]"
$results.measurements.visual_studio = "$($vs.displayName) $($vs.installationVersion)"
$devenv = $vs.productPath
$installer = Join-Path $vs.installationPath 'Common7\IDE\VSIXInstaller.exe'

$fx = Get-Content $Fixture -Raw | ConvertFrom-Json
$env:NUGET_PACKAGES = $fx.nuget_packages
$trace = Join-Path $Out 'trace.jsonl'
if (Test-Path $trace) { Remove-Item $trace }
$env:OWEN_LIVE_TRACE = $trace

# install the VSIX like a user would, into the dedicated hive
$p = Start-Process $installer -ArgumentList "/quiet", "/rootSuffix:$RootSuffix", "/instanceIds:$($vs.instanceId)", "/logFile:$(Join-Path $Out 'vsixinstaller.log')", "`"$Vsix`"" -Wait -PassThru
Check "install-vsix" ($p.ExitCode -eq 0) "VSIXInstaller exit $($p.ExitCode) into root suffix $RootSuffix"
if ($p.ExitCode -ne 0) { $results | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $Out 'results.json'); exit 1 }

# The MEF composition is cached per hive (ComponentModelCache). A hosted image ships that
# cache prebuilt, and installing an extension rebuilt the pkgdef cache but not this one (the
# run on 4289f6a: the cache files were byte-for-byte the image's, no part of Owen in them).
# Drop it so Visual Studio composes again with the installed extension, as /updateconfiguration
# would on a developer machine.
foreach ($h in (Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Microsoft\VisualStudio') -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "*$RootSuffix" })) {
    $cache = Join-Path $h.FullName 'ComponentModelCache'
    if (Test-Path $cache) { Remove-Item -Recurse -Force $cache; Log "dropped the MEF cache $cache" }
}
$u = Start-Process $devenv -ArgumentList "/rootsuffix", $RootSuffix, "/updateconfiguration" -Wait -PassThru
Log "devenv /updateconfiguration exit $($u.ExitCode)"

$major = $vs.installationVersion.Split('.')[0]
$activity = Join-Path $Out 'ActivityLog.xml'
$t0 = Now
$proc = Start-Process $devenv -ArgumentList "/rootsuffix", $RootSuffix, "/log", "`"$activity`"", "`"$($fx.sln)`"" -PassThru
Log "devenv pid $($proc.Id)"
# A hive's first launch shows modal first-run dialogs (sign-in, then the environment
# settings); a modal dialog rejects every DTE call. Dismiss them the way a user would.
$firstRun = @('Skip and add accounts later.', 'Skip and add accounts later', 'Not now, maybe later.', 'Start Visual Studio')
function Dismiss-FirstRun {
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $byPid = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $proc.Id)
    foreach ($w in $root.FindAll([System.Windows.Automation.TreeScope]::Children, $byPid)) {
        foreach ($name in $firstRun) {
            $c = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $name)
            $el = $w.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $c)
            if ($el) {
                Log "first-run dialog: '$name'"
                try { $el.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke() }
                catch {
                    $r = $el.Current.BoundingRectangle
                    [Mouse]::SetCursorPos([int]($r.X + $r.Width / 2), [int]($r.Y + $r.Height / 2)) | Out-Null
                    [Mouse]::mouse_event(2, 0, 0, 0, [UIntPtr]::Zero); [Mouse]::mouse_event(4, 0, 0, 0, [UIntPtr]::Zero)
                }
                return $true
            }
        }
    }
    return $false
}
$dte = $null
for ($k = 0; $k -lt 180 -and -not $dte; $k++) {
    Start-Sleep -Seconds 2
    try { [void](Dismiss-FirstRun) } catch { Log "dismiss: $_" }
    if ($k % 30 -eq 0) { Shot ("startup-{0:D3}" -f $k) }
    if ($proc.HasExited) {
        Log "devenv exited ($($proc.ExitCode)); relaunching once (extension registration restart)"
        $proc = Start-Process $devenv -ArgumentList "/rootsuffix", $RootSuffix, "/log", "`"$activity`"", "`"$($fx.sln)`"" -PassThru
    }
    try { $dte = [System.Runtime.InteropServices.Marshal]::GetActiveObject("VisualStudio.DTE.$major.0") } catch { }
}
if (-not $dte) { Check "dte" $false "no DTE after 360 s"; Shot "no-dte"; exit 1 }
Retry { try { [void](Dismiss-FirstRun) } catch { }; if (-not ($dte.Solution.IsOpen -and $dte.Solution.Projects.Count -gt 0)) { throw "loading" } } 300 | Out-Null
Log "solution open after $([int]((Now) - $t0) / 1000) s: $($dte.Solution.FullName)"

$liveTxt = Join-Path (Split-Path $fx.project) 'obj\owen\live.txt'
# The editor must be REALIZED for its taggers to exist: a background tab is not. Close the
# start page VS opens after an update, open the Error List, and bring Use.cs to the front.
foreach ($w in @(Retry { $dte.Windows })) {
    try { if ($w.Caption -like "What's new*" -or $w.Caption -like "Start Page*") { Log "closing '$($w.Caption)'"; $w.Close() } } catch { }
}
Retry { $dte.ExecuteCommand('View.ErrorList') } | Out-Null
$window = Retry { $dte.ItemOperations.OpenFile($fx.use) }
Retry { $window.Activate() } | Out-Null
Retry { $window.Visible = $true } | Out-Null
$doc = Retry { $dte.ActiveDocument }
Log "active document: $($doc.FullName)"
# The extension's own word that its MEF parts were composed and its monitor runs (a .NET
# Framework assembly does not reliably show among the process's native modules).
$loaded = $null
for ($k = 0; $k -lt 120 -and -not $loaded; $k++) {
    if (Test-Path $trace) { $loaded = Select-String -Path $trace -Pattern '"Owen live analysis loaded"' -SimpleMatch -List }
    if (-not $loaded) { Start-Sleep -Seconds 1 }
}
if (-not $loaded) { Collect-Diagnostics }
Check "vsix-loaded" ($null -ne $loaded) "Owen.VisualStudio composed in devenv: $(if ($loaded) { $loaded.Line } else { 'no load line in the trace after 120 s' })"
Shot "opened"
if (-not $loaded) {
    # nothing below can pass without the extension in the process: stop with the evidence
    $results.failed = $true
    $results | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $Out 'results.json') -Encoding UTF8
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    exit 1
}
$td = Retry { $doc.Object('TextDocument') }

# ---- trace ------------------------------------------------------------------------------------
$script:traceSeen = 0
$script:events = New-Object System.Collections.ArrayList
function Poll-Trace {
    if (-not (Test-Path $trace)) { return }
    $lines = @(Get-Content $trace -Encoding UTF8)
    for ($i = $script:traceSeen; $i -lt $lines.Count; $i++) {
        if ($lines[$i].Trim().Length -gt 0) { [void]$script:events.Add(($lines[$i] | ConvertFrom-Json)) }
    }
    $script:traceSeen = $lines.Count
}
function Tags-Since($since) {
    Poll-Trace
    @($script:events | Where-Object { $_.kind -eq 'tags' -and $_.t -ge $since -and $_.data.file -like '*Use.cs' })
}
function Own002($tagsEvent) { @($tagsEvent.data.tags | Where-Object { $_.code -eq 'OWN002' }) }
function Wait-Tags($since, [scriptblock]$Want, [int]$Seconds = 60) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        foreach ($e in (Tags-Since $since)) { if (& $Want $e) { return $e } }
        Start-Sleep -Milliseconds 50
    }
    return $null
}

# ---- the Error List, as the user sees it ------------------------------------------------------
function Error-Rows {
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $byPid = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $proc.Id)
    $rows = @()
    foreach ($w in $root.FindAll([System.Windows.Automation.TreeScope]::Children, $byPid)) {
        $items = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants,
            (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::DataItem)))
        foreach ($item in $items) {
            $cells = @()
            foreach ($c in $item.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)) {
                $n = $c.Current.Name
                if ($n -and $cells -notcontains $n) { $cells += $n }
            }
            $text = ($cells -join ' | ')
            if ($text -match '\b(OWN\d{3}|OWEN[BV]\d{3}|CS\d{4})\b') {
                $rows += [pscustomobject]@{ Element = $item; Text = $text; Code = $Matches[1] }
            }
        }
    }
    return $rows
}
function Wait-Row($code, [bool]$present, [int]$Seconds = 60) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        $rows = @(Error-Rows | Where-Object { $_.Code -eq $code })
        if ($present -and $rows.Count -gt 0) { return $rows[0] }
        if (-not $present -and $rows.Count -eq 0) { return $true }
        Start-Sleep -Milliseconds 250
    }
    return $null
}

# ---- text edits through the editor (never saved) ---------------------------------------------
function All-Text { $ep = $td.StartPoint.CreateEditPoint(); return $ep.GetText($td.EndPoint) }
function Line-Of($needle) {
    $lines = (All-Text) -split "`r?`n"
    for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i].Trim() -eq $needle) { return $i + 1 } }
    return -1
}
function Insert-Line($before, $text) {
    $ep = $td.StartPoint.CreateEditPoint(); $ep.MoveToLineAndOffset($before, 1); $ep.Insert($text + "`r`n")
}
function Delete-Line($line) {
    $a = $td.StartPoint.CreateEditPoint(); $a.MoveToLineAndOffset($line, 1)
    $b = $td.StartPoint.CreateEditPoint(); $b.MoveToLineAndOffset($line + 1, 1)
    $a.Delete($b)
}
$stale = '            draft.Submit(now);'
$anchor = 'var submitted = draft.Submit(now);'
$region = 'OrderProtocol.WithDraft(order, draft =>'

# ---- K1: the project's first analysis, and an unsaved clean edit ------------------------------
Retry { if (-not (Test-Path $liveTxt)) { throw "no live.txt" } } 240 | Out-Null
Check "L0-live-request" (Test-Path $liveTxt) "the design-time build wrote $liveTxt (no build was run)"
$first = $null
$deadline = (Get-Date).AddSeconds(240)
while (-not $first -and (Get-Date) -lt $deadline) {
    Poll-Trace
    $first = @($script:events | Where-Object { $_.kind -eq 'publish' })[0]
    Start-Sleep -Milliseconds 250
}
if (-not $first) {
    Poll-Trace
    Log "trace tail: $(@($script:events | Select-Object -Last 15 | ForEach-Object { $_ | ConvertTo-Json -Compress -Depth 6 }) -join "`n")"
    Check "first-publication" $false "no Owen publication within 240 s of opening Use.cs"
    Shot "no-publication"
}
else {
    $own = @($first.data.entries | Where-Object { $_.code -like 'OWN*' })
    Check "K1-open-clean" ($own.Count -eq 0) "first publication (version $($first.data.version), $($first.data.timing.total) ms in the service): $(@($first.data.entries).Count) entries, OWN: $($own.Count)"
    $results.measurements.cold_open_to_first_publication_ms = $first.t - $t0
}
$snap = @($script:events | Where-Object { $_.kind -eq 'snapshot' })[0]
if ($snap) { Log "snapshot: documents $($snap.data.documents -join ', '); generated $($snap.data.generated -join ', ')" }

$since = Now
Insert-Line ((Line-Of $anchor) + 1) '            // an unsaved, harmless edit'
$cleanPub = $null
$deadline = (Get-Date).AddSeconds(60)
while (-not $cleanPub -and (Get-Date) -lt $deadline) {
    Poll-Trace
    $cleanPub = @($script:events | Where-Object { $_.kind -eq 'publish' -and $_.t -ge $since })[0]
    Start-Sleep -Milliseconds 100
}
Check "K1-unsaved-clean" ($cleanPub -and @($cleanPub.data.entries | Where-Object { $_.code -like 'OWN*' }).Count -eq 0 -and -not $doc.Saved) "a clean unsaved edit was analysed (version $($cleanPub.data.version)) with no OWN entry; document saved=$($doc.Saved)"
Delete-Line (Line-Of '// an unsaved, harmless edit')

# ---- K2: the second Submit, unsaved -----------------------------------------------------------
$since = Now
$insertAt = (Line-Of $anchor) + 1
Insert-Line $insertAt $stale
$regionLine = Line-Of $region
$hit = Wait-Tags $since { param($e) $o = Own002 $e; ($o | Where-Object { -not $_.primary -and $_.line -eq $insertAt }) -and ($o | Where-Object { $_.primary -and $_.line -eq $regionLine }) }
Check "K2-squiggle" ($null -ne $hit) ("tags on Use.cs after the edit: " + $(if ($hit) { (Own002 $hit | ForEach-Object { "$($_.line):$($_.column)+$($_.length) primary=$($_.primary) '$($_.text)'" }) -join '; ' } else { 'none with OWN002 at the region entry and on the inserted line' }))
if ($hit) { $results.measurements.k2_edit_to_squiggle_ms = $hit.t - $since }
Check "K2-unsaved" (-not $doc.Saved) "Use.cs is unsaved (Saved=$($doc.Saved)); the disk still has one Submit: $(-not ((Get-Content $fx.use -Raw) -match 'draft\.Submit\(now\);\s*\r?\n\s*draft\.Submit'))"
Start-Sleep -Milliseconds 700
Shot "k2-squiggle"
$row = Wait-Row 'OWN002' $true 60
Check "K2-error-list" ($null -ne $row) "Error List row: $(if ($row) { $row.Text } else { 'none' })"

# navigation: double-click the row, then read the caret
if ($row) {
    try { $row.Element.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select() } catch { }
    $r = $row.Element.Current.BoundingRectangle
    [Mouse]::SetForegroundWindow([IntPtr]$dte.MainWindow.HWnd) | Out-Null
    [Mouse]::DoubleClick([int]($r.X + [Math]::Min(200, $r.Width / 2)), [int]($r.Y + $r.Height / 2))
    Start-Sleep -Milliseconds 1500
    $active = Retry { $dte.ActiveDocument }
    $point = Retry { $active.Selection.ActivePoint }
    $expectColumn = ((Retry { (All-Text) -split "`r?`n" })[$regionLine - 1]).IndexOf('OrderProtocol') + 1
    Check "K2-navigation" ($active.FullName -eq $fx.use -and $point.Line -eq $regionLine -and $point.LineCharOffset -eq $expectColumn) "double-click -> $($active.Name) line $($point.Line) column $($point.LineCharOffset); expected Use.cs line $regionLine column $expectColumn (the core's location, §6)"
    Shot "k2-navigated"
}

# ---- P9: a CS error beside OWN002 -------------------------------------------------------------
$csAt = (Line-Of $region)
Insert-Line $csAt '        int notAString = "s";'
$cs = Wait-Row 'CS0029' $true 90
$own = @(Error-Rows | Where-Object { $_.Code -eq 'OWN002' })
Check "P9-cs-and-own" (($null -ne $cs) -and $own.Count -ge 1) "CS0029 row: $(if ($cs) { $cs.Text } else { 'none' }); OWN002 rows: $($own.Count)"
Shot "p9-cs-and-own"
Delete-Line (Line-Of 'int notAString = "s";')
[void](Wait-Row 'CS0029' $false 90)

# ---- K3: delete the line ------------------------------------------------------------------------
Start-Sleep -Milliseconds 1500
$since = Now
Delete-Line (Line-Of 'draft.Submit(now);')
$gone = Wait-Tags $since { param($e) (Own002 $e).Count -eq 0 }
$rowGone = Wait-Row 'OWN002' $false 60
Check "K3-disappears" (($null -ne $gone) -and ($rowGone -eq $true)) "after deleting the line: tags without OWN002 at +$(if ($gone) { $gone.t - $since } else { '?' }) ms; Error List row gone: $($rowGone -eq $true)"
Shot "k3-gone"

# ---- latency over repeated edits ---------------------------------------------------------------
$appear = @(); $vanish = @()
for ($i = 0; $i -lt $Repeats; $i++) {
    Start-Sleep -Milliseconds 800
    $since = Now
    Insert-Line ((Line-Of $anchor) + 1) $stale
    $e = Wait-Tags $since { param($x) (Own002 $x | Where-Object { -not $_.primary }).Count -gt 0 } 30
    if ($e) { $appear += ($e.t - $since) }
    Start-Sleep -Milliseconds 800
    $since = Now
    Delete-Line (Line-Of 'draft.Submit(now);')
    $e = Wait-Tags $since { param($x) (Own002 $x).Count -eq 0 } 30
    if ($e) { $vanish += ($e.t - $since) }
}
function P95($xs) { $s = @($xs | Sort-Object); if ($s.Count -eq 0) { return $null }; return $s[[Math]::Max(0, [int][Math]::Ceiling($s.Count * 0.95) - 1)] }
$results.measurements.edit_to_squiggle_ms = $appear
$results.measurements.edit_to_disappearance_ms = $vanish
Check "T-edit-to-squiggle" ($appear.Count -eq $Repeats -and (P95 $appear) -lt 1000) "edit -> squiggle over $($appear.Count)/$Repeats edits: p95 $(P95 $appear) ms (threshold 1000), all: $($appear -join ', ')"
Check "T-edit-to-disappearance" ($vanish.Count -eq $Repeats -and (P95 $vanish) -lt 1000) "edit -> disappearance over $($vanish.Count)/$Repeats edits: p95 $(P95 $vanish) ms (threshold 1000), all: $($vanish -join ', ')"

Poll-Trace
$ui = @($script:events | Where-Object { $_.kind -eq 'ui' } | ForEach-Object { $_.data.ms } | Measure-Object -Maximum).Maximum
$results.measurements.ui_thread_max_ms = $ui
Check "T-ui-thread" ($ui -lt 50) "longest Owen UI-thread handler: $ui ms (threshold 50)"
$pubs = @($script:events | Where-Object { $_.kind -eq 'publish' })
$service = @($pubs | ForEach-Object { $_.data.timing.total } | Where-Object { $_ })
$results.measurements.service_total_ms = $service
$results.measurements.publications = $pubs.Count
$ws = @($pubs | ForEach-Object { $_.data.timing.working_set_kb } | Where-Object { $_ })
if ($ws.Count -gt 0) { $results.measurements.service_working_set_kb_first_last = @($ws[0], $ws[-1]) }

# ---- nothing was saved or built ------------------------------------------------------------------
$projDir = Split-Path $fx.project
$dll = @(Get-ChildItem -Recurse -ErrorAction SilentlyContinue (Join-Path $projDir 'bin') -Filter 'LiveFixture.dll')
Check "no-build" ($dll.Count -eq 0 -and -not (Test-Path (Join-Path $projDir 'obj\owen\request.txt'))) "no LiveFixture.dll under bin/ ($($dll.Count)), no build-check request: the build host never ran"
Check "never-saved" ((Get-Content $fx.use -Raw) -eq (Get-Content (Join-Path $PSScriptRoot '..\..\tests\owen-live\LiveFixture\Use.cs.txt') -Raw)) "Use.cs on disk is byte-identical to the fixture"

$results.failed = $failed
$results | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $Out 'results.json') -Encoding UTF8
try { $dte.Documents.CloseAll(2) } catch { }
Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
Get-Process -Name dotnet -ErrorAction SilentlyContinue | ForEach-Object { Log "dotnet still running after devenv: pid $($_.Id)" }
if ($failed) { Log "VS acceptance: FAILED"; exit 1 }
Log "VS acceptance: all checks passed"
exit 0
