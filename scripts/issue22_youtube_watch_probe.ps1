<#
Optional, explicitly authorized development diagnostic, NOT a playback PASS.
Run with Windows PowerShell 5.1 -NoProfile -NonInteractive -STA.
Uses the actual packaged app, actual app consent UI, and a visible native Play
control. Never answers provider consent, signs in, injects JavaScript, changes
WebView2 flags, launches the TV helper directly, or alters a user installation.

Exit 0: PROGRESS_OBSERVED_VISUAL_REVIEW_PENDING or PROVIDER_BLOCKED recorded.
Exit 2: BLOCKED_INFRA / harness failure. The caller must also enforce a finite
outer process/step deadline because an OS accessibility provider can hang.
The progress outcome means Windows captures plus advancing UI telemetry;
independent review must establish visible picture. It never proves selected content,
audible output, standard-user acceptance, or an embedded-player identity fix.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RuntimePath,
    [Parameter(Mandatory=$true)][string]$BuildRecordPath,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{40}$')][string]$SourceCommit,
    [Parameter(Mandatory=$true)][ValidateSet('YE7VzlLtp-4')][string]$AuthorizedFixture,
    [ValidateRange(90,240)][int]$MaxSeconds = 210
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms, System.Drawing
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class PulseWatchInput {
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X,Y; }
    [StructLayout(LayoutKind.Sequential)] public struct MOUSEINPUT { public int dx,dy; public uint data,flags,time; public UIntPtr extra; }
    [StructLayout(LayoutKind.Explicit)] public struct UNION { [FieldOffset(0)] public MOUSEINPUT mouse; }
    [StructLayout(LayoutKind.Sequential)] public struct INPUT { public uint type; public UNION value; }
    public delegate bool EnumChildProc(IntPtr hwnd,IntPtr extra);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent,EnumChildProc cb,IntPtr extra);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd,out uint pid);
    [DllImport("user32.dll")] public static extern IntPtr GetParent(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool IsChild(IntPtr parent,IntPtr child);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT point);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
    [DllImport("user32.dll")] public static extern uint SendInput(uint count,INPUT[] values,int size);
    [DllImport("kernel32.dll")] static extern IntPtr OpenProcess(uint access,bool inherit,int pid);
    [DllImport("advapi32.dll")] static extern bool OpenProcessToken(IntPtr process,uint access,out IntPtr token);
    [DllImport("advapi32.dll")] static extern bool GetTokenInformation(IntPtr token,int kind,out int value,int size,out int needed);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    public static int[] Token(int pid) {
        IntPtr p=OpenProcess(0x1000,false,pid),t=IntPtr.Zero;
        if(p==IntPtr.Zero) throw new InvalidOperationException("token_query_failed");
        try {
            if(!OpenProcessToken(p,8,out t)) throw new InvalidOperationException("token_query_failed");
            int elevated,kind,n;
            if(!GetTokenInformation(t,20,out elevated,4,out n) || !GetTokenInformation(t,18,out kind,4,out n))
                throw new InvalidOperationException("token_query_failed");
            return new[]{elevated,kind};
        } finally { if(t!=IntPtr.Zero)CloseHandle(t); CloseHandle(p); }
    }
    public static bool Click(int x,int y) {
        if(!SetCursorPos(x,y)) return false;
        INPUT[] values=new INPUT[2];
        values[0].type=0;values[0].value.mouse.flags=2;
        values[1].type=0;values[1].value.mouse.flags=4;
        return SendInput(2,values,Marshal.SizeOf(typeof(INPUT)))==2;
    }
}
'@

$watchClock = [Diagnostics.Stopwatch]::StartNew()
$watchStage = 'preflight'
$watchOwned = @{}
$watchApp = $null
$watchWindow = $null
$watchSurface = $null
$watchOutputCreated = $false
$watchApprovedPaths = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
$watchOwnershipIssues = New-Object 'System.Collections.Generic.HashSet[string]'
$watchExit = 2
$watchReceipt = [ordered]@{
    schema=1; tier='DIAGNOSTIC_ONLY'; outcome='BLOCKED_INFRA'; stage='preflight'; reason='not_completed'
    source_commit=$SourceCommit; fixture=$AuthorizedFixture; mode='normal_watch_page'
    source_identity_verified=$false
    authorized_action='QA automation of the actual app network-consent dialog and visible Play; not an owner click'
    started_at_utc=[DateTime]::UtcNow.ToString('o'); captures=@(); observations=@()
    standard_user_verified=$false; audible_output_verified=$false; selected_content_verified=$false
    embedded_identity_verified=$false; independent_visual_review_required=$true
    provider_consent_accepted=$false; forced_cleanup=$false; cleanup_complete=$false
    ownership_uncertainty=$false; ownership_issue_count=0; ownership_issue_reasons=@()
}

function Block([string]$Reason,[string]$Kind='BLOCKED_INFRA') {
    $exception = New-Object InvalidOperationException($Reason)
    $exception.Data['probe_reason']=$Reason; $exception.Data['probe_kind']=$Kind
    throw $exception
}
function Tick {
    if($watchClock.Elapsed.TotalSeconds -gt $MaxSeconds){Block 'finite_deadline_reached'}
    Start-Sleep -Milliseconds 160
}
function Record-OwnershipIssue([string]$Reason,[int]$ProcessId) {
    # Keep uncertainty sticky. No raw exception, executable path, or process
    # metadata is exported. A later empty result must not turn unknown to gone.
    $watchReceipt.ownership_uncertainty=$true
    if($watchOwnershipIssues.Count -lt 128){[void]$watchOwnershipIssues.Add($Reason+':'+$ProcessId)}
    $watchReceipt.ownership_issue_count=$watchOwnershipIssues.Count
    if($Reason -notin $watchReceipt.ownership_issue_reasons -and $watchReceipt.ownership_issue_reasons.Count -lt 16){$watchReceipt.ownership_issue_reasons+=,$Reason}
}
function Refuse-Ownership([string]$Reason,[int]$ProcessId) {
    Record-OwnershipIssue $Reason $ProcessId
    Block $Reason
}
function Remember-Process($Process) {
    try {$path=$Process.Path;$started=$Process.StartTime.ToUniversalTime().Ticks}
    catch {Refuse-Ownership 'owned_process_metadata_unknown' $Process.Id}
    if([string]::IsNullOrWhiteSpace($path)){Refuse-Ownership 'owned_executable_path_unknown' $Process.Id}
    if(-not $watchApprovedPaths.Contains($path)) {
        if([IO.Path]::GetFileName($path) -ne 'msedgewebview2.exe'){Refuse-Ownership 'unexpected_owned_process_executable' $Process.Id}
        try {$signature=Get-AuthenticodeSignature -LiteralPath $path -ErrorAction Stop}
        catch {Refuse-Ownership 'webview_child_signature_query_failed' $Process.Id}
        if($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch '(?:^|,\s*)O=Microsoft Corporation(?:,|$)'){Refuse-Ownership 'webview_child_signature_unverified' $Process.Id}
        [void]$watchApprovedPaths.Add($path)
    }
    $watchOwned[[string]$Process.Id]=[ordered]@{id=$Process.Id;start=$started;path=$path}
}
function Refresh-Owned {
    for($depth=0;$depth -lt 4;$depth++) {
        $before=$watchOwned.Count
        foreach($parent in @($watchOwned.Values)) {
            if($null -eq (Current-Process $parent)){continue}
            try {$children=@(Get-CimInstance Win32_Process -Filter ("ParentProcessId="+$parent.id) -ErrorAction Stop)}
            catch {Refuse-Ownership 'owned_child_enumeration_failed' $parent.id}
            foreach($item in $children) {
                try {$child=[Diagnostics.Process]::GetProcessById([int]$item.ProcessId)}
                catch [System.ArgumentException] {continue} # Explicit PID no longer exists.
                catch {Refuse-Ownership 'child_pid_query_unknown' $item.ProcessId}
                try {$childStarted=$child.StartTime.ToUniversalTime().Ticks}
                catch {Refuse-Ownership 'child_process_metadata_unknown' $item.ProcessId}
                if($childStarted -lt $parent.start){Refuse-Ownership 'child_ownership_predates_parent' $item.ProcessId}
                # Do not catch-and-ignore a rejection raised by this admission.
                Remember-Process $child
            }
        }
        if($watchOwned.Count -eq $before){break}
        if($watchOwned.Count -gt 64){Refuse-Ownership 'owned_process_tree_unexpectedly_large' 0}
    }
}
function Current-Process($Record) {
    try {$current=[Diagnostics.Process]::GetProcessById([int]$Record.id)}
    catch [System.ArgumentException] {return $null} # Explicit PID no longer exists.
    catch {Record-OwnershipIssue 'owned_pid_query_unknown' $Record.id;return $null}
    try {$started=$current.StartTime.ToUniversalTime().Ticks}
    catch {Record-OwnershipIssue 'owned_process_metadata_unknown' $Record.id;return $null}
    if($started -ne $Record.start){return $null} # PID recycled: original exited; never touch replacement.
    try {$path=$current.Path}
    catch {Record-OwnershipIssue 'owned_executable_path_unknown' $Record.id;return $null}
    if([string]::IsNullOrWhiteSpace($path) -or $path -ne $Record.path){
        Record-OwnershipIssue 'owned_executable_identity_unknown' $Record.id
        return $null
    }
    return $current
}
function Find-Named($Root,[string[]]$Names,[int]$Owner=0) {
    $found=@()
    foreach($name in $Names) {
        $condition=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,$name)
        foreach($element in $Root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)) {
            if($Owner -eq 0 -or $element.Current.ProcessId -eq $Owner){$found+=,$element}
        }
    }
    $visible=@($found | Where-Object {-not $_.Current.IsOffscreen -and $_.Current.IsEnabled})
    if($visible.Count -gt 1){Block 'ambiguous_accessibility_target'}
    if($visible.Count -eq 1){return $visible[0]}
    if($found.Count -eq 1) {
        try {$found[0].SetFocus()} catch {}
        Tick
        if(-not $found[0].Current.IsOffscreen -and $found[0].Current.IsEnabled){return $found[0]}
    }
    return $null
}
function Need-Named($Root,[string[]]$Names,[int]$Owner=0,[int]$Seconds=8) {
    $until=[Math]::Min($MaxSeconds,$watchClock.Elapsed.TotalSeconds+$Seconds)
    do {
        $element=Find-Named $Root $Names $Owner
        if($null -ne $element){return $element}
        Tick
    } while($watchClock.Elapsed.TotalSeconds -lt $until)
    Block 'required_visible_control_unavailable'
}
function Click-Observed($Element,[IntPtr]$RootHandle) {
    if($Element.Current.IsOffscreen -or -not $Element.Current.IsEnabled){Block 'target_not_visible_enabled'}
    $r=$Element.Current.BoundingRectangle
    if($r.IsEmpty -or $r.Width -lt 3 -or $r.Height -lt 3){Block 'target_rectangle_unavailable'}
    $x=[int]($r.X+$r.Width/2);$y=[int]($r.Y+$r.Height/2)
    [void][PulseWatchInput]::SetForegroundWindow($RootHandle)
    Tick
    $point=New-Object PulseWatchInput+POINT;$point.X=$x;$point.Y=$y
    $hit=[PulseWatchInput]::WindowFromPoint($point)
    if($hit -ne $RootHandle -and -not [PulseWatchInput]::IsChild($RootHandle,$hit)){Block 'observed_target_occluded'}
    if(-not [PulseWatchInput]::Click($x,$y)){Block 'native_click_failed'}
    Tick
}
function Snapshot([string]$Name,[bool]$NativeOnly=$false) {
    if(-not $watchOutputCreated -or $null -eq $watchWindow){return $null}
    $r=$watchWindow.Current.BoundingRectangle
    $desktop=[Windows.Forms.SystemInformation]::VirtualScreen
    $rect=[Drawing.Rectangle]::Intersect([Drawing.Rectangle]::FromLTRB([int]$r.Left,[int]$r.Top,[int]$r.Right,[int]$r.Bottom),$desktop)
    if($NativeOnly) {
        if($null -eq $watchSurface){Block 'native_capture_surface_unavailable'}
        $nativeRect=$watchSurface.Current.BoundingRectangle
        $rect=[Drawing.Rectangle]::Intersect($rect,[Drawing.Rectangle]::FromLTRB([int]$nativeRect.Left,[int]$nativeRect.Top,[int]$nativeRect.Right,[int]$nativeRect.Bottom))
    }
    if($rect.Width -lt 200 -or $rect.Height -lt 150){Block 'visible_capture_unavailable'}
    $bitmap=New-Object Drawing.Bitmap($rect.Width,$rect.Height)
    $graphics=[Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen($rect.Location,[Drawing.Point]::Empty,$rect.Size)
        $path=Join-Path $watchOutput ($Name+'.png')
        $bitmap.Save($path,[Drawing.Imaging.ImageFormat]::Png)
        $colors=New-Object 'System.Collections.Generic.HashSet[int]'
        for($x=10;$x -lt $bitmap.Width;$x+=37){for($y=10;$y -lt $bitmap.Height;$y+=31){[void]$colors.Add($bitmap.GetPixel($x,$y).ToArgb())}}
        $record=[ordered]@{file=($Name+'.png');scope=$(if($NativeOnly){'owned_native_surface'}else{'app'});sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant();width=$bitmap.Width;height=$bitmap.Height;sample_colors=$colors.Count;elapsed_seconds=[Math]::Round($watchClock.Elapsed.TotalSeconds,2)}
        $watchReceipt.captures+=,$record
        return $record
    } finally {$graphics.Dispose();$bitmap.Dispose()}
}
function Provider-Blocked($Root) {
    # Read only inside this owned player. Never export the raw accessible text.
    $dialogs=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Window)
    foreach($dialog in $Root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$dialogs)) {
        if(-not $dialog.Current.IsOffscreen){Block 'provider_dialog_observed' 'PROVIDER_BLOCKED'}
    }
    $condition=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Text)
    $count=0
    foreach($element in $Root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)) {
        if(++$count -gt 160){Block 'provider_accessibility_tree_too_large'}
        if($element.Current.IsOffscreen){continue}
        $name=[string]$element.Current.Name
        if($name -match '(?i)before you continue|confirm.{0,20}(?:age|bot)|sign in to (?:watch|confirm)|not available in your country|video unavailable|error code\s*:?\s*(?:153|101|150)') {Block 'provider_prompt_or_denial_observed' 'PROVIDER_BLOCKED'}
    }
    foreach($name in @('Accept all','Reject all','I agree','Accept cookies')) {
        if($null -ne (Find-Named $Root @($name))){Block 'provider_consent_ui_observed' 'PROVIDER_BLOCKED'}
    }
}
function Invoke-ProviderControl($Root,[string[]]$Names) {
    Provider-Blocked $Root
    $element=Need-Named $Root $Names 0 10
    Provider-Blocked $Root
    if($element.Current.IsOffscreen -or -not $element.Current.IsEnabled){Block 'provider_control_not_visible_enabled'}
    $pattern=$null
    if(-not $element.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)){Block 'provider_control_not_accessibly_invokable'}
    # Invoke only this exact Play/Pause control. No coordinate fallback: a
    # native HWND hit-test cannot identify an overlapping HTML consent panel.
    $pattern.Invoke()
    Tick
}
function Read-Observation {
    $label=Find-Named $watchWindow @('TV codec and renderer diagnostics') $watchApp.Id
    if($null -eq $label){return $null}
    $text=''
    $pattern=$null
    if($label.TryGetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern,[ref]$pattern)){$text=$pattern.DocumentRange.GetText(1600)}
    elseif($label.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$pattern)){$text=$pattern.Current.Value}
    elseif($label.TryGetCurrentPattern([System.Windows.Automation.LegacyIAccessiblePattern]::Pattern,[ref]$pattern)){$text=$pattern.Current.Value}
    $observation=[ordered]@{elapsed_seconds=[Math]::Round($watchClock.Elapsed.TotalSeconds,2);time=$null;frames=$null;state='unknown';provider_code=$null}
    if($text -match 'time\s+(\d+(?:\.\d+)?)s'){$observation.time=[double]::Parse($Matches[1],[Globalization.CultureInfo]::InvariantCulture)}
    if($text -match 'decoded frames\s+(\d+)'){$observation.frames=[long]$Matches[1]}
    if($text -match '(?i)awaiting.play|press play'){$observation.state='awaiting_play'}
    if($text -match '(?i)paused'){$observation.state='paused'}
    if($text -match '(?i)buffering|stalled'){$observation.state='buffering_or_stalled'}
    if($text -match '(?i)(?:error|code)[^0-9]{0,12}(153|150|101|100|5|2)\b'){$observation.provider_code=[int]$Matches[1]}
    if($text -match '(?i)native WebView2 error|provider.*unavailable|unapproved.*redirect') {Block 'app_reported_player_denial' 'PROVIDER_BLOCKED'}
    $watchReceipt.observations+=,$observation
    return $observation
}

try {
    $runtime=(Resolve-Path -LiteralPath $RuntimePath).Path
    $recordPath=(Resolve-Path -LiteralPath $BuildRecordPath).Path
    $watchOutput=[IO.Path]::GetFullPath($OutputDirectory)
    if(Test-Path -LiteralPath $watchOutput){Block 'evidence_directory_must_be_new'}
    if($watchOutput.StartsWith($runtime.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)){Block 'evidence_must_be_outside_runtime'}
    [void](New-Item -ItemType Directory -Path $watchOutput)
    $watchOutputCreated=$true
    # Preserve incomplete provenance even if an OS accessibility call hangs
    # and the caller's finite outer deadline terminates this script.
    $watchReceipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $watchOutput 'WATCH_PROBE.json') -Encoding UTF8
    $build=Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
    if($build.source_commit -ne $SourceCommit -or $build.source_worktree_dirty -ne $false){Block 'build_source_identity_mismatch'}
    $exe=Join-Path $runtime 'GlobalPulse.exe';$helper=Join-Path $runtime 'tv\GlobalPulse.TV.exe'
    $manifestPath=Join-Path $runtime 'MANIFEST.json'
    $manifest=Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if($manifest.source.git_commit -ne $SourceCommit){Block 'manifest_source_identity_mismatch'}
    [void]$watchApprovedPaths.Add($exe)
    [void]$watchApprovedPaths.Add($helper)
    foreach($target in @(@{path=$exe;relative='GlobalPulse.exe'},@{path=$helper;relative='tv/GlobalPulse.TV.exe'})) {
        $expected=@($manifest.files | Where-Object {($_.path -replace '\\','/') -eq $target.relative})
        if($expected.Count -ne 1 -or -not (Test-Path -LiteralPath $target.path -PathType Leaf)){Block 'packaged_payload_missing'}
        if((Get-Item -LiteralPath $target.path).Length -ne $expected[0].bytes -or (Get-FileHash -LiteralPath $target.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected[0].sha256){Block 'packaged_payload_hash_mismatch'}
    }
    $watchReceipt.build_record_sha256=(Get-FileHash -LiteralPath $recordPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $watchReceipt.manifest_sha256=(Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $watchReceipt.app_sha256=(Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
    $watchReceipt.helper_sha256=(Get-FileHash -LiteralPath $helper -Algorithm SHA256).Hash.ToLowerInvariant()
    $watchReceipt.source_identity_verified=$true
    $watchReceipt.driver_token=@([PulseWatchInput]::Token($PID))
    $watchReceipt.interactive=[Environment]::UserInteractive
    $watchReceipt.session_id=[Diagnostics.Process]::GetCurrentProcess().SessionId
    if(-not $watchReceipt.interactive -or $watchReceipt.session_id -le 0){Block 'interactive_desktop_unavailable'}
    $watchPriorProfiles=@(Get-ChildItem -LiteralPath ([IO.Path]::GetTempPath()) -Directory | Where-Object {$_.Name -match '^GlobalPulse-TV-[a-f0-9]{32}$'} | ForEach-Object {$_.FullName})
    $data=Join-Path $watchOutput 'isolated-app-data'
    $watchStage='launch_packaged_app'
    $watchApp=Start-Process -FilePath $exe -ArgumentList @('--no-start','--skip-setup','--data-dir',('"'+$data+'"')) -PassThru
    Remember-Process $watchApp
    $until=$watchClock.Elapsed.TotalSeconds+25
    $dashboardTitle='Global Pulse '+[char]0x2014+' Dietrich AI Labs'
    $dashboardReady=$false
    do {
        $watchApp.Refresh()
        if($watchApp.HasExited){Block 'packaged_app_exited'}
        $dashboardReady=($watchApp.MainWindowHandle -ne 0 -and $watchApp.MainWindowTitle -eq $dashboardTitle -and [PulseWatchInput]::IsWindowVisible($watchApp.MainWindowHandle) -and [PulseWatchInput]::IsWindowEnabled($watchApp.MainWindowHandle))
        if($dashboardReady){break}
        Tick
    } while($watchClock.Elapsed.TotalSeconds -lt $until)
    if(-not $dashboardReady){Block 'actual_dashboard_window_unavailable'}
    $watchReceipt.app_token=@([PulseWatchInput]::Token($watchApp.Id))
    $watchWindow=[System.Windows.Automation.AutomationElement]::FromHandle($watchApp.MainWindowHandle)
    $maximize=Find-Named $watchWindow @('Maximize or restore') $watchApp.Id
    if($null -ne $maximize){Click-Observed $maximize $watchApp.MainWindowHandle}
    [void](Snapshot '01-app-before-network')
    $watchStage='select_exact_fixture'
    $edit=Need-Named $watchWindow @('Add a specific YouTube video') $watchApp.Id
    Click-Observed $edit $watchApp.MainWindowHandle
    $value=$edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    $value.SetValue('https://www.youtube.com/watch?v='+$AuthorizedFixture)
    Click-Observed (Need-Named $watchWindow @('Add video') $watchApp.Id) $watchApp.MainWindowHandle
    $combo=Need-Named $watchWindow @('Television channel or saved video') $watchApp.Id
    Click-Observed $combo $watchApp.MainWindowHandle
    $savedName='Your video '+[char]0xB7+' '+$AuthorizedFixture
    $saved=Need-Named ([System.Windows.Automation.AutomationElement]::RootElement) @($savedName) $watchApp.Id
    $saved.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()
    Tick
    $watchStage='actual_app_consent'
    Click-Observed (Need-Named $watchWindow @("Try the selected video in YouTube's normal watch page, with consent") $watchApp.Id) $watchApp.MainWindowHandle
    $dialog=Need-Named ([System.Windows.Automation.AutomationElement]::RootElement) @('Try official YouTube watch page inside Pulse?') $watchApp.Id
    $dialogHandle=[IntPtr]$dialog.Current.NativeWindowHandle
    if($dialogHandle -eq [IntPtr]::Zero){Block 'app_consent_window_handle_missing'}
    [void](Snapshot '02-app-network-consent')
    Click-Observed (Need-Named $dialog @('Yes','&Yes') $watchApp.Id) $dialogHandle
    $watchReceipt.app_consent_ui_clicked=$true
    $watchStage='native_player_visible'
    $until=$watchClock.Elapsed.TotalSeconds+30
    $native=$null
    do {
        Refresh-Owned
        $candidates=@(Get-CimInstance Win32_Process -Filter ("ParentProcessId="+$watchApp.Id) | Where-Object {$_.ExecutablePath -eq $helper})
        if($candidates.Count -eq 1){$native=Get-Process -Id $candidates[0].ProcessId;Remember-Process $native;break}
        if($candidates.Count -gt 1){Block 'ambiguous_native_helper'}
        Tick
    } while($watchClock.Elapsed.TotalSeconds -lt $until)
    if($null -eq $native){Block 'native_helper_not_observed'}
    $watchReceipt.helper_token=@([PulseWatchInput]::Token($native.Id))
    $handles=New-Object 'System.Collections.Generic.List[System.IntPtr]'
    $callback=[PulseWatchInput+EnumChildProc]{param($hwnd,$unused);[uint32]$owner=0;[void][PulseWatchInput]::GetWindowThreadProcessId($hwnd,[ref]$owner);if($owner -eq $native.Id -and [PulseWatchInput]::IsWindowVisible($hwnd)){[void]$handles.Add($hwnd)};return $true}
    $until=$watchClock.Elapsed.TotalSeconds+25
    do {
        if($null -eq (Current-Process $watchOwned[[string]$native.Id])){Block 'native_helper_exited_before_attach'}
        $handles.Clear()
        [void][PulseWatchInput]::EnumChildWindows($watchApp.MainWindowHandle,$callback,[IntPtr]::Zero)
        $top=@($handles | Where-Object {-not $handles.Contains([PulseWatchInput]::GetParent($_))})
        if($top.Count -gt 1){Block 'ambiguous_native_child_surfaces'}
        if($top.Count -eq 1){break}
        Tick
    } while($watchClock.Elapsed.TotalSeconds -lt $until)
    if($top.Count -ne 1){Block 'owned_native_surface_not_unique'}
    $watchSurface=[System.Windows.Automation.AutomationElement]::FromHandle($top[0])
    $watchCreatedProfiles=@(Get-ChildItem -LiteralPath ([IO.Path]::GetTempPath()) -Directory | Where-Object {$_.Name -match '^GlobalPulse-TV-[a-f0-9]{32}$' -and $_.FullName -notin $watchPriorProfiles} | ForEach-Object {$_.FullName})
    $watchReceipt.new_private_profile_count=$watchCreatedProfiles.Count
    [void](Snapshot '03-native-before-play')
    Provider-Blocked $watchSurface
    # Demonstrate the new deliberate-pre-Play idle behavior without autoplay.
    $watchStage='deliberate_pre_play_wait'
    $idleUntil=$watchClock.Elapsed.TotalSeconds+47
    while($watchClock.Elapsed.TotalSeconds -lt $idleUntil){Provider-Blocked $watchSurface;Tick}
    if($native.HasExited){Block 'native_player_closed_before_play' 'PROVIDER_BLOCKED'}
    $watchReceipt.deliberate_pre_play_wait_seconds=47
    $watchStage='visible_play'
    Provider-Blocked $watchSurface
    [void](Need-Named $watchSurface @('Play','Play (k)') 0 10)
    [void](Snapshot '04-play-target-visible')
    Invoke-ProviderControl $watchSurface @('Play','Play (k)')
    $first=$null;$second=$null;$until=$watchClock.Elapsed.TotalSeconds+35
    do {
        Provider-Blocked $watchSurface
        $sample=Read-Observation
        if($null -ne $sample -and $null -ne $sample.time -and $sample.frames -gt 0) {
            if($null -eq $first){$first=$sample;[void](Snapshot '05-first-progress');[void](Snapshot '05-first-progress-native' $true)}
            elseif($sample.time -gt $first.time+1 -and $sample.frames -gt $first.frames){$second=$sample;[void](Snapshot '06-later-progress');[void](Snapshot '06-later-progress-native' $true);break}
        }
        Tick
    } while($watchClock.Elapsed.TotalSeconds -lt $until)
    if($null -eq $second){Block 'advancing_ui_telemetry_not_demonstrated'}
    $watchStage='pause_resume'
    Invoke-ProviderControl $watchSurface @('Pause','Pause (k)')
    [void](Snapshot '07-paused')
    $watchReceipt.pause_control_clicked=$true
    Provider-Blocked $watchSurface
    Invoke-ProviderControl $watchSurface @('Play','Play (k)')
    $watchReceipt.resume_control_clicked=$true
    $watchStage='unmute_control'
    $volume=Find-Named $watchWindow @('Television volume') $watchApp.Id
    $mute=Find-Named $watchWindow @('Mute television audio') $watchApp.Id
    $range=$null;$toggle=$null
    if($null -ne $volume -and $null -ne $mute -and $volume.TryGetCurrentPattern([System.Windows.Automation.RangeValuePattern]::Pattern,[ref]$range) -and $mute.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern,[ref]$toggle)) {
        $range.SetValue(10)
        if($range.Current.Value -eq 10 -and $toggle.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::On) {
            $watchReceipt.unmute_attempted=$true
            Click-Observed $mute $watchApp.MainWindowHandle
            $watchReceipt.unmute_control_clicked=($toggle.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::Off)
            $watchReceipt.requested_volume_percent=10
        }
    }
    [void](Snapshot '08-resumed-unmute-requested')
    $watchReceipt.outcome='PROGRESS_OBSERVED_VISUAL_REVIEW_PENDING'
    $watchReceipt.reason='advancing_ui_telemetry_recorded_native_captures_require_independent_review'
    $watchExit=0
} catch {
    $watchReceipt.outcome='BLOCKED_INFRA'
    $watchReceipt.reason='harness_exception_'+$_.Exception.GetType().Name
    if($_.Exception.Data.Contains('probe_reason')){$watchReceipt.reason=$_.Exception.Data['probe_reason'];$watchReceipt.outcome=$_.Exception.Data['probe_kind']}
    if($watchReceipt.outcome -eq 'PROVIDER_BLOCKED'){$watchExit=0}
    try {[void](Snapshot '09-blocked-observation')} catch {}
} finally {
    $watchReceipt.stage=$watchStage
    try {
        if($null -ne $watchWindow -and $null -ne $watchApp -and -not $watchApp.HasExited) {
            Refresh-Owned
            $mute=Find-Named $watchWindow @('Mute television audio') $watchApp.Id
            $toggle=$null
            if($null -ne $mute -and $mute.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern,[ref]$toggle)) {
                if($toggle.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::Off){Click-Observed $mute $watchApp.MainWindowHandle}
                $watchReceipt.remuted_before_stop=($toggle.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::On)
            }
            $stop=Find-Named $watchWindow @('Stop selected media source') $watchApp.Id
            if($null -ne $stop){Click-Observed $stop $watchApp.MainWindowHandle;$watchReceipt.stop_control_clicked=$true}
            $settings=Find-Named $watchWindow @('Settings') $watchApp.Id
            if($null -ne $settings){Click-Observed $settings $watchApp.MainWindowHandle}
            $exit=Find-Named $watchWindow @('Exit Completely') $watchApp.Id
            if($null -ne $exit){Click-Observed $exit $watchApp.MainWindowHandle}
        }
    } catch {$watchReceipt.cleanup_ui_unavailable=$true}
    $cleanupUntil=[Diagnostics.Stopwatch]::StartNew()
    do {
        $alive=@($watchOwned.Values | ForEach-Object {Current-Process $_} | Where-Object {$null -ne $_})
        if($alive.Count -eq 0){break}
        Start-Sleep -Milliseconds 200
    } while($cleanupUntil.Elapsed.TotalSeconds -lt 8)
    foreach($owned in @($watchOwned.Values)) {
        $process=Current-Process $owned
        if($null -ne $process){$watchReceipt.forced_cleanup=$true;try {$process.Kill()} catch {}}
    }
    Start-Sleep -Milliseconds 300
    $remaining=@($watchOwned.Values | ForEach-Object {Current-Process $_} | Where-Object {$null -ne $_})
    $watchReceipt.cleanup_complete=($remaining.Count -eq 0 -and -not $watchReceipt.ownership_uncertainty)
    if($watchReceipt.forced_cleanup -or -not $watchReceipt.cleanup_complete){$watchReceipt.outcome='BLOCKED_INFRA';$watchReceipt.reason='owned_process_cleanup_not_clean';$watchExit=2}
    if($watchReceipt.ownership_uncertainty){$watchReceipt.outcome='BLOCKED_INFRA';$watchReceipt.reason='owned_process_cleanup_uncertain';$watchExit=2}
    if(Get-Variable watchCreatedProfiles -ErrorAction SilentlyContinue) {
        $remainingProfiles=@($watchCreatedProfiles | Where-Object {Test-Path -LiteralPath $_ -PathType Container})
        $watchReceipt.private_profile_cleanup_observed=($watchCreatedProfiles.Count -gt 0 -and $remainingProfiles.Count -eq 0)
        $watchReceipt.remaining_observed_profile_count=$remainingProfiles.Count
    }
    $watchReceipt.finished_at_utc=[DateTime]::UtcNow.ToString('o')
    if($watchOutputCreated -and (Test-Path -LiteralPath $watchOutput -PathType Container)) {
        $watchReceipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $watchOutput 'WATCH_PROBE.json') -Encoding UTF8
    }
    Write-Host ('YOUTUBE_WATCH_DIAGNOSTIC='+$watchReceipt.outcome+'; STAGE='+$watchReceipt.stage+'; REASON='+$watchReceipt.reason)
}
exit $watchExit
