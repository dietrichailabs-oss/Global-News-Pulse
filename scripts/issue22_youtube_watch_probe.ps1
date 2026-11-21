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
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left,Top,Right,Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct MOUSEINPUT { public int dx,dy; public uint data,flags,time; public UIntPtr extra; }
    [StructLayout(LayoutKind.Explicit)] public struct UNION { [FieldOffset(0)] public MOUSEINPUT mouse; }
    [StructLayout(LayoutKind.Sequential)] public struct INPUT { public uint type; public UNION value; }
    public delegate bool EnumChildProc(IntPtr hwnd,IntPtr extra);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent,EnumChildProc cb,IntPtr extra);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd,out uint pid);
    [DllImport("user32.dll")] public static extern IntPtr GetParent(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr hwnd,uint flags);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hwnd,out RECT rect);
    [DllImport("user32.dll")] public static extern bool IsChild(IntPtr parent,IntPtr child);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hwnd,int command);
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
    public static bool Drag(int x0,int y0,int x1,int y1) {
        if(!SetCursorPos(x0,y0)) return false;
        INPUT[] down=new INPUT[1],up=new INPUT[1];
        down[0].type=0;down[0].value.mouse.flags=2;
        up[0].type=0;up[0].value.mouse.flags=4;
        int size=Marshal.SizeOf(typeof(INPUT));
        if(SendInput(1,down,size)!=1) return false;
        bool moved=true,released=false;
        try {
            for(int step=1;step<=8;step++) {
                if(!SetCursorPos(x0+(x1-x0)*step/8,y0+(y1-y0)*step/8)){moved=false;break;}
                System.Threading.Thread.Sleep(25);
            }
        } finally { released=SendInput(1,up,size)==1; }
        return moved && released;
    }
}
'@

$watchClock = [Diagnostics.Stopwatch]::StartNew()
$watchStage = 'preflight'
$watchOwned = @{}
$watchApp = $null
$watchWindow = $null
$watchTv = $null
$watchSurface = $null
$watchOutputCreated = $false
$watchApprovedPaths = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
$watchOwnershipIssues = New-Object 'System.Collections.Generic.HashSet[string]'
$watchExplicitExits = New-Object 'System.Collections.Generic.HashSet[string]'
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
    ownership_issue_details=@(); explicit_owned_exit_count=0; explicit_owned_exits=@()
    initial_failure=$null; cleanup_failures=@(); last_ui_operation='preflight'; app_scroll_actions=0
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
function Owned-Role($Record) {
    if($null -eq $Record){return 'unclassified'}
    switch([IO.Path]::GetFileName($Record.path)) {
        'GlobalPulse.exe' {return 'app'}
        'GlobalPulse.TV.exe' {return 'native_helper'}
        'msedgewebview2.exe' {return 'webview_child'}
        default {return 'unclassified'}
    }
}
function Record-OwnershipIssue([string]$Reason,[int]$ProcessId,[string]$Detail='unavailable') {
    # Keep uncertainty sticky. No raw exception, executable path, or process
    # metadata is exported. A later empty result must not turn unknown to gone.
    $watchReceipt.ownership_uncertainty=$true
    $newIssue=$false
    if($watchOwnershipIssues.Count -lt 128){$newIssue=$watchOwnershipIssues.Add($Reason+':'+$ProcessId)}
    $watchReceipt.ownership_issue_count=$watchOwnershipIssues.Count
    if($Reason -notin $watchReceipt.ownership_issue_reasons -and $watchReceipt.ownership_issue_reasons.Count -lt 16){$watchReceipt.ownership_issue_reasons+=,$Reason}
    if($newIssue -and $watchReceipt.ownership_issue_details.Count -lt 16){
        $record=if($watchOwned.ContainsKey([string]$ProcessId)){$watchOwned[[string]$ProcessId]}else{$null}
        $watchReceipt.ownership_issue_details+=,[ordered]@{role=(Owned-Role $record);reason=$Reason;detail=$Detail;operation=$watchReceipt.last_ui_operation;elapsed_seconds=[Math]::Round($watchClock.Elapsed.TotalSeconds,2)}
    }
}
function Read-OwnedExitState($Process,$Record,[string]$Phase) {
    # Only an explicit true on this SAME acquired Process instance is exit
    # evidence. Do not acquire a broader Handle or query a replacement PID.
    try {$exited=$Process.HasExited}
    catch {Record-OwnershipIssue 'owned_exit_query_unknown' $Record.id $Phase;return $null}
    if($exited -eq $true) {
        $key=[string]$Record.id+':'+[string]$Record.start
        if($watchExplicitExits.Count -lt 64 -and $watchExplicitExits.Add($key)) {
            $watchReceipt.explicit_owned_exit_count=$watchExplicitExits.Count
            if($watchReceipt.explicit_owned_exits.Count -lt 16){$watchReceipt.explicit_owned_exits+=,[ordered]@{role=(Owned-Role $Record);phase=$Phase;elapsed_seconds=[Math]::Round($watchClock.Elapsed.TotalSeconds,2)}}
        }
        return $true
    }
    return $false
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
    $exitState=Read-OwnedExitState $current $Record 'before_metadata'
    if($null -eq $exitState -or $exitState){return $null}
    try {$started=$current.StartTime.ToUniversalTime().Ticks}
    catch {
        $exitState=Read-OwnedExitState $current $Record 'start_query_failed'
        if($exitState -ne $true){Record-OwnershipIssue 'owned_process_metadata_unknown' $Record.id}
        return $null
    }
    if($started -ne $Record.start){return $null} # PID recycled: original exited; never touch replacement.
    $exitState=Read-OwnedExitState $current $Record 'after_start'
    if($null -eq $exitState -or $exitState){return $null}
    try {$path=$current.Path}
    catch {
        $exitState=Read-OwnedExitState $current $Record 'path_query_failed'
        if($exitState -ne $true){Record-OwnershipIssue 'owned_executable_path_unknown' $Record.id}
        return $null
    }
    $exitState=Read-OwnedExitState $current $Record 'after_path'
    if($null -eq $exitState -or $exitState){return $null}
    if([string]::IsNullOrWhiteSpace($path) -or $path -ne $Record.path){
        $detail=if([string]::IsNullOrWhiteSpace($path)){'live_path_blank'}else{'live_path_mismatch'}
        Record-OwnershipIssue 'owned_executable_identity_unknown' $Record.id $detail
        return $null
    }
    return $current
}
function Failure-Details($ErrorRecord,[string]$Stage) {
    $reason='harness_exception_'+$ErrorRecord.Exception.GetType().Name
    $kind='BLOCKED_INFRA'
    if($ErrorRecord.Exception.Data.Contains('probe_reason')){$reason=$ErrorRecord.Exception.Data['probe_reason'];$kind=$ErrorRecord.Exception.Data['probe_kind']}
    return [ordered]@{stage=$Stage;reason=$reason;kind=$kind;operation=$watchReceipt.last_ui_operation;script_line=[int]$ErrorRecord.InvocationInfo.ScriptLineNumber}
}
function Record-CleanupFailure($ErrorRecord,[string]$Stage) {
    $watchReceipt.cleanup_ui_unavailable=$true
    if($watchReceipt.cleanup_failures.Count -lt 16){$watchReceipt.cleanup_failures+=,(Failure-Details $ErrorRecord $Stage)}
}
function Checkpoint-Receipt {
    if($watchOutputCreated){$watchReceipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $watchOutput 'WATCH_PROBE.json') -Encoding UTF8}
}
function Fit-OwnedDashboard {
    $watchReceipt.last_ui_operation='fit_owned_dashboard'
    if($null -eq (Current-Process $watchOwned[[string]$watchApp.Id])){Block 'dashboard_owner_identity_unavailable'}
    [uint32]$owner=0
    [void][PulseWatchInput]::GetWindowThreadProcessId($watchApp.MainWindowHandle,[ref]$owner)
    if($owner -ne $watchApp.Id){Block 'dashboard_hwnd_owner_mismatch'}
    $before=$watchWindow.Current.BoundingRectangle
    $work=[Windows.Forms.Screen]::FromHandle($watchApp.MainWindowHandle).WorkingArea
    $watchReceipt.initial_window_rect=@($before.X,$before.Y,$before.Width,$before.Height)
    $watchReceipt.desktop_work_area=@($work.X,$work.Y,$work.Width,$work.Height)
    if($work.Width -lt 960 -or $work.Height -lt 640){Block 'desktop_below_app_minimum'}
    $pattern=$null
    if($watchWindow.TryGetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern,[ref]$pattern)) {
        try {$pattern.SetWindowVisualState([System.Windows.Automation.WindowVisualState]::Maximized)} catch {}
    }
    # Normal owned-window maximize, not an offscreen titlebar-coordinate click
    # and not a display-resolution/OS setting change. Win32 return is previous
    # visibility, so actual geometry readback below is the success criterion.
    [void][PulseWatchInput]::ShowWindow($watchApp.MainWindowHandle,3)
    $until=$watchClock.Elapsed.TotalSeconds+4
    do {
        Tick
        $r=$watchWindow.Current.BoundingRectangle
        $fits=($r.Left -ge $work.Left-8 -and $r.Top -ge $work.Top-8 -and $r.Right -le $work.Right+8 -and $r.Bottom -le $work.Bottom+8)
        if($fits){break}
    } while($watchClock.Elapsed.TotalSeconds -lt $until)
    if(-not $fits){Block 'owned_dashboard_did_not_fit_desktop'}
    $watchReceipt.fitted_window_rect=@($r.X,$r.Y,$r.Width,$r.Height)
    $watchReceipt.desktop_fit_verified=$true
}
function Prepare-MediaViewport {
    # Existing local layout controls only. The map layer panel makes the map
    # minimum too tall on this CI desktop; hiding that panel changes neither
    # selected layers nor source/network policy. This is disposable app data.
    $watchReceipt.last_ui_operation='prepare_owned_media_viewport'
    $before=Visible-Rectangle $watchTv $watchWindow
    $watchReceipt.tv_viewport_before=@($before.X,$before.Y,$before.Width,$before.Height)
    $layers=Need-Named $watchWindow @('Show or hide persistent map layer controls') $watchApp.Id
    $toggle=$null
    if(-not $layers.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern,[ref]$toggle)){Block 'map_layer_panel_state_unavailable'}
    $state=$toggle.Current.ToggleState
    if($state -eq [System.Windows.Automation.ToggleState]::Indeterminate){Block 'map_layer_panel_state_indeterminate'}
    $watchReceipt.map_layer_panel_initially_visible=($state -eq [System.Windows.Automation.ToggleState]::On)
    if($state -eq [System.Windows.Automation.ToggleState]::On){Click-Observed $layers $watchApp.MainWindowHandle}
    if($toggle.Current.ToggleState -ne [System.Windows.Automation.ToggleState]::Off){Block 'map_layer_panel_not_hidden'}
    $watchReceipt.map_layer_panel_hidden_for_viewport=$true

    $handles=@()
    $ancestor=[System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($watchTv)
    for($depth=0;$depth -lt 16 -and $null -ne $ancestor;$depth++) {
        if($ancestor.Current.NativeWindowHandle -eq $watchApp.MainWindowHandle){break}
        if($ancestor.Current.ProcessId -eq $watchApp.Id -and $ancestor.Current.ClassName -eq 'QSplitter') {
            $condition=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ClassNameProperty,'QSplitterHandle')
            foreach($handle in $ancestor.FindAll([System.Windows.Automation.TreeScope]::Children,$condition)) {
                $r=$handle.Current.BoundingRectangle
                # Qt's Grip maps to UIA Thumb, not Separator. Ignore handle0
                # (empty) and the narrow vertical handles of horizontal panes.
                if($handle.Current.ProcessId -eq $watchApp.Id -and $handle.Current.ControlType -eq [System.Windows.Automation.ControlType]::Thumb -and -not $r.IsEmpty -and $r.Width -ge 200 -and $r.Height -ge 3 -and $r.Height -le 12 -and (Physically-Visible $handle $watchWindow)){$handles+=,@{element=$handle;splitter=$ancestor}}
            }
        }
        $ancestor=[System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($ancestor)
    }
    if($handles.Count -ne 1){Block 'owned_vertical_splitter_handle_not_unique'}
    $handle=$handles[0].element;$splitter=$handles[0].splitter
    [void][PulseWatchInput]::SetForegroundWindow($watchApp.MainWindowHandle)
    Tick
    if($null -eq (Current-Process $watchOwned[[string]$watchApp.Id])){Block 'splitter_owner_identity_unavailable'}
    [uint32]$owner=0
    [void][PulseWatchInput]::GetWindowThreadProcessId($watchApp.MainWindowHandle,[ref]$owner)
    if($owner -ne $watchApp.Id){Block 'splitter_window_owner_mismatch'}
    $r=$handle.Current.BoundingRectangle;$bounds=$splitter.Current.BoundingRectangle
    $watchReceipt.splitter_handle_before=@($r.X,$r.Y,$r.Width,$r.Height)
    $watchReceipt.splitter_parent_rectangle=@($bounds.X,$bounds.Y,$bounds.Width,$bounds.Height)
    if(-not (Physically-Visible $handle $watchWindow) -or $bounds.IsEmpty){Block 'splitter_handle_not_visible'}
    $x=[int]($r.X+$r.Width/2);$y=[int]($r.Y+$r.Height/2)
    # Derive the endpoint from the observed owned parent, not desktop guesses.
    # Qt enforces its real minimum; success comes only from geometry readback.
    $targetY=[int]($bounds.Top+$bounds.Height/3)
    if($targetY -le $bounds.Top -or $targetY -ge $bounds.Bottom -or $x -le $bounds.Left -or $x -ge $bounds.Right){Block 'splitter_drag_endpoint_invalid'}
    [void](Snapshot '01b-media-before-splitter')
    $watchReceipt.splitter_drag_requested=($targetY -lt $y-2)
    if($watchReceipt.splitter_drag_requested) {
        $point=New-Object PulseWatchInput+POINT;$point.X=$x;$point.Y=$y
        $hit=[PulseWatchInput]::WindowFromPoint($point)
        if($hit -ne $watchApp.MainWindowHandle -and -not [PulseWatchInput]::IsChild($watchApp.MainWindowHandle,$hit)){Block 'splitter_handle_occluded'}
        $hitElement=[System.Windows.Automation.AutomationElement]::FromPoint((New-Object System.Windows.Point($x,$y)))
        $expected=($handle.GetRuntimeId() -join ',');$matched=$false
        for($depth=0;$depth -lt 4 -and $null -ne $hitElement;$depth++) {
            if($hitElement.Current.ProcessId -ne $watchApp.Id){break}
            if(($hitElement.GetRuntimeId() -join ',') -eq $expected){$matched=$true;break}
            $hitElement=[System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($hitElement)
        }
        if(-not $matched){Block 'splitter_accessibility_hit_mismatch'}
        $watchReceipt.last_ui_operation='drag_observed_owned_vertical_splitter'
        if(-not [PulseWatchInput]::Drag($x,$y,$x,$targetY)){Block 'owned_splitter_drag_failed'}
        Tick
    }
    $after=$handle.Current.BoundingRectangle
    $clip=Visible-Rectangle $watchTv $watchWindow
    $watchReceipt.splitter_handle_after=@($after.X,$after.Y,$after.Width,$after.Height)
    $watchReceipt.splitter_drag_moved=($after.Top -lt $r.Top-1)
    $watchReceipt.tv_viewport_after=@($clip.X,$clip.Y,$clip.Width,$clip.Height)
    [void](Snapshot '01c-media-after-splitter')
    if($clip.Width -lt 200 -or $clip.Height -lt 150){Block 'owned_media_viewport_still_too_small'}
    # This is only layout capacity. The actual attached native surface and
    # provider controls must pass their unchanged physical visibility checks.
    $watchReceipt.media_viewport_capacity_ready=$true
}
function Visible-Rectangle($Element,$Root) {
    if($Element.Current.IsOffscreen){return [Drawing.Rectangle]::Empty}
    $r=$Element.Current.BoundingRectangle
    if($r.IsEmpty -or $r.Width -lt 3 -or $r.Height -lt 3){return [Drawing.Rectangle]::Empty}
    $desktop=[Windows.Forms.SystemInformation]::VirtualScreen
    $clip=$Root.Current.BoundingRectangle
    if($clip.IsEmpty){return [Drawing.Rectangle]::Empty}
    $visible=[Drawing.Rectangle]::FromLTRB([int][Math]::Ceiling($r.Left),[int][Math]::Ceiling($r.Top),[int][Math]::Floor($r.Right),[int][Math]::Floor($r.Bottom))
    $visible=[Drawing.Rectangle]::Intersect($visible,$desktop)
    $visible=[Drawing.Rectangle]::Intersect($visible,[Drawing.Rectangle]::FromLTRB([int][Math]::Ceiling($clip.Left),[int][Math]::Ceiling($clip.Top),[int][Math]::Floor($clip.Right),[int][Math]::Floor($clip.Bottom)))
    # Qt can report IsOffscreen=false for a child beyond its scroll viewport.
    # Respect actual ancestor clipping too, not merely the desktop rectangle.
    $ancestor=[System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($Element)
    for($depth=0;$depth -lt 16 -and $null -ne $ancestor;$depth++) {
        $a=$ancestor.Current.BoundingRectangle
        if(-not $a.IsEmpty -and $a.Width -gt 0 -and $a.Height -gt 0){$visible=[Drawing.Rectangle]::Intersect($visible,[Drawing.Rectangle]::FromLTRB([int][Math]::Ceiling($a.Left),[int][Math]::Ceiling($a.Top),[int][Math]::Floor($a.Right),[int][Math]::Floor($a.Bottom)))}
        if($ancestor.Current.NativeWindowHandle -eq $watchApp.MainWindowHandle){break}
        $ancestor=[System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($ancestor)
    }
    # The native HWND's UIA parent chain may skip non-native Qt viewport
    # widgets. Its actual owned TV container supplies that app-side clip.
    if($null -ne $watchSurface -and $null -ne $watchTv -and $Root.Current.NativeWindowHandle -eq $watchSurface.Current.NativeWindowHandle){
        $visible=[Drawing.Rectangle]::Intersect($visible,(Visible-Rectangle $watchTv $watchWindow))
    }
    return $visible
}
function Physically-Visible($Element,$Root,[bool]$AllowAppClip=$false) {
    if(-not $Element.Current.IsEnabled){return $false}
    $visible=Visible-Rectangle $Element $Root
    if($visible.Width -lt 3 -or $visible.Height -lt 3){return $false}
    if($AllowAppClip -and $Element.Current.ProcessId -eq $watchApp.Id){return $true}
    $r=$Element.Current.BoundingRectangle
    # Provider controls must be wholly visible, never hidden-invokable. The
    # one-pixel tolerance covers inward conversion of fractional UIA bounds.
    if($visible.Left -gt $r.Left+1 -or $visible.Top -gt $r.Top+1 -or $visible.Right -lt $r.Right-1 -or $visible.Bottom -lt $r.Bottom-1){return $false}
    return $true
}
function Reveal-OwnedTarget($Element,[bool]$NativeSurface=$false) {
    $watchReceipt.last_ui_operation='reveal_owned_scroll_target'
    if($null -eq (Current-Process $watchOwned[[string]$watchApp.Id])){Block 'scroll_owner_identity_unavailable'}
    if($NativeSurface) {
        if($null -eq $watchSurface -or $Element.Current.NativeWindowHandle -ne $watchSurface.Current.NativeWindowHandle -or -not [PulseWatchInput]::IsChild($watchApp.MainWindowHandle,[IntPtr]$Element.Current.NativeWindowHandle)){Block 'native_surface_reveal_identity_mismatch'}
        [uint32]$surfaceOwner=0
        [void][PulseWatchInput]::GetWindowThreadProcessId([IntPtr]$Element.Current.NativeWindowHandle,[ref]$surfaceOwner)
        if(-not $watchOwned.ContainsKey([string]$surfaceOwner) -or $null -eq (Current-Process $watchOwned[[string]$surfaceOwner])){Block 'native_surface_owner_identity_unavailable'}
    } elseif($Element.Current.ProcessId -ne $watchApp.Id){Block 'scroll_target_not_app_owned'}
    if(-not $NativeSurface) {
        $itemPattern=$null
        if($Element.TryGetCurrentPattern([System.Windows.Automation.ScrollItemPattern]::Pattern,[ref]$itemPattern)){try {$itemPattern.ScrollIntoView()} catch {}}
        try {$Element.SetFocus()} catch {}
        Tick
    }
    for($attempt=0;$attempt -lt 12;$attempt++) {
        if($NativeSurface) {
            $visible=Visible-Rectangle $Element $Element
            if($visible.Width -ge 200 -and $visible.Height -ge 150){return $true}
        } elseif(Physically-Visible $Element $watchWindow $true){return $true}
        $target=$Element.Current.BoundingRectangle
        $scrollTarget=if($NativeSurface){$watchTv}else{$Element}
        if($null -eq $scrollTarget){Block 'owned_scroll_container_unavailable'}
        $ancestor=[System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($scrollTarget)
        $scrolled=$false
        for($depth=0;$depth -lt 12 -and $null -ne $ancestor;$depth++) {
            if($ancestor.Current.NativeWindowHandle -eq $watchApp.MainWindowHandle){break}
            if($ancestor.Current.ProcessId -eq $watchApp.Id) {
                $bounds=$ancestor.Current.BoundingRectangle
                $scroll=$null
                if(-not $bounds.IsEmpty -and $ancestor.TryGetCurrentPattern([System.Windows.Automation.ScrollPattern]::Pattern,[ref]$scroll) -and $scroll.Current.VerticallyScrollable) {
                    $above=$target.Top -lt $bounds.Top
                    $distance=if($above){$bounds.Top-$target.Top}else{$target.Bottom-$bounds.Bottom}
                    if($distance -gt 0) {
                        $amount=if($above){if($distance -gt $bounds.Height){[System.Windows.Automation.ScrollAmount]::LargeDecrement}else{[System.Windows.Automation.ScrollAmount]::SmallDecrement}}else{if($distance -gt $bounds.Height){[System.Windows.Automation.ScrollAmount]::LargeIncrement}else{[System.Windows.Automation.ScrollAmount]::SmallIncrement}}
                        $scroll.Scroll([System.Windows.Automation.ScrollAmount]::NoAmount,$amount)
                        $scrolled=$true;break
                    }
                }
                # Qt exposes a real QScrollArea vertical scrollbar on platforms
                # without ScrollPattern. Never inspect a provider's scrollbar.
                if($ancestor.Current.ClassName -eq 'QScrollArea') {
                    $condition=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::ScrollBar)
                    $bars=@($ancestor.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition) | Where-Object {$_.Current.ProcessId -eq $watchApp.Id -and $_.Current.Orientation -eq [System.Windows.Automation.OrientationType]::Vertical -and (Physically-Visible $_ $watchWindow $true)})
                    if($bars.Count -gt 1){Block 'ambiguous_app_scrollbar'}
                    $range=$null
                    if($bars.Count -eq 1 -and $bars[0].TryGetCurrentPattern([System.Windows.Automation.RangeValuePattern]::Pattern,[ref]$range) -and $range.Current.Maximum -gt $range.Current.Minimum) {
                        $direction=if($target.Top -lt $bounds.Top){-1}else{1}
                        $distance=if($direction -lt 0){$bounds.Top-$target.Top}else{$target.Bottom-$bounds.Bottom}
                        if($distance -gt 0) {
                            # Qt reports LargeChange as singleStep on Windows.
                            # Its own QScrollArea scrollbar uses pixel offsets;
                            # bound movement by the observed viewport geometry.
                            $change=[Math]::Min($bounds.Height,[Math]::Max(1,$distance))
                            $next=[Math]::Max($range.Current.Minimum,[Math]::Min($range.Current.Maximum,$range.Current.Value+$direction*$change))
                            if($next -ne $range.Current.Value){$range.SetValue($next);$scrolled=$true;break}
                        }
                    }
                }
            }
            $ancestor=[System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($ancestor)
        }
        if(-not $scrolled){return $false}
        $watchReceipt.app_scroll_actions++
        Tick
    }
    if($NativeSurface){$visible=Visible-Rectangle $Element $Element;return ($visible.Width -ge 200 -and $visible.Height -ge 150)}
    return (Physically-Visible $Element $watchWindow $true)
}
function Matching-Named($Root,[string[]]$Names,[int]$Owner=0) {
    $watchReceipt.last_ui_operation='find_exact_accessibility_name'
    $found=@()
    foreach($name in $Names) {
        $condition=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,$name)
        foreach($element in $Root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)) {
            if($Owner -eq 0 -or $element.Current.ProcessId -eq $Owner){$found+=,$element}
        }
    }
    return ,$found
}
function Find-Named($Root,[string[]]$Names,[int]$Owner=0) {
    $found=Matching-Named $Root $Names $Owner
    $allowAppClip=($Owner -eq $watchApp.Id)
    $visible=@($found | Where-Object {Physically-Visible $_ $Root $allowAppClip})
    if($visible.Count -gt 1){Block 'ambiguous_accessibility_target'}
    if($visible.Count -eq 1){return $visible[0]}
    # Discovery of provider controls is always passive. Only exact app-owned
    # controls may receive focus/scroll actions to become physically visible.
    if($found.Count -eq 1 -and $Owner -eq $watchApp.Id) {
        if((Reveal-OwnedTarget $found[0]) -and (Physically-Visible $found[0] $Root $true)){return $found[0]}
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
function Need-TvSelector {
    $watchReceipt.last_ui_operation='find_unique_owned_tv_selector'
    if($null -eq $watchTv -or $watchTv.Current.ProcessId -ne $watchApp.Id){Block 'owned_tv_container_unavailable'}
    $condition=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::ComboBox)
    $combos=@($watchTv.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition) | Where-Object {$_.Current.ProcessId -eq $watchApp.Id})
    if($combos.Count -ne 1){Block 'owned_tv_selector_not_unique'}
    if(-not (Reveal-OwnedTarget $combos[0])){Block 'owned_tv_selector_not_visible'}
    return $combos[0]
}
function Resolve-FixturePopup($Element,[string]$Name) {
    # A combo popup is a separate native window even though Qt's logical
    # accessibility ancestry leads back through the closed ComboBox. This
    # exception is solely for this exact app-owned saved-video ListItem.
    $expectedName='Your video '+[char]0xB7+' '+$AuthorizedFixture
    if($Name -ne $expectedName -or $Element.Current.ProcessId -ne $watchApp.Id -or $Element.Current.ControlType -ne [System.Windows.Automation.ControlType]::ListItem -or $Element.Current.Name -ne $Name){Block 'fixture_popup_item_identity_mismatch'}
    if($null -eq (Current-Process $watchOwned[[string]$watchApp.Id])){Block 'fixture_popup_owner_identity_unavailable'}
    if($Element.Current.IsOffscreen -or -not $Element.Current.IsEnabled){return $null}
    $ancestor=[System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($Element)
    $list=$null
    for($depth=0;$depth -lt 8 -and $null -ne $ancestor;$depth++) {
        if($ancestor.Current.ProcessId -ne $watchApp.Id){Block 'fixture_popup_list_not_app_owned'}
        if($ancestor.Current.ControlType -eq [System.Windows.Automation.ControlType]::List){$list=$ancestor;break}
        if($ancestor.Current.ControlType -eq [System.Windows.Automation.ControlType]::ComboBox){break}
        $ancestor=[System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($ancestor)
    }
    if($null -eq $list -or $list.Current.IsOffscreen){return $null}
    $itemBounds=$Element.Current.BoundingRectangle;$listBounds=$list.Current.BoundingRectangle
    if($itemBounds.IsEmpty -or $listBounds.IsEmpty){return $null}
    $rect=[Drawing.Rectangle]::FromLTRB([int][Math]::Ceiling($itemBounds.Left),[int][Math]::Ceiling($itemBounds.Top),[int][Math]::Floor($itemBounds.Right),[int][Math]::Floor($itemBounds.Bottom))
    $rect=[Drawing.Rectangle]::Intersect($rect,[Drawing.Rectangle]::FromLTRB([int][Math]::Ceiling($listBounds.Left),[int][Math]::Ceiling($listBounds.Top),[int][Math]::Floor($listBounds.Right),[int][Math]::Floor($listBounds.Bottom)))
    $rect=[Drawing.Rectangle]::Intersect($rect,[Windows.Forms.SystemInformation]::VirtualScreen)
    if($rect.Width -lt 3 -or $rect.Height -lt 3){return $null}
    $point=New-Object PulseWatchInput+POINT;$point.X=[int]($rect.X+$rect.Width/2);$point.Y=[int]($rect.Y+$rect.Height/2)
    $hit=[PulseWatchInput]::WindowFromPoint($point)
    $popup=[PulseWatchInput]::GetAncestor($hit,2) # GA_ROOT, not root-owner (the main app).
    if($popup -eq [IntPtr]::Zero -or $popup -eq $watchApp.MainWindowHandle){return $null}
    [uint32]$owner=0
    [void][PulseWatchInput]::GetWindowThreadProcessId($popup,[ref]$owner)
    if($owner -ne $watchApp.Id){Block 'fixture_popup_not_app_owned'}
    if(-not [PulseWatchInput]::IsWindowVisible($popup) -or -not [PulseWatchInput]::IsWindowEnabled($popup)){return $null}
    $popupBounds=New-Object PulseWatchInput+RECT
    if(-not [PulseWatchInput]::GetWindowRect($popup,[ref]$popupBounds)){Block 'fixture_popup_rectangle_unavailable'}
    $rect=[Drawing.Rectangle]::Intersect($rect,[Drawing.Rectangle]::FromLTRB($popupBounds.Left,$popupBounds.Top,$popupBounds.Right,$popupBounds.Bottom))
    if($rect.Width -lt 3 -or $rect.Height -lt 3){return $null}
    $point.X=[int]($rect.X+$rect.Width/2);$point.Y=[int]($rect.Y+$rect.Height/2)
    $hit=[PulseWatchInput]::WindowFromPoint($point)
    if($hit -ne $popup -and -not [PulseWatchInput]::IsChild($popup,$hit)){Block 'fixture_popup_item_occluded'}
    # The same process may own more than one popup. Verify the exact current
    # accessible item at this observed point, not merely any owned HWND.
    $hitElement=[System.Windows.Automation.AutomationElement]::FromPoint((New-Object System.Windows.Point($point.X,$point.Y)))
    $expected=($Element.GetRuntimeId() -join ',');$matched=$false
    for($depth=0;$depth -lt 4 -and $null -ne $hitElement;$depth++) {
        if($hitElement.Current.ProcessId -ne $watchApp.Id){break}
        if(($hitElement.GetRuntimeId() -join ',') -eq $expected){$matched=$true;break}
        $hitElement=[System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($hitElement)
    }
    if(-not $matched){Block 'fixture_popup_item_hit_mismatch'}
    return [ordered]@{handle=$popup;point=$point;rectangle=$rect}
}
function Click-SavedFixture([string]$Name) {
    $watchReceipt.last_ui_operation='activate_visible_owned_fixture_popup'
    $until=[Math]::Min($MaxSeconds,$watchClock.Elapsed.TotalSeconds+8)
    $target=$null;$item=$null;$scrolled=$false
    do {
        $items=@((Matching-Named ([System.Windows.Automation.AutomationElement]::RootElement) @($Name) $watchApp.Id) | Where-Object {$_.Current.ControlType -eq [System.Windows.Automation.ControlType]::ListItem})
        if($items.Count -gt 1){Block 'fixture_popup_item_not_unique'}
        if($items.Count -eq 1) {
            $item=$items[0];$target=Resolve-FixturePopup $item $Name
            if($null -ne $target){break}
            $scrollItem=$null
            if(-not $scrolled -and $item.TryGetCurrentPattern([System.Windows.Automation.ScrollItemPattern]::Pattern,[ref]$scrollItem)){$scrollItem.ScrollIntoView();$scrolled=$true}
        }
        Tick
    } while($watchClock.Elapsed.TotalSeconds -lt $until)
    if($null -eq $target){Block 'fixture_popup_visibility_unavailable'}
    [void][PulseWatchInput]::SetForegroundWindow($target.handle)
    Tick
    $fresh=Resolve-FixturePopup $item $Name
    if($null -eq $fresh -or $fresh.handle -ne $target.handle){Block 'fixture_popup_changed_before_click'}
    if(-not [PulseWatchInput]::Click($fresh.point.X,$fresh.point.Y)){Block 'fixture_popup_native_click_failed'}
    $watchReceipt.selected_fixture_popup_clicked=$true
    Tick
}
function Click-Observed($Element,[IntPtr]$RootHandle) {
    $watchReceipt.last_ui_operation='native_click_visible_app_control'
    if($Element.Current.ProcessId -ne $watchApp.Id){Block 'native_click_not_app_owned'}
    if($Element.Current.IsOffscreen -or -not $Element.Current.IsEnabled){Block 'target_not_visible_enabled'}
    $root=[System.Windows.Automation.AutomationElement]::FromHandle($RootHandle)
    if(-not (Physically-Visible $Element $root $true)){Block 'target_outside_visible_desktop_or_viewport'}
    $r=Visible-Rectangle $Element $root
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
        $rect=[Drawing.Rectangle]::Intersect($rect,(Visible-Rectangle $watchSurface $watchSurface))
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
        $record=[ordered]@{file=($Name+'.png');scope=$(if($NativeOnly){'owned_native_surface'}else{'app'});sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant();width=$bitmap.Width;height=$bitmap.Height;screen_rectangle=@($rect.X,$rect.Y,$rect.Width,$rect.Height);sample_colors=$colors.Count;elapsed_seconds=[Math]::Round($watchClock.Elapsed.TotalSeconds,2)}
        $watchReceipt.captures+=,$record
        return $record
    } finally {$graphics.Dispose();$bitmap.Dispose()}
}
function Provider-Blocked($Root) {
    # Read only inside this owned player. Never export the raw accessible text.
    # Offscreen recommendations/comments do not consume the visible prompt
    # budget. An incomplete bounded check is infrastructure BLOCKED, not proof
    # that prompts are absent and not a claimed provider denial.
    $promptClock=[Diagnostics.Stopwatch]::StartNew()
    $onscreen=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::IsOffscreenProperty,$false)
    $dialogType=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Window)
    $dialogs=New-Object System.Windows.Automation.AndCondition($dialogType,$onscreen)
    $dialogCandidates=$Root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$dialogs)
    if($dialogCandidates.Count -gt 32){Block 'prompt_check_incomplete'}
    foreach($dialog in $dialogCandidates) {
        if($promptClock.Elapsed.TotalSeconds -gt 4 -or $watchClock.Elapsed.TotalSeconds -gt $MaxSeconds){Block 'prompt_check_incomplete'}
        $visible=Visible-Rectangle $dialog $Root
        if($visible.Width -ge 3 -and $visible.Height -ge 3){Block 'provider_dialog_observed' 'PROVIDER_BLOCKED'}
    }
    $textType=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Text)
    $condition=New-Object System.Windows.Automation.AndCondition($textType,$onscreen)
    $candidates=$Root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)
    if($candidates.Count -gt 640){Block 'prompt_check_incomplete'}
    $count=0
    foreach($element in $candidates) {
        if($promptClock.Elapsed.TotalSeconds -gt 4 -or $watchClock.Elapsed.TotalSeconds -gt $MaxSeconds){Block 'prompt_check_incomplete'}
        $visible=Visible-Rectangle $element $Root
        if($visible.Width -lt 3 -or $visible.Height -lt 3){continue}
        if(++$count -gt 160){Block 'prompt_check_incomplete'}
        $name=[string]$element.Current.Name
        if($name.Length -gt 1600){Block 'prompt_check_incomplete'}
        if($name -match '(?i)before you continue|confirm.{0,20}(?:age|bot)|sign in to (?:watch|confirm)|not available in your country|video unavailable|error code\s*:?\s*(?:153|101|150)') {Block 'provider_prompt_or_denial_observed' 'PROVIDER_BLOCKED'}
    }
    foreach($name in @('Accept all','Reject all','I agree','Accept cookies')) {
        if($promptClock.Elapsed.TotalSeconds -gt 4 -or $watchClock.Elapsed.TotalSeconds -gt $MaxSeconds){Block 'prompt_check_incomplete'}
        if($null -ne (Find-Named $Root @($name))){Block 'provider_consent_ui_observed' 'PROVIDER_BLOCKED'}
    }
    if($promptClock.Elapsed.TotalSeconds -gt 4){Block 'prompt_check_incomplete'}
}
function Invoke-ProviderControl($Root,[string[]]$Names) {
    Provider-Blocked $Root
    $element=Need-Named $Root $Names 0 10
    Provider-Blocked $Root
    if($element.Current.IsOffscreen -or -not $element.Current.IsEnabled){Block 'provider_control_not_visible_enabled'}
    if(-not (Physically-Visible $element $Root)){Block 'provider_control_not_fully_visible'}
    $pattern=$null
    if(-not $element.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)){Block 'provider_control_not_accessibly_invokable'}
    # Invoke only this exact Play/Pause control. No coordinate fallback: a
    # native HWND hit-test cannot identify an overlapping HTML consent panel.
    $pattern.Invoke()
    Tick
}
function Read-Observation {
    # Passive telemetry only: revealing this label would scroll the actual
    # native player offscreen immediately before its picture is captured.
    $watchReceipt.last_ui_operation='read_owned_telemetry_passively'
    $labels=Matching-Named $watchTv @('TV codec and renderer diagnostics') $watchApp.Id
    if($labels.Count -gt 1){Block 'ambiguous_owned_diagnostic_label'}
    if($labels.Count -eq 0){return $null}
    $label=$labels[0]
    # This exact app label mirrors its already-displayed bounded diagnostics
    # through Qt Help/UIA HelpText. Never inspect raw helper logs or provider
    # HTML; keep older supported text/value patterns as bounded alternatives.
    $text=''
    $help=[string]$label.Current.HelpText
    if(-not [string]::IsNullOrWhiteSpace($help)) {
        if($help.Length -gt 10000 -or -not $help.StartsWith('<pre>') -or -not $help.EndsWith('</pre>')){Block 'owned_telemetry_help_invalid'}
        $text=[System.Net.WebUtility]::HtmlDecode($help.Substring(5,$help.Length-11))
        if($text.Length -gt 1600){Block 'owned_telemetry_text_too_large'}
    }
    $pattern=$null
    if([string]::IsNullOrWhiteSpace($text) -and $label.TryGetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern,[ref]$pattern)){$text=$pattern.DocumentRange.GetText(1600)}
    if([string]::IsNullOrWhiteSpace($text) -and $label.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$pattern)){$text=[string]$pattern.Current.Value}
    if([string]::IsNullOrWhiteSpace($text) -and $label.TryGetCurrentPattern([System.Windows.Automation.LegacyIAccessiblePattern]::Pattern,[ref]$pattern)){$text=[string]$pattern.Current.Value}
    if($text.Length -gt 1600){$text=$text.Substring(0,1600)}
    $available=(-not [string]::IsNullOrWhiteSpace($text))
    $observation=[ordered]@{elapsed_seconds=[Math]::Round($watchClock.Elapsed.TotalSeconds,2);time=$null;frames=$null;state='unknown';provider_code=$null;telemetry_text_available=$available;telemetry_offscreen=(-not (Physically-Visible $label $watchWindow $true))}
    $watchReceipt.telemetry_text_available=$available
    if($text -match 'time\s+(\d+(?:\.\d+)?)s'){$observation.time=[double]::Parse($Matches[1],[Globalization.CultureInfo]::InvariantCulture)}
    if($text -match 'decoded frames\s+(\d+)'){$observation.frames=[long]$Matches[1]}
    if($text -match '(?i)awaiting.play|press play'){$observation.state='awaiting_play'}
    if($text -match '(?i)paused'){$observation.state='paused'}
    if($text -match '(?i)buffering|stalled'){$observation.state='buffering_or_stalled'}
    if($text -match '(?i)(?:error|code)[^0-9]{0,12}(153|150|101|100|5|2)\b'){$observation.provider_code=[int]$Matches[1]}
    $watchReceipt.observations+=,$observation
    if($text -match '(?i)Visible YouTube error|native WebView2 error|provider.*unavailable|unapproved.*redirect') {Block 'app_reported_player_denial' 'PROVIDER_BLOCKED'}
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
    $watchStage='fit_owned_dashboard'
    Fit-OwnedDashboard
    [void](Snapshot '01-app-before-network')
    $watchStage='select_exact_fixture'
    $tvRoots=Matching-Named $watchWindow @('Single large television player') $watchApp.Id
    if($tvRoots.Count -ne 1){Block 'owned_tv_container_not_unique'}
    $watchTv=$tvRoots[0]
    $watchStage='prepare_media_viewport'
    Prepare-MediaViewport
    $watchStage='select_exact_fixture'
    $edit=Need-Named $watchWindow @('Add a specific YouTube video') $watchApp.Id
    Click-Observed $edit $watchApp.MainWindowHandle
    $watchReceipt.last_ui_operation='set_exact_fixture_url'
    $value=$edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    $value.SetValue('https://www.youtube.com/watch?v='+$AuthorizedFixture)
    Click-Observed (Need-Named $watchWindow @('Add video') $watchApp.Id) $watchApp.MainWindowHandle
    # Qt exposes the selected ComboBox text as its accessible name, so locate
    # the sole ComboBox within this exact app-owned television container.
    $combo=Need-TvSelector
    Click-Observed $combo $watchApp.MainWindowHandle
    $savedName='Your video '+[char]0xB7+' '+$AuthorizedFixture
    # SelectionItem.Select alone only marks a popup row in Qt; it does not
    # activate the ComboBox value. Use its actual visible owned popup item.
    Click-SavedFixture $savedName
    $watchReceipt.last_ui_operation='verify_selected_fixture_readback'
    $selected=[string]$combo.Current.Name
    $selection=$null;$comboValue=$null
    $selectedNames=@($selected)
    if($combo.TryGetCurrentPattern([System.Windows.Automation.SelectionPattern]::Pattern,[ref]$selection)) {
        foreach($item in $selection.GetCurrentSelection()){if($item.Current.ProcessId -eq $watchApp.Id){$selectedNames+=,[string]$item.Current.Name}}
    }
    if($combo.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$comboValue)){$selectedNames+=,[string]$comboValue.Current.Value}
    if($savedName -notin $selectedNames){Block 'selected_fixture_readback_mismatch'}
    $watchReceipt.selected_fixture_control_verified=$true
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
    $watchStage='reveal_native_surface'
    if(-not (Reveal-OwnedTarget $watchSurface $true)){Block 'native_surface_not_physically_visible'}
    $watchReceipt.native_surface_visible=$true
    $visibleNative=Visible-Rectangle $watchSurface $watchSurface
    $watchReceipt.native_surface_visible_rectangle=@($visibleNative.X,$visibleNative.Y,$visibleNative.Width,$visibleNative.Height)
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
        $sample=Read-Observation
        Provider-Blocked $watchSurface
        if($null -ne $sample -and $null -ne $sample.time -and $sample.frames -gt 0) {
            if($null -eq $first){$first=$sample;[void](Snapshot '05-first-progress');[void](Snapshot '05-first-progress-native' $true)}
            elseif($sample.time -gt $first.time+1 -and $sample.frames -gt $first.frames){$second=$sample;[void](Snapshot '06-later-progress');[void](Snapshot '06-later-progress-native' $true);break}
        }
        Tick
    } while($watchClock.Elapsed.TotalSeconds -lt $until)
    if($null -eq $second) {
        if(-not ($watchReceipt.Contains('telemetry_text_available')) -or -not $watchReceipt.telemetry_text_available){Block 'owned_telemetry_accessibility_unavailable'}
        Block 'advancing_ui_telemetry_not_demonstrated'
    }
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
    $failure=Failure-Details $_ $watchStage
    $watchReceipt.initial_failure=$failure
    $watchReceipt.outcome=$failure.kind
    $watchReceipt.reason=$failure.reason
    Checkpoint-Receipt
    if($watchReceipt.outcome -eq 'PROVIDER_BLOCKED'){$watchExit=0}
    try {[void](Snapshot '09-blocked-observation')} catch {}
} finally {
    $watchReceipt.stage=$watchStage
    if($null -ne $watchWindow -and $null -ne $watchApp -and -not $watchApp.HasExited) {
        try {Refresh-Owned} catch {Record-CleanupFailure $_ 'cleanup_ownership_refresh'}
        try {
            $mute=Find-Named $watchWindow @('Mute television audio') $watchApp.Id
            $toggle=$null
            if($null -ne $mute -and $mute.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern,[ref]$toggle)) {
                if($toggle.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::Off){Click-Observed $mute $watchApp.MainWindowHandle}
                $watchReceipt.remuted_before_stop=($toggle.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::On)
            }
        } catch {Record-CleanupFailure $_ 'cleanup_remute'}
        try {
            $stop=Find-Named $watchWindow @('Stop selected media source') $watchApp.Id
            if($null -ne $stop){Click-Observed $stop $watchApp.MainWindowHandle;$watchReceipt.stop_control_clicked=$true}
        } catch {Record-CleanupFailure $_ 'cleanup_stop_media'}
        # A missing/offscreen Stop before any media was opened must not skip
        # independent navigation to the app's normal full-exit action.
        try {
            $settings=Find-Named $watchWindow @('Settings') $watchApp.Id
            if($null -eq $settings){Block 'graceful_exit_settings_unavailable'}
            Click-Observed $settings $watchApp.MainWindowHandle
        } catch {Record-CleanupFailure $_ 'cleanup_open_settings'}
        try {
            $exit=Find-Named $watchWindow @('Exit Completely') $watchApp.Id
            if($null -eq $exit){Block 'graceful_exit_control_unavailable'}
            Click-Observed $exit $watchApp.MainWindowHandle
        } catch {Record-CleanupFailure $_ 'cleanup_exit_completely'}
    }
    Checkpoint-Receipt
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
