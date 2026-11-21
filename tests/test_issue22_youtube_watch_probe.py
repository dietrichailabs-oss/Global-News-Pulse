"""Offline source-contract checks for the separately opted-in Windows probe.

These tests do not launch PowerShell, the packaged application, or YouTube.
The actual live probe can be BLOCKED and is never a standard-user/audio PASS.
"""
from pathlib import Path
import re


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "issue22_youtube_watch_probe.ps1"


def source():
    return SCRIPT.read_text(encoding="utf-8")


def body(name):
    text = source()
    start = text.index("function " + name)
    ends = [end for end in (text.find("\nfunction ", start + 1),
                            text.find("\ntry {", start + 1)) if end >= 0]
    return text[start:] if not ends else text[start:min(ends)]


def test_windows_powershell_51_source_is_ascii_and_explicitly_opted_in():
    text = source()
    assert text.isascii()  # PS5.1 without a BOM must not corrupt UI labels.
    assert "[Parameter(Mandatory=$true)][ValidateSet('YE7VzlLtp-4')]" in text
    assert "[ValidateRange(90,240)][int]$MaxSeconds" in text
    assert "finite outer process/step deadline" in text.replace("\n+", " ") or "outer process/step deadline" in text
    assert "if($watchClock.Elapsed.TotalSeconds -gt $MaxSeconds)" in text


def test_only_packaged_application_launch_and_provenance_checks():
    text = source()
    assert len(re.findall(r"\bStart-Process\b", text)) == 1
    assert "Start-Process -FilePath $exe" in text
    assert "@('--no-start','--skip-setup','--data-dir'" in text
    assert "source_worktree_dirty -ne $false" in text
    assert "$build.source_commit -ne $SourceCommit" in text
    assert "$manifest.source.git_commit -ne $SourceCommit" in text
    assert "packaged_payload_hash_mismatch" in text
    for key in ("build_record_sha256", "manifest_sha256", "app_sha256", "helper_sha256"):
        assert key in text
    assert "Start-Process -FilePath $helper" not in text
    assert "--probe-embed" not in text


def test_actual_specific_video_consent_not_quick_embed_button():
    text = source()
    assert "Add a specific YouTube video" in text
    assert "Your video '+[char]0xB7+' '+$AuthorizedFixture" in text
    assert "Try the selected video in YouTube's normal watch page, with consent" in text
    assert "Try official YouTube watch page inside Pulse?" in text
    assert "Click-Observed (Need-Named $dialog @('Yes','&Yes')" in text
    assert "Test TV player" not in text
    assert "QMessageBox" not in text and "_begin_native_player" not in text
    assert "not an owner click" in text


def test_provider_play_uses_exact_visible_accessibility_control_no_click_fallback():
    target = body("Invoke-ProviderControl")
    assert target.count("Provider-Blocked $Root") == 2
    assert "IsOffscreen" in target and "IsEnabled" in target
    assert "InvokePattern]::Pattern" in target
    assert "$pattern.Invoke()" in target
    assert "Click-Observed" not in target and "PulseWatchInput]::Click" not in target
    text = source()
    assert "Invoke-ProviderControl $watchSurface @('Play','Play (k)')" in text
    assert "Invoke-ProviderControl $watchSurface @('Pause','Pause (k)')" in text
    assert "provider_dialog_observed" in body("Provider-Blocked")
    assert "provider_consent_ui_observed" in body("Provider-Blocked")


def test_no_policy_or_provider_bypass_and_no_raw_ui_export():
    text = source()
    for forbidden in ("ExecuteScript", "playVideo(", "remote-debugging-port",
                      "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--no-sandbox",
                      "Import-Certificate", "Cert:\\", "Set-ExecutionPolicy",
                      "Invoke-WebRequest", "taskkill", "Stop-Process -Name"):
        assert forbidden not in text
    assert "provider_consent_accepted=$false" in text
    assert "GetText(1600)" in text
    assert "$watchReceipt.raw" not in text
    assert "$watchReceipt.html" not in text
    assert "$watchReceipt.observations+=,$observation" in text
    assert "Write-Host ('YOUTUBE_WATCH_DIAGNOSTIC='" in text
    assert "Write-Host $text" not in text and "Write-Host $name" not in text


def test_outcomes_do_not_manufacture_audio_selected_content_or_standard_user_pass():
    text = source()
    for fact in ("standard_user_verified=$false", "audible_output_verified=$false",
                 "selected_content_verified=$false", "embedded_identity_verified=$false",
                 "independent_visual_review_required=$true", "tier='DIAGNOSTIC_ONLY'"):
        assert fact in text
    assert "[PulseWatchInput]::Token($PID)" in text
    assert "[PulseWatchInput]::Token($watchApp.Id)" in text
    assert "[PulseWatchInput]::Token($native.Id)" in text
    assert "'PROGRESS_OBSERVED_VISUAL_REVIEW_PENDING'" in text and "'PROVIDER_BLOCKED'" in text
    assert "$watchExit=2" in text and "exit $watchExit" in text


def test_cleanup_is_exact_owned_process_and_generation_checked():
    text = source()
    assert 'ParentProcessId="+$parent.id' in text
    assert "$started=$current.StartTime.ToUniversalTime().Ticks" in text
    assert "if($started -ne $Record.start){return $null}" in text
    assert "$path -ne $Record.path" in text
    assert "$null -eq (Current-Process $parent)" in text
    assert "$process=Current-Process $owned" in text
    assert "$process.Kill()" in text
    assert "$watchReceipt.forced_cleanup=$true" in text
    assert "owned_process_cleanup_not_clean" in text
    assert "'Stop selected media source'" in text
    assert "'Exit Completely'" in text
    assert "Remove-Item" not in text  # Do not delete arbitrary app/profile data.
    assert "evidence_directory_must_be_new" in text
    assert "$watchOutputCreated -and" in text
    assert "if(-not $watchOutputCreated -or $null -eq $watchWindow)" in text
    assert "Get-AuthenticodeSignature -LiteralPath $path" in text
    assert "webview_child_signature_unverified" in text
    assert "private_profile_cleanup_observed=($watchCreatedProfiles.Count -gt 0" in text


def test_captures_and_progress_are_separate_from_meaning_of_content():
    text = source()
    assert "CopyFromScreen" in text
    assert "sample_colors" in text and "Get-FileHash" in text
    assert "$sample.time -gt $first.time+1 -and $sample.frames -gt $first.frames" in text
    assert "deliberate_pre_play_wait_seconds=47" in text
    assert "advancing_ui_telemetry_recorded_native_captures_require_independent_review" in text
    assert "Snapshot '05-first-progress-native' $true" in text
    assert "Snapshot '06-later-progress-native' $true" in text
    assert "scope=$(if($NativeOnly){'owned_native_surface'}else{'app'})" in text
    assert "$range.SetValue(10)" in text
    assert "remuted_before_stop=" in text


def test_bounded_readiness_waits_for_dashboard_and_attached_native_surface():
    text = source()
    assert "$watchApp.MainWindowTitle -eq $dashboardTitle" in text
    assert "'Global Pulse '+[char]0x2014+' Dietrich AI Labs'" in text
    assert "IsWindowVisible($watchApp.MainWindowHandle)" in text
    assert "IsWindowEnabled($watchApp.MainWindowHandle)" in text
    assert "if(-not $dashboardReady){Block 'actual_dashboard_window_unavailable'}" in text
    assert "native_helper_exited_before_attach" in text
    assert "if($top.Count -gt 1){Block 'ambiguous_native_child_surfaces'}" in text
    assert "$until=$watchClock.Elapsed.TotalSeconds+25" in text
    assert text.index("$watchCreatedProfiles=@") > text.index("if($top.Count -ne 1)")


def test_unknown_owned_process_is_not_silently_treated_as_exited():
    current = body("Current-Process")
    assert "catch [System.ArgumentException] {return $null}" in current
    assert "if($started -ne $Record.start){return $null}" in current
    assert "catch {}" not in current
    for reason in ("owned_pid_query_unknown", "owned_process_metadata_unknown",
                   "owned_executable_path_unknown", "owned_executable_identity_unknown"):
        assert "Record-OwnershipIssue '" + reason + "'" in current
    assert "[string]::IsNullOrWhiteSpace($path)" in current
    record = body("Record-OwnershipIssue")
    assert "$watchReceipt.ownership_uncertainty=$true" in record
    assert "$watchOwnershipIssues.Count -lt 128" in record
    assert "$watchReceipt.ownership_issue_reasons.Count -lt 16" in record
    final = source()[source().index("$watchReceipt.cleanup_complete="):]
    assert "$remaining.Count -eq 0 -and -not $watchReceipt.ownership_uncertainty" in final
    assert "if($watchReceipt.ownership_uncertainty)" in final
    assert "'owned_process_cleanup_uncertain';$watchExit=2" in final


def test_child_enumeration_and_admission_failures_remain_explicit():
    refresh = body("Refresh-Owned")
    assert "Get-CimInstance Win32_Process" in refresh
    assert "-ErrorAction Stop" in refresh
    assert "SilentlyContinue" not in refresh and "catch {}" not in refresh
    assert "Refuse-Ownership 'owned_child_enumeration_failed'" in refresh
    assert "catch [System.ArgumentException] {continue}" in refresh
    assert "Refuse-Ownership 'child_process_metadata_unknown'" in refresh
    assert "Refuse-Ownership 'child_ownership_predates_parent'" in refresh
    # The call is outside the metadata try/catch: its original rejection must
    # propagate rather than being swallowed as if the child never existed.
    assert re.search(r"# Do not catch-and-ignore[^\n]*\n\s+Remember-Process \$child\n\s+}", refresh)
    refuse = body("Refuse-Ownership")
    assert refuse.index("Record-OwnershipIssue $Reason $ProcessId") < refuse.index("Block $Reason")
    remember = body("Remember-Process")
    assert "Refuse-Ownership 'unexpected_owned_process_executable'" in remember
    assert "Refuse-Ownership 'webview_child_signature_unverified'" in remember
    assert "Refuse-Ownership 'webview_child_signature_query_failed'" in remember


def test_owned_window_is_required_to_fit_actual_desktop_before_fixture_input():
    fit = body("Fit-OwnedDashboard")
    assert "Current-Process $watchOwned[[string]$watchApp.Id]" in fit
    assert "GetWindowThreadProcessId($watchApp.MainWindowHandle" in fit
    assert "$owner -ne $watchApp.Id" in fit
    assert "Screen]::FromHandle($watchApp.MainWindowHandle).WorkingArea" in fit
    assert "WindowVisualState]::Maximized" in fit
    assert "ShowWindow($watchApp.MainWindowHandle,3)" in fit
    assert "owned_dashboard_did_not_fit_desktop" in fit
    assert "$until=$watchClock.Elapsed.TotalSeconds+4" in fit
    assert "initial_window_rect=" in fit and "fitted_window_rect=" in fit
    text = source()
    flow = text[text.index("$watchStage='fit_owned_dashboard'"):]
    assert flow.index("Fit-OwnedDashboard") < flow.index("Snapshot '01-app-before-network'")
    assert flow.index("Snapshot '01-app-before-network'") < flow.index("$watchStage='select_exact_fixture'")
    for forbidden in ("ChangeDisplaySettings", "Set-DisplayResolution", "DisplayConfigSetDeviceInfo"):
        assert forbidden not in text


def test_app_clipped_visibility_is_not_extended_to_provider_controls():
    clip = body("Visible-Rectangle")
    assert "VirtualScreen" in clip
    assert "[Drawing.Rectangle]::Intersect" in clip
    assert "ControlViewWalker.GetParent($Element)" in clip
    assert "$depth -lt 16" in clip
    assert "Visible-Rectangle $watchTv $watchWindow" in clip
    visible = body("Physically-Visible")
    assert "[bool]$AllowAppClip=$false" in visible
    assert "$AllowAppClip -and $Element.Current.ProcessId -eq $watchApp.Id" in visible
    assert "$visible.Right -lt $r.Right-1" in visible
    click = body("Click-Observed")
    assert "native_click_not_app_owned" in click
    assert "$r=Visible-Rectangle $Element $root" in click
    assert "WindowFromPoint($point)" in click and "IsChild($RootHandle,$hit)" in click
    provider = body("Invoke-ProviderControl")
    assert "Physically-Visible $element $Root" in provider
    assert "provider_control_not_fully_visible" in provider
    assert "AllowAppClip" not in provider and "Click-Observed" not in provider


def test_reveal_uses_bounded_owned_scroll_actions_without_provider_focus():
    reveal = body("Reveal-OwnedTarget")
    assert "$attempt -lt 12" in reveal
    assert "scroll_target_not_app_owned" in reveal
    assert "native_surface_reveal_identity_mismatch" in reveal
    assert "native_surface_owner_identity_unavailable" in reveal
    assert "$scrollTarget=if($NativeSurface){$watchTv}else{$Element}" in reveal
    assert "if(-not $NativeSurface)" in reveal
    assert "ScrollItemPattern" in reveal and "ScrollPattern" in reveal
    assert "$ancestor.Current.ProcessId -eq $watchApp.Id" in reveal
    assert "$ancestor.Current.ClassName -eq 'QScrollArea'" in reveal
    assert "OrientationType]::Vertical" in reveal and "RangeValuePattern" in reveal
    # Qt's Windows provider exposes LargeChange as the small step; relying on
    # it cannot reveal Settings Exit within this bounded 12-action budget.
    assert "$change=[Math]::Min($bounds.Height,[Math]::Max(1,$distance))" in reveal
    assert "$range.Current.Value+$direction*$change" in reveal
    assert "$range.Current.Maximum" in reveal and "$range.Current.Minimum" in reveal
    assert "$range.Current.LargeChange" not in reveal
    assert "if($distance -le 0){continue}" not in reveal
    assert "$ancestor=[System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($ancestor)" in reveal
    finder = body("Find-Named")
    assert "$found.Count -eq 1 -and $Owner -eq $watchApp.Id" in finder
    assert "$allowAppClip=($Owner -eq $watchApp.Id)" in finder
    assert "SetFocus" not in body("Matching-Named")
    assert "Reveal-OwnedTarget" not in body("Matching-Named")


def test_native_capture_uses_app_viewport_clip_not_neighboring_panes():
    capture = body("Snapshot")
    assert "Visible-Rectangle $watchSurface $watchSurface" in capture
    assert "$rect.Width -lt 200 -or $rect.Height -lt 150" in capture
    assert "screen_rectangle=@($rect.X,$rect.Y,$rect.Width,$rect.Height)" in capture
    text = source()
    attached = text[text.index("$watchStage='reveal_native_surface'"):]
    assert attached.index("Reveal-OwnedTarget $watchSurface $true") < attached.index("Snapshot '03-native-before-play'")
    assert "native_surface_visible_rectangle=" in attached


def test_tv_selector_is_unique_owned_type_and_selected_fixture_is_read_back():
    selector = body("Need-TvSelector")
    assert "$watchTv.Current.ProcessId -ne $watchApp.Id" in selector
    assert "ControlType]::ComboBox" in selector
    assert "$combos.Count -ne 1" in selector
    assert "Reveal-OwnedTarget $combos[0]" in selector
    text = source()
    assert "Matching-Named $watchWindow @('Single large television player') $watchApp.Id" in text
    assert "$tvRoots.Count -ne 1" in text
    assert "$combo=Need-TvSelector" in text
    assert "Need-Named $watchWindow @('Television channel or saved video')" not in text
    assert "$savedName -notin $selectedNames" in text
    assert "selected_fixture_readback_mismatch" in text


def test_combo_popup_is_clicked_with_its_own_bounds_not_logical_combo_clip():
    text = source()
    assert "Click-SavedFixture $savedName" in text
    assert "SelectionItemPattern]::Pattern).Select()" not in text
    popup = body("Resolve-FixturePopup")
    assert "$expectedName='Your video '+[char]0xB7+' '+$AuthorizedFixture" in popup
    assert "$Name -ne $expectedName" in popup
    assert "$Element.Current.ProcessId -ne $watchApp.Id" in popup
    assert "ControlType]::ListItem" in popup and "ControlType]::List" in popup
    assert "Current-Process $watchOwned[[string]$watchApp.Id]" in popup
    assert "GetAncestor($hit,2)" in popup
    assert "$popup -eq $watchApp.MainWindowHandle" in popup
    assert "GetWindowThreadProcessId($popup,[ref]$owner)" in popup
    assert "$owner -ne $watchApp.Id" in popup
    assert "GetWindowRect($popup,[ref]$popupBounds)" in popup
    assert "VirtualScreen" in popup and "Rectangle]::Intersect" in popup
    assert "WindowFromPoint($point)" in popup
    assert "AutomationElement]::FromPoint" in popup
    assert "$Element.GetRuntimeId()" in popup and "fixture_popup_item_hit_mismatch" in popup
    assert "Visible-Rectangle" not in popup  # Would incorrectly clip popup to ComboBox.
    activate = body("Click-SavedFixture")
    assert "$watchClock.Elapsed.TotalSeconds+8" in activate
    assert "$items.Count -gt 1" in activate
    assert "$fresh=Resolve-FixturePopup $item $Name" in activate
    assert "$fresh.handle -ne $target.handle" in activate
    assert "PulseWatchInput]::Click($fresh.point.X,$fresh.point.Y)" in activate
    assert "Invoke-ProviderControl" not in activate


def test_provider_prompt_budget_counts_visible_clipped_text_only_and_fails_closed():
    check = body("Provider-Blocked")
    assert "IsOffscreenProperty,$false" in check
    assert "AndCondition($textType,$onscreen)" in check
    assert "$candidates.Count -gt 640" in check
    assert "$dialogCandidates.Count -gt 32" in check
    assert "$promptClock.Elapsed.TotalSeconds -gt 4" in check
    clipped = check.index("$visible=Visible-Rectangle $element $Root")
    counted = check.index("if(++$count -gt 160)")
    read_name = check.index("$name=[string]$element.Current.Name")
    assert clipped < counted < read_name
    assert "if($visible.Width -lt 3 -or $visible.Height -lt 3){continue}" in check
    assert "Block 'prompt_check_incomplete'" in check
    assert "Block 'prompt_check_incomplete' 'PROVIDER_BLOCKED'" not in check
    assert "$watchReceipt.raw" not in check


def test_diagnostics_are_read_passively_through_exact_bounded_help_text():
    observation = body("Read-Observation")
    assert "Matching-Named $watchTv @('TV codec and renderer diagnostics') $watchApp.Id" in observation
    assert "$labels.Count -gt 1" in observation
    assert "$label.Current.HelpText" in observation
    assert "$help.Length -gt 10000" in observation
    assert "$help.StartsWith('<pre>')" in observation and "$help.EndsWith('</pre>')" in observation
    assert "[System.Net.WebUtility]::HtmlDecode" in observation
    assert "$text.Length -gt 1600" in observation
    assert "telemetry_text_available=$available" in observation
    assert "telemetry_offscreen=" in observation
    for forbidden in ("Find-Named", "Reveal-OwnedTarget", "SetFocus", "ScrollIntoView"):
        assert forbidden not in observation
    assert "Visible YouTube error" in observation
    text = source()
    assert "owned_telemetry_accessibility_unavailable" in text
    assert "$sample.time -gt $first.time+1 -and $sample.frames -gt $first.frames" in text
    assert "UI_STATUS_OBSERVED" not in text


def test_initial_failure_is_checkpointed_before_cleanup_and_not_overwritten():
    text = source()
    failure = text[text.index("$failure=Failure-Details $_ $watchStage"):]
    assert failure.index("$watchReceipt.initial_failure=$failure") < failure.index("Checkpoint-Receipt")
    assert failure.index("Checkpoint-Receipt") < failure.index("Snapshot '09-blocked-observation'")
    cleanup = failure[failure.index("} finally {"):]
    assert "$watchReceipt.initial_failure=" not in cleanup
    assert "owned_process_cleanup_not_clean" in cleanup
    detail = body("Failure-Details")
    for key in ("stage=$Stage", "reason=$reason", "kind=$kind", "operation=", "script_line="):
        assert key in detail
    assert "probe_reason" in detail and "probe_kind" in detail
    assert "if($watchOutputCreated)" in body("Checkpoint-Receipt")


def test_graceful_exit_is_attempted_independently_of_media_stop_failure():
    text = source()
    assert re.search(r"catch \{Record-CleanupFailure \$_ 'cleanup_stop_media'\}\s*"
                     r"# A missing/offscreen Stop[^\n]*\n\s*# independent[^\n]*\n\s*try \{", text)
    assert "catch {Record-CleanupFailure $_ 'cleanup_open_settings'}" in text
    assert "catch {Record-CleanupFailure $_ 'cleanup_exit_completely'}" in text
    assert "graceful_exit_settings_unavailable" in text
    assert "graceful_exit_control_unavailable" in text
    assert "$watchReceipt.cleanup_failures.Count -lt 16" in body("Record-CleanupFailure")
    assert "if($watchReceipt.forced_cleanup -or -not $watchReceipt.cleanup_complete)" in text


def test_measured_local_layers_toggle_precedes_owned_splitter_resize():
    prepare = body("Prepare-MediaViewport")
    assert "Need-Named $watchWindow @('Show or hide persistent map layer controls') $watchApp.Id" in prepare
    assert "TogglePattern]::Pattern" in prepare
    assert "ToggleState]::Indeterminate" in prepare
    assert "if($state -eq [System.Windows.Automation.ToggleState]::On){Click-Observed $layers" in prepare
    assert "$toggle.Current.ToggleState -ne [System.Windows.Automation.ToggleState]::Off" in prepare
    assert "map_layer_panel_initially_visible=" in prepare
    assert prepare.index("map_layer_panel_hidden_for_viewport=$true") < prepare.index("$handles=@()")
    assert "$ancestor.Current.ClassName -eq 'QSplitter'" in prepare
    assert "ClassNameProperty,'QSplitterHandle'" in prepare
    assert "TreeScope]::Children" in prepare
    assert "ControlType]::Thumb" in prepare
    assert "$r.Width -ge 200 -and $r.Height -ge 3 -and $r.Height -le 12" in prepare
    assert "$handles.Count -ne 1" in prepare
    flow = source()[source().index("$tvRoots=Matching-Named"):]
    assert flow.index("Prepare-MediaViewport") < flow.index("$watchStage='actual_app_consent'")
    assert "Set-DisplayResolution" not in source()


def test_splitter_drag_is_observed_owned_hit_tested_and_read_back():
    prepare = body("Prepare-MediaViewport")
    assert "Current-Process $watchOwned[[string]$watchApp.Id]" in prepare
    assert "GetWindowThreadProcessId($watchApp.MainWindowHandle" in prepare
    assert "$owner -ne $watchApp.Id" in prepare
    assert "Physically-Visible $handle $watchWindow" in prepare
    assert "$targetY=[int]($bounds.Top+$bounds.Height/3)" in prepare
    assert "splitter_drag_endpoint_invalid" in prepare
    assert "WindowFromPoint($point)" in prepare and "AutomationElement]::FromPoint" in prepare
    assert "$handle.GetRuntimeId()" in prepare and "splitter_accessibility_hit_mismatch" in prepare
    assert "PulseWatchInput]::Drag($x,$y,$x,$targetY)" in prepare
    assert "splitter_handle_before=" in prepare and "splitter_handle_after=" in prepare
    assert "tv_viewport_before=" in prepare and "tv_viewport_after=" in prepare
    assert "splitter_drag_moved=($after.Top -lt $r.Top-1)" in prepare
    assert "Snapshot '01b-media-before-splitter'" in prepare
    assert "Snapshot '01c-media-after-splitter'" in prepare
    assert "$clip.Width -lt 200 -or $clip.Height -lt 150" in prepare
    # A moved splitter/capacity check is not substituted for actual native
    # surface visibility or a fully visible provider control later on.
    assert "$visible.Width -ge 200 -and $visible.Height -ge 150" in body("Reveal-OwnedTarget")
    assert "provider_control_not_fully_visible" in body("Invoke-ProviderControl")
    assert "Drag(" not in body("Invoke-ProviderControl")
    assert "finally { released=SendInput(1,up,size)==1; }" in source()


def test_only_explicit_same_process_exit_resolves_metadata_exit_race():
    exit_state = body("Read-OwnedExitState")
    assert "try {$exited=$Process.HasExited}" in exit_state
    assert "if($exited -eq $true)" in exit_state
    assert "catch {Record-OwnershipIssue 'owned_exit_query_unknown'" in exit_state
    assert "return $null" in exit_state and "return $false" in exit_state
    for forbidden in ("GetProcessById", "Get-Process", "$Process.Handle", "OpenProcess(", ".Kill()"):
        assert forbidden not in exit_state
    assert "$watchExplicitExits.Count -lt 64" in exit_state
    assert "$watchReceipt.explicit_owned_exits.Count -lt 16" in exit_state
    current = body("Current-Process")
    assert current.count("[Diagnostics.Process]::GetProcessById") == 1
    for phase in ("before_metadata", "after_start", "after_path",
                  "start_query_failed", "path_query_failed"):
        assert "Read-OwnedExitState $current $Record '" + phase + "'" in current
    assert current.index("'before_metadata'") < current.index("$current.StartTime")
    assert current.index("'after_start'") < current.index("$path=$current.Path")
    assert current.index("'after_path'") < current.index("[string]::IsNullOrWhiteSpace($path)")
    assert "if($exitState -ne $true){Record-OwnershipIssue" in current
    assert "if($null -eq $exitState -or $exitState){return $null}" in current
    assert "'live_path_blank'" in current and "'live_path_mismatch'" in current
    assert "Record-OwnershipIssue 'owned_executable_identity_unknown' $Record.id $detail" in current
    assert "ownership_uncertainty=$false" not in current


def test_exit_and_uncertainty_receipts_are_bounded_role_enums_not_raw_metadata():
    role = body("Owned-Role")
    assert "return 'app'" in role and "return 'native_helper'" in role
    assert "return 'webview_child'" in role and "return 'unclassified'" in role
    record = body("Record-OwnershipIssue")
    assert "$watchReceipt.ownership_issue_details.Count -lt 16" in record
    assert "role=(Owned-Role $record);reason=$Reason;detail=$Detail" in record
    exit_state = body("Read-OwnedExitState")
    assert "role=(Owned-Role $Record);phase=$Phase;elapsed_seconds=" in exit_state
    for snippet in (record, exit_state):
        assert "path=$" not in snippet and "pid=$" not in snippet
        assert "ownership_uncertainty=$false" not in snippet
