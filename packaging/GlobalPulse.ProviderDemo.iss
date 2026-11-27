; Provider demonstration wrapper of exact held runtime.
#ifndef PackageRoot
  #error "Exact verified runtime required"
#endif
#ifndef OutputRoot
  #error "Output directory required"
#endif
#ifndef SeedRoot
  #error "Empty demonstration profile required"
#endif
#if !FileExists(AddBackslash(PackageRoot) + "GlobalPulse.exe")
  #error "Runtime missing"
#endif
#if !FileExists(AddBackslash(PackageRoot) + "MANIFEST.json")
  #error "Original runtime manifest missing"
#endif
#if !FileExists(AddBackslash(SeedRoot) + "global-pulse.sqlite3")
  #error "Demonstration profile seed missing"
#endif

[Setup]
InfoBeforeFile={#PackageRoot}\notifications\licenses\windows-sdk\SDK_TERMS.txt
InfoAfterFile={#SeedRoot}\PROVIDER_DEMO_GUIDE.txt
AppId={{1B02E5EC-CE9A-4E85-8AE9-7F5BAC15F034}
AppName=Global Pulse Provider Demo
AppVersion=0.1.1
AppVerName=Global Pulse 0.1.1 E2 - PROVIDER DEMONSTRATION ONLY
AppPublisher=Dietrich AI Labs
AppPublisherURL=https://www.dietrichailabs.com/
DefaultDirName={localappdata}\Programs\Dietrich AI Labs\Global Pulse Provider Demo
DefaultGroupName=Global Pulse Provider Demo
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir={#OutputRoot}
OutputBaseFilename=GlobalPulse-0.1.1-E2-ProviderDemo-windows-x64-setup
UninstallDisplayName=Global Pulse Provider Demo
UninstallDisplayIcon={app}\GlobalPulse.exe
SetupIconFile=..\global_pulse\resources\pulse.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no
SetupLogging=yes
ChangesAssociations=no
ChangesEnvironment=no
UsePreviousAppDir=no
UsePreviousGroup=no
Uninstallable=yes
VersionInfoVersion=0.1.1.0
VersionInfoDescription=Global Pulse Provider Demonstration Installer
VersionInfoProductName=Global Pulse Provider Demo
VersionInfoCompany=Dietrich AI Labs

[Tasks]
Name: "desktopicon"; Description: "Create Provider Demo desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#PackageRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SeedRoot}\global-pulse.sqlite3"; DestDir: "{localappdata}\DietrichAILabs\GlobalPulse-ProviderDemo"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "{#SeedRoot}\PROVIDER_DEMO_GUIDE.txt"; DestDir: "{localappdata}\DietrichAILabs\GlobalPulse-ProviderDemo"; Flags: ignoreversion uninsneveruninstall

[Icons]
Name: "{group}\Global Pulse Provider Demo"; Filename: "{app}\GlobalPulse.exe"; Parameters: "--no-start --data-dir ""{localappdata}\DietrichAILabs\GlobalPulse-ProviderDemo"""; WorkingDir: "{app}"; Comment: "Controlled provider demonstration; monitoring starts paused"
Name: "{autodesktop}\Global Pulse Provider Demo"; Filename: "{app}\GlobalPulse.exe"; Parameters: "--no-start --data-dir ""{localappdata}\DietrichAILabs\GlobalPulse-ProviderDemo"""; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{group}\Provider Demo Guide"; Filename: "{localappdata}\DietrichAILabs\GlobalPulse-ProviderDemo\PROVIDER_DEMO_GUIDE.txt"

[Run]
Filename: "{app}\GlobalPulse.exe"; Parameters: "--no-start --data-dir ""{localappdata}\DietrichAILabs\GlobalPulse-ProviderDemo"""; Description: "Open Provider Demo (monitoring paused)"; Flags: postinstall nowait skipifsilent unchecked

; No shared native notification-unregister action: preserve clean install.
; No uninstall-delete of demo or normal archives.
