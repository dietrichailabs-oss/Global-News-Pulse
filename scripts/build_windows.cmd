@echo off
setlocal
rem This wrapper does not change PowerShell execution policy or request elevation.
powershell.exe -NoLogo -NoProfile -NonInteractive -File "%~dp0build_windows.ps1" %*
if errorlevel 1 (
  echo Global Pulse build stopped. Review the displayed prerequisite or test error.
  echo If PowerShell policy blocks this script, use an appropriately signed script
  echo or the documented individual build commands. This wrapper does not alter policy.
  exit /b 1
)
exit /b 0
