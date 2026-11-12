; Global Pulse 0.1.1 E2 — Engineering candidate, not a release approval.
; Compiler prerequisite: Inno Setup 6.7.4. No elevation or background service.
#ifndef PackageRoot
  #define PackageRoot AddBackslash(SourcePath) + "..\dist\GlobalPulse"
#endif
#ifndef OutputRoot
  #define OutputRoot AddBackslash(SourcePath) + "..\release\windows-e2"
#endif
#ifndef ProductVersion
  #define ProductVersion "0.1.1"
#endif
#ifndef CandidateId
  #define CandidateId "E2"
#endif
#if !FileExists(AddBackslash(PackageRoot) + "GlobalPulse.exe")
  #error "The allowlisted Windows application has not been built."
#endif
#if !FileExists(AddBackslash(PackageRoot) + "notifications\GlobalPulse.Notifications.exe")
  #error "The self-contained native notification component is required."
#endif
#if !FileExists(AddBackslash(PackageRoot) + "MANIFEST.json")
  #error "Run package_manifest.py scan/manifest before building the installer."
#endif

[Setup]
InfoBeforeFile={#PackageRoot}\notifications\licenses\windows-sdk\SDK_TERMS.txt
AppId={{56466D47-27D2-492B-B26C-438A4DDBB6AD}
AppName=Global Pulse
AppVersion={#ProductVersion}
AppVerName=Global Pulse {#ProductVersion} {#CandidateId} Engineering Candidate
AppPublisher=Dietrich AI Labs
AppPublisherURL=https://www.dietrichailabs.com/
DefaultDirName={localappdata}\Programs\Dietrich AI Labs\Global Pulse
DefaultGroupName=Global Pulse
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir={#OutputRoot}
OutputBaseFilename=GlobalPulse-{#ProductVersion}-{#CandidateId}-windows-x64-setup
UninstallDisplayName=Global Pulse {#ProductVersion} {#CandidateId}
UninstallDisplayIcon={app}\GlobalPulse.exe
SetupIconFile=..\global_pulse\resources\pulse.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
ChangesAssociations=no
ChangesEnvironment=no
UsePreviousAppDir=yes
UsePreviousGroup=yes
Uninstallable=yes
VersionInfoVersion={#ProductVersion}.0
VersionInfoDescription=Global Pulse Engineering Candidate Installer
VersionInfoProductName=Global Pulse
VersionInfoCompany=Dietrich AI Labs

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#PackageRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Global Pulse"; Filename: "{app}\GlobalPulse.exe"; WorkingDir: "{app}"; Comment: "Global intelligence and emerging events monitor"
Name: "{autodesktop}\Global Pulse"; Filename: "{app}\GlobalPulse.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{group}\Global Pulse User Guide"; Filename: "{app}\USER_GUIDE.md"

[Run]
Filename: "{app}\GlobalPulse.exe"; Description: "Open Global Pulse"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\notifications\GlobalPulse.Notifications.exe"; Parameters: "--unregister"; Flags: runhidden waituntilterminated skipifdoesntexist; RunOnceId: "UnregisterGlobalPulseNotifications"

; There are deliberately no [UninstallDelete] entries for the user's archive,
; translation models, exports, or parent directories. Only installed program
; files and installer-created shortcuts are removed by normal Inno tracking.
