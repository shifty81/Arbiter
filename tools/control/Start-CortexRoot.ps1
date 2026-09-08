[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$Command
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
} else {
    $ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
}

$consolePath = Join-Path $PSScriptRoot 'Cortex.Console.ps1'
. $consolePath
Set-CortexConsoleDefaults

$sessionStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$sessionRoot = Join-Path $ProjectRoot 'logs\sessions'
New-Item -ItemType Directory -Force -Path $sessionRoot | Out-Null

$sessionLog = Join-Path $sessionRoot ("cortex-root-{0}.log" -f $sessionStamp)
$transcriptLog = Join-Path $sessionRoot ("cortex-root-{0}.transcript.log" -f $sessionStamp)
$transcriptStarted = $false

try {
    Start-Transcript -LiteralPath $transcriptLog -Force | Out-Null
    $transcriptStarted = $true
}
catch {
    # Transcript support is useful but not required for startup.
}

function Write-BootstrapEvent {
    param(
        [ValidateSet('INFO','PASS','WARN','FAIL','DEBUG','SKIP')][string]$Kind,
        [string]$Message
    )
    Write-CortexEvent $Kind $Message $sessionLog
}

function New-BootstrapDebugBundle {
    param(
        [string]$Reason,
        [string]$FailedStage,
        [int]$ExitCode
    )

    try {
        & (Join-Path $PSScriptRoot 'New-CortexDebugBundle.ps1') `
            -ProjectRoot $ProjectRoot `
            -Reason $Reason `
            -FailedStage $FailedStage `
            -ExitCode $ExitCode `
            -LogPath $sessionLog `
            -OpenFolder | Out-Null
    }
    catch {
        Write-BootstrapEvent 'FAIL' ('Debug bundle creation failed: {0}' -f $_.Exception.Message)
    }
}

function Stop-CortexTranscriptIfRunning {
    if ($script:transcriptStarted) {
        try {
            Stop-Transcript | Out-Null
        }
        catch {
        }
        $script:transcriptStarted = $false
    }
}

try {
    Write-CortexRule 'CORTEX ROOT BOOTSTRAP'

    $patchResult = @(
        & (Join-Path $PSScriptRoot 'InvokeRootPatchIntake.ps1') -ProjectRoot $ProjectRoot -LogPath $sessionLog |
            Where-Object { $_ -is [psobject] -and $_.PSObject.Properties['Applied'] } |
            Select-Object -Last 1
    )

    if ($patchResult.Count -gt 0 -and $patchResult[0].RestartRequired) {
        Write-BootstrapEvent 'WARN' 'Root tooling updated; relaunching before any gate or controller is loaded.'
        Stop-CortexTranscriptIfRunning
        Start-Process -FilePath (Join-Path $ProjectRoot 'PROJECT_CONTROL_CENTER.cmd') -WorkingDirectory $ProjectRoot | Out-Null
        exit 0
    }

    & (Join-Path $PSScriptRoot 'Normalize-CortexArtifacts.ps1') -ProjectRoot $ProjectRoot -LogPath $sessionLog | Out-Null

    & (Join-Path $PSScriptRoot 'Test-CortexQuickGate.ps1') -ProjectRoot $ProjectRoot -LogPath $sessionLog
    $quickGateExitCode = $LASTEXITCODE

    if ($quickGateExitCode -ne 0) {
        Write-BootstrapEvent 'FAIL' 'Startup quick gate failed. Project Control Center will NOT be launched.'
        New-BootstrapDebugBundle -Reason 'STARTUP_FAIL' -FailedStage 'startup-quick-gate' -ExitCode $quickGateExitCode
        exit $quickGateExitCode
    }

    New-BootstrapDebugBundle -Reason 'STARTUP_GREEN' -FailedStage '' -ExitCode 0

    & (Join-Path $PSScriptRoot 'ProjectControlCenter.ps1') `
        -ProjectRoot $ProjectRoot `
        -Command $Command `
        -LogPath $sessionLog

    $controllerExitCode = $LASTEXITCODE
    if ($controllerExitCode -ne 0) {
        New-BootstrapDebugBundle -Reason 'CONTROL_CENTER_FAIL' -FailedStage 'project-control-center' -ExitCode $controllerExitCode
    }
    exit $controllerExitCode
}
catch {
    Write-BootstrapEvent 'FAIL' ('ROOT BOOTSTRAP FAILURE: {0}' -f $_.Exception.Message)
    New-BootstrapDebugBundle -Reason 'ROOT_BOOTSTRAP_FAIL' -FailedStage 'root-bootstrap' -ExitCode 1
    exit 1
}
finally {
    Stop-CortexTranscriptIfRunning
    Set-CortexConsoleDefaults
}
