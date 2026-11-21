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
    end = text.find("\nfunction ", start + 1)
    return text[start:] if end < 0 else text[start:end]


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
