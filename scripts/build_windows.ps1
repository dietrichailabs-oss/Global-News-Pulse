<#
.SYNOPSIS
Builds a Global Pulse E2 Windows engineering candidate. It does not approve or publish it.
.DESCRIPTION
Requires existing Windows x64, Python 3.12, .NET SDK 10, and Inno Setup 6.7.4.
Project Python dependencies are installed from SHA256-locked requirement files.
The script does not elevate, install OS toolchains, change execution policy, run
untrusted source content, or mark the native Windows acceptance checklist passed.
#>
[CmdletBinding()]
param(
    [string]$Python = 'py.exe',
    [string]$InnoCompiler = '',
    [string]$OutputDirectory = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-Checked {
    param([Parameter(Mandatory=$true)][string]$File, [string[]]$Arguments = @())
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Required command failed with exit code $LASTEXITCODE`: $File"
    }
}

function Remove-GeneratedDirectory {
    param([string]$Path, [string]$AllowedParent)
    $resolved = [System.IO.Path]::GetFullPath($Path)
    $parent = [System.IO.Path]::GetFullPath($AllowedParent).TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($parent, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Refusing to clean a directory outside the generated build area.'
    }
    foreach ($candidatePath in @($AllowedParent,$resolved)) {
        if ((Test-Path -LiteralPath $candidatePath) -and ((Get-Item -LiteralPath $candidatePath -Force).Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
            throw 'Refusing to clean a generated directory through a junction or symbolic link.'
        }
    }
    if (Test-Path -LiteralPath $resolved) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
    New-Item -ItemType Directory -Path $resolved -Force | Out-Null
}

if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) {
    throw 'This candidate must be built on Windows x64. Linux checks do not produce a Windows installer.'
}
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$buildRoot = Join-Path $projectRoot 'build'
$distRoot = Join-Path $projectRoot 'dist'
$venvRoot = Join-Path $buildRoot 'venv-windows'
$nativeRoot = Join-Path $buildRoot 'notifications'
$workRoot = Join-Path $buildRoot 'pyinstaller-windows'
$packageRoot = Join-Path $distRoot 'GlobalPulse'
$helper = Join-Path $PSScriptRoot 'package_manifest.py'
$version = '0.1.1'
$candidate = 'E2'
$buildStamp = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss')
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $projectRoot "release\windows-e2-$buildStamp"
}
$outputRoot = [System.IO.Path]::GetFullPath($OutputDirectory)
if ((Test-Path -LiteralPath $outputRoot) -and (Get-ChildItem -LiteralPath $outputRoot -Force | Select-Object -First 1)) {
    throw 'Output directory is not empty. Choose a new directory; frozen candidates are never overwritten.'
}

foreach ($required in @('requirements-bootstrap.lock','requirements-build.lock','pyproject.toml',
        'global_pulse\resources\pulse.ico','global_pulse\resources\pulse.png',
        'packaging\notifications\GlobalPulse.Notifications.csproj')) {
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $required) -PathType Leaf)) {
        throw "Required build input is missing: $required"
    }
}
$pythonCommand = (Get-Command $Python -ErrorAction Stop).Source
$pythonSelector = @()
if ([System.IO.Path]::GetFileName($pythonCommand) -match '^py(?:\.exe)?$') { $pythonSelector = @('-3.12') }
$pythonIdentity = & $pythonCommand @pythonSelector -c "import sys,platform; assert sys.version_info[:2]==(3,12), 'Python 3.12 is required'; assert platform.machine().lower() in ('amd64','x86_64'), 'Native x64 Python is required'; print(sys.version.split()[0])"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 x64 prerequisite is not satisfied.' }
$dotnet = (Get-Command 'dotnet.exe' -ErrorAction Stop).Source
$dotnetVersion = (& $dotnet --version).Trim()
if ($LASTEXITCODE -ne 0 -or $dotnetVersion -notmatch '^10\.\d+\.\d+$') {
    throw '.NET SDK 10 stable must be the selected SDK. No SDK or system runtime is downloaded by this script.'
}
if (-not $InnoCompiler) {
    $innoCommand = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
    if ($innoCommand) { $InnoCompiler = $innoCommand.Source }
    else {
        $candidates = @(
            (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
            (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
        )
        $InnoCompiler = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    }
}
if (-not $InnoCompiler -or -not (Test-Path -LiteralPath $InnoCompiler -PathType Leaf)) {
    throw 'Install the reviewed Inno Setup 6.7.4 toolchain separately, or pass -InnoCompiler with its ISCC.exe path.'
}
$innoVersion = (Get-Item -LiteralPath $InnoCompiler).VersionInfo.ProductVersion
$innoCompilerSha256 = (Get-FileHash -LiteralPath $InnoCompiler -Algorithm SHA256).Hash.ToLowerInvariant()
# The exact compiler from the SHA-256-verified official 6.7.4 installer may
# report Win32 ProductVersion 0.0.0.0. Accept only reviewed version metadata
# OR the exact 6.7.4 executable hash; never accept an arbitrary replacement.
$reviewedInno674CompilerSha256 = 'f02fa0e5f237b47d7ed1edae9b991866ec94fe02af61eb6a73e94f92fe8e0604'
if ($innoVersion -notmatch '^6\.7\.4(?:\D|$)' -and $innoCompilerSha256 -ne $reviewedInno674CompilerSha256) {
    throw "Expected reviewed Inno Setup 6.7.4; observed ProductVersion=$innoVersion, compiler SHA-256=$innoCompilerSha256. No substitution."
}
if ($innoVersion -notmatch '^6\.7\.4(?:\D|$)') {
    $innoVersion = '6.7.4 (exact compiler SHA-256 verified)'
}

New-Item -ItemType Directory -Path $buildRoot,$distRoot,$outputRoot -Force | Out-Null
Remove-GeneratedDirectory -Path $venvRoot -AllowedParent $buildRoot
Remove-GeneratedDirectory -Path $nativeRoot -AllowedParent $buildRoot
Remove-GeneratedDirectory -Path $workRoot -AllowedParent $buildRoot
Remove-GeneratedDirectory -Path $packageRoot -AllowedParent $distRoot

Push-Location $projectRoot
try {
    Write-Host 'Creating the project-local Python build environment.'
    Invoke-Checked -File $pythonCommand -Arguments ($pythonSelector + @('-m','venv',$venvRoot))
    $buildPython = Join-Path $venvRoot 'Scripts\python.exe'
    Invoke-Checked -File $buildPython -Arguments @('-m','pip','install','--require-hashes','--no-build-isolation','-r','requirements-bootstrap.lock')
    Invoke-Checked -File $buildPython -Arguments @('-m','pip','install','--require-hashes','--no-build-isolation','-r','requirements-build.lock')
    Invoke-Checked -File $buildPython -Arguments @('-m','pip','install','--no-deps','--no-build-isolation','--no-index','.')
    Invoke-Checked -File $buildPython -Arguments @('-m','pip','check')

    Write-Host 'Running internal source, security, integration, and native-backend Qt tests.'
    $priorQtPlatform = $env:QT_QPA_PLATFORM
    try {
        # Use the application's real platform/font backend on this Windows host.
        # Offscreen Windows screenshots were unreadable; do not mask that by
        # removing font/layout checks. Linux CI retains its offscreen suite.
        $env:QT_QPA_PLATFORM = 'windows'
        Invoke-Checked -File $buildPython -Arguments @('-m','pytest','-q','--junitxml', (Join-Path $outputRoot 'internal-tests.xml'))
    }
    finally {
        if ($null -eq $priorQtPlatform) { Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue }
        else { $env:QT_QPA_PLATFORM = $priorQtPlatform }
    }

    Write-Host 'Restoring and publishing the required self-contained Windows notification helper.'
    $nativeProject = Join-Path $projectRoot 'packaging\notifications\GlobalPulse.Notifications.csproj'
    $nativeLock = Join-Path $projectRoot 'packaging\notifications\packages.lock.json'
    $restoreArgs = @('restore',$nativeProject,'--runtime','win-x64','--use-lock-file','--force-evaluate')
    if (Test-Path -LiteralPath $nativeLock -PathType Leaf) {
        $restoreArgs = @('restore',$nativeProject,'--runtime','win-x64','--locked-mode')
    }
    Invoke-Checked -File $dotnet -Arguments $restoreArgs
    Invoke-Checked -File $dotnet -Arguments @('publish',$nativeProject,'--configuration','Release','--runtime','win-x64','--self-contained','true','--no-restore','--output',$nativeRoot,'-p:WindowsAppSDKSelfContained=true','-p:PublishSingleFile=false','-p:PublishTrimmed=false')
    if (-not (Test-Path -LiteralPath (Join-Path $nativeRoot 'coreclr.dll'))) {
        throw 'The notification helper is missing the self-contained .NET runtime.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $nativeRoot 'GlobalPulse.Notifications.exe'))) {
        throw 'The native notification helper executable was not produced.'
    }

    Write-Host 'Collecting exact notices for the shipped self-contained .NET/NuGet runtime.'
    $depsPath = Join-Path $nativeRoot 'GlobalPulse.Notifications.deps.json'
    if (-not (Test-Path -LiteralPath $depsPath -PathType Leaf)) { throw 'Published notification .deps.json is missing.' }
    $nugetLine = (& $dotnet nuget locals global-packages --list).Trim()
    if ($LASTEXITCODE -ne 0 -or $nugetLine -notmatch '^global-packages:\s*(.+)$') {
        throw 'Unable to resolve the exact NuGet global-packages cache.'
    }
    $nugetRoot = $Matches[1].Trim()
    Invoke-Checked -File $buildPython -Arguments @(
        'scripts\collect_dotnet_notices.py',
        '--deps',$depsPath,
        '--nuget-root',$nugetRoot,
        '--output',(Join-Path $nativeRoot 'licenses')
    )

    Write-Host 'Verifying exact Microsoft SDK redistribution evidence and unmodified payloads.'
    Invoke-Checked -File $buildPython -Arguments @(
        'scripts\sdk_distribution.py', '--deps',$depsPath,
        '--nuget-root',$nugetRoot, '--published',$nativeRoot
    )

    Write-Host 'Freezing the application from the explicit PyInstaller specification.'
    Invoke-Checked -File $buildPython -Arguments @('-m','PyInstaller','--noconfirm','--clean','--distpath',$distRoot,'--workpath',$workRoot,'packaging\GlobalPulse.spec')
    Copy-Item -LiteralPath $nativeRoot -Destination (Join-Path $packageRoot 'notifications') -Recurse
    Copy-Item -LiteralPath 'global_pulse\resources\pulse.png' -Destination (Join-Path $packageRoot 'notifications\pulse.png')
    # The compiler's .pdb debugging symbols are engineering artifacts, not runtime.
    Get-ChildItem -LiteralPath (Join-Path $packageRoot 'notifications') -Filter '*.pdb' -Recurse | Remove-Item -Force
    $userDocuments = [ordered]@{
        'docs\PRIVATE_TEST_GUIDE.md' = 'README.md'
        'docs\USER_GUIDE.md' = 'USER_GUIDE.md'
        'docs\SETTINGS_ALERTS.md' = 'SETTINGS_ALERTS.md'
        'docs\KNOWN_LIMITATIONS.md' = 'KNOWN_LIMITATIONS.md'
        'docs\SOURCE_ACCESS_MATRIX.md' = 'SOURCE_ACCESS_MATRIX.md'
        'docs\THIRD_PARTY_NOTICES.md' = 'THIRD_PARTY_NOTICES.md'
    }
    foreach ($sourceName in $userDocuments.Keys) {
        if (-not (Test-Path -LiteralPath $sourceName -PathType Leaf)) { throw "Required user document is missing: $sourceName" }
        Copy-Item -LiteralPath $sourceName -Destination (Join-Path $packageRoot $userDocuments[$sourceName])
    }
    Invoke-Checked -File $buildPython -Arguments @($helper,'licenses',$packageRoot)
    Invoke-Checked -File $buildPython -Arguments @('scripts\qt_distribution.py','--package',$packageRoot)
    Invoke-Checked -File $buildPython -Arguments @($helper,'scan',$packageRoot)
    Invoke-Checked -File $buildPython -Arguments @($helper,'sbom',$packageRoot)
    Invoke-Checked -File $buildPython -Arguments @($helper,'manifest',$packageRoot,'--source-root',$projectRoot)
    Invoke-Checked -File $buildPython -Arguments @($helper,'verify',$packageRoot)

    Write-Host 'Building the per-user installer and portable runtime archive.'
    Invoke-Checked -File $InnoCompiler -Arguments @('/Qp',"/DPackageRoot=$packageRoot","/DOutputRoot=$outputRoot",'/DProductVersion=0.1.1','/DCandidateId=E2','packaging\GlobalPulse.iss')
    $installer = Join-Path $outputRoot 'GlobalPulse-0.1.1-E2-windows-x64-setup.exe'
    $portable = Join-Path $outputRoot 'GlobalPulse-0.1.1-E2-windows-x64-portable.zip'
    if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) { throw 'Installer compiler did not produce the expected artifact.' }
    Invoke-Checked -File $buildPython -Arguments @($helper,'archive',$packageRoot,$portable)
    Copy-Item -LiteralPath (Join-Path $packageRoot 'MANIFEST.json'),(Join-Path $packageRoot 'SBOM.cdx.json') -Destination $outputRoot
    if (Test-Path -LiteralPath $nativeLock) { Copy-Item -LiteralPath $nativeLock -Destination (Join-Path $outputRoot 'native-packages.lock.json') }
    $buildRecord = [ordered]@{
        product='Global Pulse';version=$version;candidate=$candidate;built_at_utc=(Get-Date).ToUniversalTime().ToString('o')
        python=($pythonIdentity -join '');dotnet_sdk=$dotnetVersion;inno_setup=$innoVersion
        system=[Environment]::OSVersion.VersionString
        source_commit=((& git rev-parse HEAD) -join '').Trim()
        source_worktree_dirty=[bool]((& git status --porcelain --untracked-files=no) -join '')
        native_helper_self_contained=$true
        internal_automated_tests='See internal-tests.xml; command failed the build if any test failed'
        qt_test_platform='windows'
        windows_native_acceptance='NOT RUN by build script'
        clean_machine_installation='NOT RUN by build script'
        security_privacy_review='PENDING';source_licensing_review='PENDING';release_approval='NOT GRANTED'
    }
    $recordPath = Join-Path $outputRoot 'WINDOWS_BUILD_RECORD.json'
    $buildRecord | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $recordPath -Encoding UTF8
    Invoke-Checked -File $buildPython -Arguments @($helper,'artifact-hashes',$installer,$portable,(Join-Path $outputRoot 'MANIFEST.json'),(Join-Path $outputRoot 'SBOM.cdx.json'),$recordPath,'--output',(Join-Path $outputRoot 'SHA256SUMS.txt'))
    Write-Host "Engineering artifacts created in $outputRoot"
    Write-Host 'Windows acceptance, exact-artifact independent QA, security/privacy and licensing review remain required. Nothing was published.'
}
catch {
    Write-Error "Build stopped: $($_.Exception.Message). Partial outputs are not release candidates."
    exit 1
}
finally {
    Pop-Location
}
