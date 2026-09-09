[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$ControllerVersion = 'CTX-ROOT-09KR10R1'
$CortexGitRemoteUrl = 'https://github.com/shifty81/Cortex.git'
. (Join-Path $PSScriptRoot 'Cortex.Console.ps1')
Set-CortexConsoleDefaults

$ArtifactsRoot = Join-Path $ProjectRoot 'artifacts'
$ArtifactLogsRoot = Join-Path $ArtifactsRoot 'logs'
$logsDir = Join-Path $ArtifactLogsRoot 'sessions'
$debugDir = Join-Path $ArtifactsRoot 'debug'
$patchArtifactsDir = Join-Path $ArtifactsRoot 'patches'
$recoveryArtifactsDir = Join-Path $ArtifactsRoot 'recovery'
$certificationArtifactsDir = Join-Path $ArtifactsRoot 'certification'
$buildArtifactsDir = Join-Path $ArtifactsRoot 'builds'
$statusArtifactsDir = Join-Path $ArtifactsRoot 'status'
New-Item -ItemType Directory -Force -Path @(
    $ArtifactsRoot,
    $ArtifactLogsRoot,
    $logsDir,
    $debugDir,
    $patchArtifactsDir,
    $recoveryArtifactsDir,
    $certificationArtifactsDir,
    $buildArtifactsDir,
    $statusArtifactsDir
) | Out-Null

$sessionStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$ActiveLog = Join-Path $logsDir "cortex-root-$sessionStamp.log"
$TranscriptLog = Join-Path $logsDir "cortex-root-$sessionStamp.transcript.log"
$transcriptStarted = $false
try {
    Start-Transcript -LiteralPath $TranscriptLog -Force | Out-Null
    $transcriptStarted = $true
} catch {}

$script:CargoTargetDirectory = $null
$script:CargoMetadataCache = $null
$script:CargoMetadataCacheUtc = [datetime]::MinValue
$script:GitSummaryCache = $null
$script:GitSummaryCacheUtc = [datetime]::MinValue
$script:PatchScanCache = $null
$script:PatchScanCacheUtc = [datetime]::MinValue
$script:LastGateFailedStage = ''
$script:LastGateExitCode = 0
$script:LastCargoDiagnosticsPath = ''

function Reset-CortexStatusCaches {
    $script:GitSummaryCache = $null
    $script:GitSummaryCacheUtc = [datetime]::MinValue
    $script:PatchScanCache = $null
    $script:PatchScanCacheUtc = [datetime]::MinValue
    $script:CargoMetadataCache = $null
    $script:CargoMetadataCacheUtc = [datetime]::MinValue
    $script:CargoTargetDirectory = $null
}

function Get-CargoMetadata {
    $age = ((Get-Date) - $script:CargoMetadataCacheUtc).TotalSeconds
    if ($script:CargoMetadataCache -and $age -lt 10) {
        return $script:CargoMetadataCache
    }
    if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { return $null }

    Push-Location $ProjectRoot
    try {
        $raw = & cargo metadata --no-deps --format-version 1 --quiet 2>$null
        if ($LASTEXITCODE -eq 0 -and $raw) {
            $metadata = $raw | ConvertFrom-Json
            $script:CargoMetadataCache = $metadata
            $script:CargoMetadataCacheUtc = Get-Date
            if ($metadata.target_directory) {
                $script:CargoTargetDirectory = [IO.Path]::GetFullPath([string]$metadata.target_directory)
            }
            return $metadata
        }
    } catch {
    } finally {
        Pop-Location
        Set-CortexConsoleDefaults
    }
    return $null
}

function Get-CargoTargetDirectory {
    if ($script:CargoTargetDirectory) { return $script:CargoTargetDirectory }
    $metadata = Get-CargoMetadata
    if ($metadata -and $metadata.target_directory) {
        $script:CargoTargetDirectory = [IO.Path]::GetFullPath([string]$metadata.target_directory)
        return $script:CargoTargetDirectory
    }
    return (Join-Path $ProjectRoot 'target')
}

function Get-CortexBinaryDescriptor {
    param([ValidateSet('CLI','GUI')][string]$Kind)

    $packageName = if ($Kind -eq 'CLI') { 'cortex' } else { 'cortex_desktop' }
    $fallbackTargetName = $packageName
    $metadata = Get-CargoMetadata
    $targetDir = Get-CargoTargetDirectory
    $targetName = $fallbackTargetName

    if ($metadata -and $metadata.packages) {
        $package = @($metadata.packages | Where-Object { [string]$_.name -eq $packageName } | Select-Object -First 1)
        if ($package.Count -gt 0) {
            $binaryTarget = @(
                $package[0].targets |
                    Where-Object { @($_.kind) -contains 'bin' } |
                    Select-Object -First 1
            )
            if ($binaryTarget.Count -gt 0 -and $binaryTarget[0].name) {
                $targetName = [string]$binaryTarget[0].name
            }
        }
    }

    $exeName = if ($env:OS -eq 'Windows_NT') { "$targetName.exe" } else { $targetName }
    $found = $null
    $foundProfile = $null

    foreach ($profile in @('debug','release')) {
        $candidate = Join-Path (Join-Path $targetDir $profile) $exeName
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $found = $candidate
            $foundProfile = $profile
            break
        }
    }

    if (-not $found) {
        $found = Join-Path (Join-Path $targetDir 'debug') $exeName
        $foundProfile = 'debug'
    }

    return [pscustomobject]@{
        Kind = $Kind
        Package = $packageName
        TargetName = $targetName
        FileName = $exeName
        Path = $found
        Profile = $foundProfile
        Exists = (Test-Path -LiteralPath $found -PathType Leaf)
        TargetDirectory = $targetDir
    }
}

function Get-CortexBinaryPath {
    param([ValidateSet('CLI','GUI')][string]$Kind)
    $descriptor = Get-CortexBinaryDescriptor -Kind $Kind
    if (-not $descriptor) { return $null }
    return [string]$descriptor.Path
}

function Get-CortexGitSummary {
    $age = ((Get-Date) - $script:GitSummaryCacheUtc).TotalSeconds
    if ($script:GitSummaryCache -and $age -lt 5) { return $script:GitSummaryCache }

    $fallback = [pscustomobject]@{
        gitReady = $false
        branch = $null
        headShort = $null
        upstream = $null
        ahead = $null
        behind = $null
        clean = $false
        greenMarker = $false
        greenMatch = $false
        greenEligible = $false
    }

    $helper = Join-Path $PSScriptRoot 'GitSourceControl.ps1'
    if (-not (Test-Path -LiteralPath $helper -PathType Leaf)) { return $fallback }

    try {
        $global:CortexGitBridgeExitCode = 0
        $json = @(& $helper -Root $ProjectRoot -Action SummaryJson -RemoteUrl $CortexGitRemoteUrl) -join "`n"
        if ($global:CortexGitBridgeExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($json)) {
            $summary = $json | ConvertFrom-Json
            $script:GitSummaryCache = $summary
            $script:GitSummaryCacheUtc = Get-Date
            return $summary
        }
    } catch {}
    return $fallback
}

function Invoke-BuildPackage {
    param(
        [Parameter(Mandatory=$true)][string]$Package,
        [Parameter(Mandatory=$true)][string]$Label
    )
    $ok = Invoke-CargoStep -Label "Build $Label" -CargoArgs @('build','-p',$Package)
    if ($ok) {
        $script:CargoTargetDirectory = $null
        Reset-CortexStatusCaches
    }
    return $ok
}

function Start-CortexDesktop {
    $gui = Get-CortexBinaryPath GUI
    if (-not $gui -or -not (Test-Path -LiteralPath $gui -PathType Leaf)) {
        Event 'INFO' 'Cortex Desktop is not built; building package cortex_desktop.'
        if (-not (Invoke-BuildPackage -Package 'cortex_desktop' -Label 'Cortex Desktop')) {
            Event 'FAIL' 'Cortex Desktop build failed; launch cancelled.'
            return $false
        }
        $gui = Get-CortexBinaryPath GUI
    }
    if (-not $gui -or -not (Test-Path -LiteralPath $gui -PathType Leaf)) {
        Event 'FAIL' 'Cortex Desktop executable was not found after build.'
        return $false
    }
    Event 'INFO' "Launching Cortex Desktop: $gui"
    Start-Process -FilePath $gui -WorkingDirectory $ProjectRoot -ArgumentList @("`"$ProjectRoot`"") | Out-Null
    return $true
}

function Event([string]$kind,[string]$message) { Write-CortexEvent $kind $message $ActiveLog }
function Invoke-ControlScript([string]$name,[hashtable]$params = @{}) {
    $path = Join-Path $PSScriptRoot $name
    if (-not (Test-Path -LiteralPath $path)) { throw "Required control script missing: $path" }
    & $path @params
    return $LASTEXITCODE
}
function Write-CargoRunReceipt {
    param(
        [Parameter(Mandatory=$true)][string]$Label,
        [AllowEmptyCollection()][string[]]$Arguments = @(),
        [Parameter(Mandatory=$true)][int]$ExitCode,
        [Parameter(Mandatory=$true)][datetime]$Started,
        [Parameter(Mandatory=$true)][datetime]$Finished,
        [string]$DiagnosticsPath = ''
    )

    try {
        New-Item -ItemType Directory -Force -Path $buildArtifactsDir | Out-Null
        $safeLabel = ($Label -replace '[^A-Za-z0-9._-]','_').Trim('_')
        if ([string]::IsNullOrWhiteSpace($safeLabel)) { $safeLabel = 'cargo' }
        $stamp = $Started.ToString('yyyyMMdd-HHmmssfff')
        $path = Join-Path $buildArtifactsDir ("{0}_{1}.json" -f $stamp,$safeLabel)

        $head = $null
        try {
            if (Test-Path -LiteralPath (Join-Path $ProjectRoot '.git')) {
                $head = (& git -C $ProjectRoot rev-parse HEAD 2>$null | Select-Object -First 1)
            }
        } catch {}

        $receipt = [ordered]@{
            schema = 'cortex.cargo_run_receipt.v1'
            label = $Label
            arguments = @($Arguments)
            exitCode = $ExitCode
            success = ($ExitCode -eq 0)
            startedUtc = $Started.ToUniversalTime().ToString('o')
            finishedUtc = $Finished.ToUniversalTime().ToString('o')
            elapsedMs = [int64]($Finished - $Started).TotalMilliseconds
            gitHead = $head
            projectRoot = $ProjectRoot
            diagnosticsPath = $DiagnosticsPath
        }
        $json = $receipt | ConvertTo-Json -Depth 6
        $json | Set-Content -LiteralPath $path -Encoding UTF8
        $json | Set-Content -LiteralPath (Join-Path $buildArtifactsDir 'LATEST_BUILD_RECEIPT.json') -Encoding UTF8
    } catch {
        Event 'WARN' "Could not write Cargo run receipt: $($_.Exception.Message)"
    }
}

function Invoke-CargoStep {
    param(
        [Parameter(Mandatory=$true)][string]$Label,
        [Parameter(Mandatory=$true)][AllowEmptyCollection()][string[]]$CargoArgs
    )

    Event 'INFO' "START $Label"
    $started = Get-Date
    $code = 1
    $safeLabel = ($Label -replace '[^A-Za-z0-9._-]','_').Trim('_')
    if ([string]::IsNullOrWhiteSpace($safeLabel)) { $safeLabel = 'cargo' }
    $diagnosticsPath = Join-Path $buildArtifactsDir ("{0}_{1}.log" -f $started.ToString('yyyyMMdd-HHmmssfff'),$safeLabel)
    $latestDiagnostics = Join-Path $buildArtifactsDir 'LATEST_CARGO_DIAGNOSTICS.log'
    $script:LastCargoDiagnosticsPath = $diagnosticsPath

    @(
        '========================================================================'
        " CORTEX CARGO DIAGNOSTICS - $Label"
        '========================================================================'
        "Started     : $($started.ToString('o'))"
        "ProjectRoot : $ProjectRoot"
        "Command     : cargo $($CargoArgs -join ' ')"
        ''
    ) | Set-Content -LiteralPath $diagnosticsPath -Encoding UTF8

    Push-Location $ProjectRoot
    try {
        # Capture native stdout/stderr so the function emits only its Boolean
        # result. Native Cargo output previously escaped through the success
        # pipeline and converted the return value into an object array.
        $cargoOutput = @(& cargo @CargoArgs 2>&1)
        $code = $LASTEXITCODE
        foreach ($entry in $cargoOutput) {
            $line = [string]$entry
            Add-Content -LiteralPath $diagnosticsPath -Value $line -Encoding UTF8
            Write-Host $line
        }
    } catch {
        $code = if ($LASTEXITCODE) { [int]$LASTEXITCODE } else { 1 }
        $line = "Cargo invocation crashed: $($_.Exception.Message)"
        Add-Content -LiteralPath $diagnosticsPath -Value $line -Encoding UTF8
        Write-Host $line
    } finally {
        Pop-Location
        Set-CortexConsoleDefaults
    }

    $finished = Get-Date
    @(
        ''
        "Finished    : $($finished.ToString('o'))"
        "ExitCode    : $code"
    ) | Add-Content -LiteralPath $diagnosticsPath -Encoding UTF8

    Copy-Item -LiteralPath $diagnosticsPath -Destination $latestDiagnostics -Force

    Write-CargoRunReceipt `
        -Label $Label `
        -Arguments $CargoArgs `
        -ExitCode $code `
        -Started $started `
        -Finished $finished `
        -DiagnosticsPath $diagnosticsPath

    if ($code -ne 0) {
        $script:LastGateFailedStage = $safeLabel.ToLowerInvariant()
        $script:LastGateExitCode = $code
        Event 'FAIL' "$Label failed with exit code $code"
        return $false
    }

    Event 'PASS' $Label
    return $true
}

function Get-StatusValue {
    param([string]$kind)
    switch ($kind) {
        'Git' {
            $summary = Get-CortexGitSummary
            if (-not $summary.gitReady) { return 'Not a repository' }
            return $(if ($summary.clean) { 'Clean' } else { 'Modified' })
        }
        'Cargo' { if (Get-Command cargo -ErrorAction SilentlyContinue) { return 'Ready' } else { return 'Missing' } }
        'Workspace' { if (Test-Path -LiteralPath (Join-Path $ProjectRoot 'Cargo.toml')) { return 'Ready' } else { return 'Missing' } }
        'CLI' {
            $path = Get-CortexBinaryPath CLI
            if ($path -and (Test-Path -LiteralPath $path -PathType Leaf)) { return 'Ready' }
            return 'Not built yet'
        }
        'GUI' {
            $path = Get-CortexBinaryPath GUI
            if ($path -and (Test-Path -LiteralPath $path -PathType Leaf)) { return 'Ready' }
            return 'Not built yet'
        }
    }
}

function Invoke-CortexGitAction {
    param(
        [Parameter(Mandatory=$true)][string]$Action,
        [string]$Message = ''
    )

    $helper = Join-Path $PSScriptRoot 'GitSourceControl.ps1'
    if (-not (Test-Path -LiteralPath $helper -PathType Leaf)) {
        Event 'FAIL' "Git source-control helper is missing: $helper"
        return $false
    }

    $arguments = @(
        '-Root',$ProjectRoot,
        '-Action',$Action,
        '-RemoteUrl',$CortexGitRemoteUrl
    )
    if (-not [string]::IsNullOrWhiteSpace($Message)) {
        $arguments += @('-Message',$Message)
    }

    Event 'INFO' "START Git: $Action"
    $global:CortexGitBridgeExitCode = 0

    try {
        # Force native Git/Python stdout to the host so callers may safely capture
        # the boolean result without hiding the actual status/audit report.
        & $helper @arguments | ForEach-Object { Write-Host $_ }
        $code = [int]$global:CortexGitBridgeExitCode
    } catch {
        Event 'FAIL' "Git action $Action crashed: $($_.Exception.Message)"
        Set-CortexConsoleDefaults
        return $false
    }

    Set-CortexConsoleDefaults

    if ($code -ne 0) {
        Event 'FAIL' "Git action $Action failed with exit code $code."
        return $false
    }

    Reset-CortexStatusCaches
    Event 'PASS' "Git action $Action"
    return $true
}


function Write-CortexGreenMarker {
    $ok = Invoke-CortexGitAction -Action 'MarkGreen'
    if (-not $ok) {
        Event 'WARN' 'Full Quality is GREEN, but the optional Git GREEN-source marker could not be written.'
    }
}

function Get-PatchScanSummary {
    param([switch]$Force)

    $age = ((Get-Date) - $script:PatchScanCacheUtc).TotalSeconds
    if (-not $Force -and $script:PatchScanCache -and $age -lt 5) {
        return $script:PatchScanCache
    }

    $fallback = [pscustomobject]@{
        Applied = 0
        Pending = 0
        Invalid = 0
        Ignored = 0
        Archives = @()
        RestartRequired = $false
    }

    try {
        $output = @(
            & (Join-Path $PSScriptRoot 'InvokeRootPatchIntake.ps1') `
                -ProjectRoot $ProjectRoot `
                -LogPath $ActiveLog `
                -ScanOnly `
                -Quiet
        )
        $summary = @(
            $output |
                Where-Object {
                    $_ -is [psobject] -and
                    $_.PSObject.Properties['Pending']
                } |
                Select-Object -Last 1
        )
        if ($summary.Count -gt 0) {
            $script:PatchScanCache = $summary[0]
            $script:PatchScanCacheUtc = Get-Date
            return $script:PatchScanCache
        }
    } catch {
        Event 'WARN' "Patch scan failed: $($_.Exception.Message)"
    }

    return $fallback
}

function Restart-CortexRootUtility {
    Event 'WARN' 'Control-center files were updated; relaunching Cortex root utility so the new scripts become authoritative.'
    try {
        $pwsh = (Get-Process -Id $PID).Path
        Start-Process -FilePath $pwsh -ArgumentList @(
            '-NoProfile',
            '-ExecutionPolicy',
            'Bypass',
            '-File',
            "`"$PSCommandPath`""
        ) -WorkingDirectory $ProjectRoot | Out-Null
        if ($transcriptStarted) {
            try { Stop-Transcript | Out-Null } catch {}
        }
        exit 0
    } catch {
        Event 'WARN' "Automatic relaunch failed: $($_.Exception.Message). Close and relaunch the root utility once."
        return $false
    }
}

function Invoke-PendingPatchApply {
    Write-CortexRule 'APPLY PENDING ROOT / INBOX UPDATES'
    $summary = $null
    try {
        $output = @(
            & (Join-Path $PSScriptRoot 'InvokeRootPatchIntake.ps1') `
                -ProjectRoot $ProjectRoot `
                -LogPath $ActiveLog
        )
        $result = @(
            $output |
                Where-Object {
                    $_ -is [psobject] -and
                    $_.PSObject.Properties['Applied']
                } |
                Select-Object -Last 1
        )
        if ($result.Count -gt 0) { $summary = $result[0] }
    } catch {
        Event 'FAIL' "Root patch intake failed: $($_.Exception.Message)"
        return $false
    }

    Reset-CortexStatusCaches

    if ($summary -and $summary.RestartRequired) {
        [void](Restart-CortexRootUtility)
        return $true
    }

    if ($summary) {
        Event 'PASS' ("Patch intake completed: {0} applied." -f [int]$summary.Applied)
    }
    return $true
}

function Invoke-QuickGateMenuAction {
    Write-CortexRule 'QUICK PROJECT GATE'
    try {
        & (Join-Path $PSScriptRoot 'Test-CortexQuickGate.ps1') `
            -ProjectRoot $ProjectRoot `
            -LogPath $ActiveLog
        if ($LASTEXITCODE -eq 0) {
            Event 'PASS' 'Quick project gate GREEN.'
            return $true
        }
        Event 'FAIL' "Quick project gate failed with exit code $LASTEXITCODE."
    } catch {
        Event 'FAIL' "Quick project gate crashed: $($_.Exception.Message)"
    }
    return $false
}

function Open-CortexFolder {
    param([Parameter(Mandatory=$true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    }
    Start-Process explorer.exe -ArgumentList "`"$Path`"" | Out-Null
}

function Move-CortexLegacyRootSessionLogs {
    $legacy = Join-Path $ProjectRoot 'logs\sessions'
    if (-not (Test-Path -LiteralPath $legacy -PathType Container)) { return }

    $destination = Join-Path $ArtifactLogsRoot 'legacy-sessions'
    New-Item -ItemType Directory -Force -Path $destination | Out-Null

    $moved = 0
    Get-ChildItem -LiteralPath $legacy -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne '.gitkeep' } |
        ForEach-Object {
            $target = Join-Path $destination $_.Name
            if (Test-Path -LiteralPath $target) {
                $target = Join-Path $destination ("{0}-{1}{2}" -f
                    [IO.Path]::GetFileNameWithoutExtension($_.Name),
                    (Get-Date -Format 'yyyyMMdd-HHmmssfff'),
                    $_.Extension)
            }
            try {
                Move-Item -LiteralPath $_.FullName -Destination $target -Force
                $moved++
            } catch {
                Event 'WARN' "Could not migrate legacy session log $($_.Name): $($_.Exception.Message)"
            }
        }

    if ($moved -gt 0) {
        Event 'INFO' "Migrated $moved legacy root session log(s) into artifacts\\logs\\legacy-sessions."
    }
}

function Test-CortexPublishedMain {
    Write-CortexRule 'VERIFY PUBLISHED MAIN'
    $result = [ordered]@{
        schema = 'cortex.published_state.v1'
        checkedUtc = (Get-Date).ToUniversalTime().ToString('o')
        branch = $null
        localHead = $null
        remoteHead = $null
        clean = $false
        greenMatch = $false
        published = $false
        detail = $null
    }

    try {
        if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot '.git'))) {
            throw 'Git repository is not initialized.'
        }

        & git -C $ProjectRoot fetch origin main --quiet
        if ($LASTEXITCODE -ne 0) { throw "git fetch origin main failed with exit code $LASTEXITCODE" }

        $branch = (& git -C $ProjectRoot branch --show-current 2>$null | Select-Object -First 1).Trim()
        $local = (& git -C $ProjectRoot rev-parse HEAD 2>$null | Select-Object -First 1).Trim()
        $remote = (& git -C $ProjectRoot rev-parse origin/main 2>$null | Select-Object -First 1).Trim()
        $porcelain = @(& git -C $ProjectRoot status --porcelain=v1 -uall 2>$null)
        $clean = ($LASTEXITCODE -eq 0 -and $porcelain.Count -eq 0)
        $gitSummary = Get-CortexGitSummary

        $result.branch = $branch
        $result.localHead = $local
        $result.remoteHead = $remote
        $result.clean = $clean
        $result.greenMatch = [bool]$gitSummary.greenMatch
        $result.published = ($branch -eq 'main' -and $local -eq $remote -and $clean)
        $result.detail = if ($result.published) {
            'Local main exactly matches origin/main and the working tree is clean.'
        } else {
            'Local source is not yet in a clean published-main state.'
        }

        Write-CortexStatusRow 'Branch' $branch ($(if ($branch -eq 'main') {'Pass'} else {'Warn'}))
        Write-CortexStatusRow 'Local HEAD' $local 'Value'
        Write-CortexStatusRow 'origin/main' $remote 'Value'
        Write-CortexStatusRow 'Working tree' ($(if ($clean) {'Clean'} else {'Modified'})) ($(if ($clean) {'Pass'} else {'Warn'}))
        Write-CortexStatusRow 'FULL GREEN' ($(if ($gitSummary.greenMatch) {'MATCH'} else {'NOT MATCH'})) ($(if ($gitSummary.greenMatch) {'Pass'} else {'Warn'}))
        Write-CortexStatusRow 'Published' ($(if ($result.published) {'YES'} else {'NO'})) ($(if ($result.published) {'Pass'} else {'Warn'}))
    } catch {
        $result.detail = $_.Exception.Message
        Event 'FAIL' "Published-main verification failed: $($_.Exception.Message)"
    }

    try {
        New-Item -ItemType Directory -Force -Path $statusArtifactsDir | Out-Null
        ($result | ConvertTo-Json -Depth 6) |
            Set-Content -LiteralPath (Join-Path $statusArtifactsDir 'LATEST_PUBLISHED_STATE.json') -Encoding UTF8
    } catch {}

    return [bool]$result.published
}

function Invoke-RootSelfAudit {
    Write-CortexRule 'ROOT SELF-AUDIT'
    try {
        & (Join-Path $PSScriptRoot 'Test-CortexRootSelfAudit.ps1') `
            -ProjectRoot $ProjectRoot `
            -LogPath $ActiveLog `
            -ControllerVersion $ControllerVersion
        return ($LASTEXITCODE -eq 0)
    } catch {
        Event 'FAIL' "Root self-audit crashed: $($_.Exception.Message)"
        return $false
    }
}

function Invoke-ArtifactMaintenance {
    param([switch]$Prune)
    try {
        $maintenanceParams = @{
            ProjectRoot = $ProjectRoot
            LogPath = $ActiveLog
        }
        if ($Prune) { $maintenanceParams['Prune'] = $true }
        & (Join-Path $PSScriptRoot 'Invoke-CortexArtifactMaintenance.ps1') @maintenanceParams | Out-Null
        return $true
    } catch {
        Event 'FAIL' "Artifact maintenance failed: $($_.Exception.Message)"
        return $false
    }
}

function Initialize-RootPatchReceiptBaseline {
    $receiptDir = Join-Path $patchArtifactsDir 'receipts'
    $latest = Join-Path $patchArtifactsDir 'LATEST_PATCH_RECEIPT.json'
    New-Item -ItemType Directory -Force -Path $receiptDir | Out-Null

    $existing09K = $false
    foreach ($file in @(Get-ChildItem -LiteralPath $receiptDir -Filter '*.json' -File -ErrorAction SilentlyContinue)) {
        try {
            $data = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
            if ([string]$data.patchId -eq 'CTX-ROOT-09K' -and [string]$data.status -eq 'APPLIED') {
                $existing09K = $true
                break
            }
        } catch {}
    }
    if ($existing09K) { return }

    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $receipt = [ordered]@{
        schema = 'cortex.patch_receipt.v1'
        status = 'APPLIED'
        patchId = 'CTX-ROOT-09K'
        title = 'Manifest-authoritative Root Utility baseline'
        appliedUtc = (Get-Date).ToUniversalTime().ToString('o')
        migrationBaseline = $true
        controller = $ControllerVersion
        archivePath = $null
        backupPath = $null
        files = @(
            'tools/control/ProjectControlCenter.ps1',
            'tools/control/InvokeRootPatchIntake.ps1',
            'tools/control/New-CortexDebugBundle.ps1',
            'tools/control/Invoke-CortexArtifactMaintenance.ps1',
            'tools/control/Test-CortexRootSelfAudit.ps1'
        )
        removed = @()
        rollbackAttempted = $false
        rollbackSucceeded = $false
    }
    $json = $receipt | ConvertTo-Json -Depth 8
    $path = Join-Path $receiptDir ("{0}_CTX-ROOT-09K_BASELINE.json" -f $stamp)
    $json | Set-Content -LiteralPath $path -Encoding UTF8
    $json | Set-Content -LiteralPath $latest -Encoding UTF8
    Event 'PASS' 'Initialized CTX-ROOT-09K patch receipt baseline.'
}

function Show-SourceGitMenu {
    while ($true) {
        Show-Banner
        Write-CortexRule 'SOURCE CONTROL / GIT'

        Write-CortexText ' INSPECT' 'Label'
        Write-CortexText '  1. Detailed Git / branch / remote / GREEN status' 'Default'
        Write-CortexText '  2. Review working changes' 'Default'
        Write-CortexText '  3. Verify published main against origin/main' 'Default'

        Write-CortexText ' GREEN CHECKPOINT' 'Label'
        Write-CortexText ' 10. Commit current source if FULL GREEN matches' 'Pass'
        Write-CortexText ' 11. Commit + push if FULL GREEN matches' 'Pass'
        Write-CortexText ' 12. Push already-committed main' 'Default'

        Write-CortexText ' SYNC / REMOTE' 'Label'
        Write-CortexText ' 20. Pull origin/main - fast-forward only' 'Default'
        Write-CortexText ' 21. Initialize / connect / repair origin/main' 'Accent'
        Write-CortexText ' 22. Open Cortex GitHub repository' 'Default'

        Write-CortexText ' ADVANCED' 'Label'
        Write-CortexText ' 30. Manual commit - not GREEN protected' 'Warn'

        Write-CortexText '  0. Back' 'Default'
        Write-CortexText 'Select an option: ' 'Label' -NoNewline
        $choice = Read-Host

        switch ($choice) {
            '1' {
                [void](Invoke-CortexGitAction -Action 'Status')
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '2' {
                [void](Invoke-CortexGitAction -Action 'Review')
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '3' {
                [void](Test-CortexPublishedMain)
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '10' {
                $default = "Cortex GREEN checkpoint - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
                $message = Read-Host "Commit message [$default]"
                if ([string]::IsNullOrWhiteSpace($message)) { $message = $default }
                $committedGreen = Invoke-CortexGitAction -Action 'CommitGreen' -Message $message
                if ($committedGreen) {
                    [void](Test-CortexPublishedMain)
                }
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '11' {
                $default = "Cortex GREEN checkpoint - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
                $message = Read-Host "Commit message [$default]"
                if ([string]::IsNullOrWhiteSpace($message)) { $message = $default }
                $publishedCommit = Invoke-CortexGitAction -Action 'CommitPushGreen' -Message $message
                if ($publishedCommit) {
                    [void](Test-CortexPublishedMain)
                }
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '12' {
                $pushed = Invoke-CortexGitAction -Action 'Push'
                if ($pushed) {
                    [void](Test-CortexPublishedMain)
                }
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '20' {
                $pulled = Invoke-CortexGitAction -Action 'Pull'
                if ($pulled) {
                    [void](Test-CortexPublishedMain)
                }
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '21' {
                $setup = Invoke-CortexGitAction -Action 'Setup'
                if ($setup) {
                    [void](Test-CortexPublishedMain)
                }
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '22' {
                Start-Process $CortexGitRemoteUrl | Out-Null
            }
            '30' {
                $message = Read-Host 'Manual commit message'
                if ([string]::IsNullOrWhiteSpace($message)) {
                    Event 'WARN' 'Manual commit cancelled: no commit message supplied.'
                } else {
                    $manualCommitted = Invoke-CortexGitAction -Action 'ManualCommit' -Message $message
                    if ($manualCommitted) {
                        [void](Test-CortexPublishedMain)
                    }
                }
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '0' { break }
            default {
                Event 'WARN' "Unknown Source Control / Git option: $choice"
                Start-Sleep -Milliseconds 700
            }
        }
        if ($choice -eq '0') { break }
    }
}

function Show-UpdatePatchMenu {
    while ($true) {
        Show-Banner
        Write-CortexRule 'UPDATES / PATCHES'

        Write-CortexText ' INTAKE' 'Label'
        Write-CortexText '  1. Scan pending patch queue' 'Accent'
        Write-CortexText '  2. Validate pending patch queue without applying' 'Info'
        Write-CortexText '  3. Apply pending patches now' 'Accent'
        Write-CortexText '  4. Open updates inbox' 'Default'

        Write-CortexText ' HISTORY / EVIDENCE' 'Label'
        Write-CortexText ' 10. Open applied patch archives' 'Default'
        Write-CortexText ' 11. Open patch receipts' 'Default'
        Write-CortexText ' 12. Open failed / quarantined patches' 'Warn'
        Write-CortexText ' 13. Open patch recovery backups' 'Default'

        Write-CortexText '  0. Back' 'Default'
        Write-CortexText 'Select an option: ' 'Label' -NoNewline
        $choice = Read-Host

        switch ($choice) {
            '1' {
                $scan = Get-PatchScanSummary -Force
                Write-CortexRule 'PENDING PATCH SCAN'
                Write-CortexStatusRow 'Pending' ([string]$scan.Pending) ($(if ([int]$scan.Pending -gt 0) {'Warn'} else {'Pass'}))
                Write-CortexStatusRow 'Invalid' ([string]$scan.Invalid) ($(if ([int]$scan.Invalid -gt 0) {'Fail'} else {'Pass'}))
                Write-CortexStatusRow 'Ignored ZIPs' ([string]$scan.Ignored) 'Value'
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '2' {
                try {
                    $output = @(
                        & (Join-Path $PSScriptRoot 'InvokeRootPatchIntake.ps1') `
                            -ProjectRoot $ProjectRoot `
                            -LogPath $ActiveLog `
                            -ValidateOnly
                    )
                    $summary = @($output | Where-Object { $_ -is [psobject] -and $_.PSObject.Properties['Validated'] } | Select-Object -Last 1)
                    if ($summary.Count -gt 0) {
                        Write-CortexStatusRow 'Validated' ([string]$summary[0].Validated) 'Pass'
                        Write-CortexStatusRow 'Invalid' ([string]$summary[0].Invalid) ($(if ([int]$summary[0].Invalid -gt 0) {'Fail'} else {'Pass'}))
                    }
                } catch {
                    Event 'FAIL' "Patch validation failed: $($_.Exception.Message)"
                }
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '3' {
                [void](Invoke-PendingPatchApply)
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '4' { Open-CortexFolder (Join-Path $ProjectRoot 'updates\inbox') }
            '10' { Open-CortexFolder (Join-Path $patchArtifactsDir 'applied') }
            '11' { Open-CortexFolder (Join-Path $patchArtifactsDir 'receipts') }
            '12' { Open-CortexFolder (Join-Path $patchArtifactsDir 'failed') }
            '13' { Open-CortexFolder (Join-Path $recoveryArtifactsDir 'patch-backups') }
            '0' { break }
            default {
                Event 'WARN' "Unknown Updates / Patches option: $choice"
                Start-Sleep -Milliseconds 700
            }
        }
        if ($choice -eq '0') { break }
    }
}

function Invoke-RustFormatApply {
    Write-CortexRule 'APPLY RUST SOURCE FORMATTING'
    Write-CortexText ' This operation runs cargo fmt --all and modifies Rust source files.' 'Warn'
    Write-CortexText ' It is intentionally separate from Fast / Full quality gates.' 'Info'

    $ok = Invoke-CargoStep -Label 'cargo fmt --all apply' -CargoArgs @('fmt','--all')
    if ($ok) {
        Reset-CortexStatusCaches
        Event 'PASS' 'Canonical Rust formatting applied. Run Full Quality Gate next.'
    } else {
        Event 'FAIL' 'Rust formatting could not be applied.'
    }
    return [bool]$ok
}

function Show-ValidationCertificationMenu {
    while ($true) {
        Show-Banner
        Write-CortexRule 'TEST / VALIDATE / CERTIFY'

        Write-CortexText ' INDIVIDUAL CHECKS' 'Label'
        Write-CortexText '  1. Quick project gate' 'Info'
        Write-CortexText '  2. Root Utility self-audit' 'Info'
        Write-CortexText '  3. cargo fmt --all -- --check' 'Info'
        Write-CortexText '  4. cargo check --workspace --all-targets' 'Info'
        Write-CortexText '  5. cargo test --workspace --all-targets' 'Info'
        Write-CortexText '  6. cargo clippy --workspace --all-targets -D warnings' 'Info'
        Write-CortexText '  7. APPLY cargo fmt --all - modifies Rust source' 'Warn'

        Write-CortexText ' COMPOSITE GATES' 'Label'
        Write-CortexText ' 10. Fast development gate' 'Info'
        Write-CortexText ' 11. FULL QUALITY GATE' 'Pass'

        Write-CortexText ' CERTIFICATION EVIDENCE' 'Label'
        Write-CortexText ' 20. Create certification / debug bundle' 'Accent'
        Write-CortexText ' 21. Show current GREEN eligibility' 'Default'
        Write-CortexText ' 22. Open certification artifacts' 'Default'

        Write-CortexText '  0. Back' 'Default'
        Write-CortexText 'Select an option: ' 'Label' -NoNewline
        $choice = Read-Host

        switch ($choice) {
            '1' {
                $ok = Invoke-QuickGateMenuAction
                try {
                    & (Join-Path $PSScriptRoot 'New-CortexDebugBundle.ps1') `
                        -ProjectRoot $ProjectRoot `
                        -Reason ($(if ($ok) {'QUICK_GREEN'} else {'QUICK_FAIL'})) `
                        -LogPath $ActiveLog | Out-Null
                } catch {}
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '2' {
                [void](Invoke-RootSelfAudit)
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '3' {
                [void](Invoke-CargoStep -Label 'cargo fmt --check' -CargoArgs @('fmt','--all','--','--check'))
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '4' {
                [void](Invoke-CargoStep -Label 'cargo check --workspace --all-targets' -CargoArgs @('check','--workspace','--all-targets'))
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '5' {
                [void](Invoke-CargoStep -Label 'cargo test --workspace --all-targets' -CargoArgs @('test','--workspace','--all-targets'))
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '6' {
                [void](Invoke-CargoStep -Label 'cargo clippy -D warnings' -CargoArgs @('clippy','--workspace','--all-targets','--','-D','warnings'))
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '7' {
                [void](Invoke-RustFormatApply)
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '10' {
                $ok = Invoke-FastGate
                try {
                    & (Join-Path $PSScriptRoot 'New-CortexDebugBundle.ps1') `
                        -ProjectRoot $ProjectRoot `
                        -Reason ($(if ($ok) {'FAST_GREEN'} else {'FAST_FAIL'})) `
                        -LogPath $ActiveLog | Out-Null
                } catch {}
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '11' {
                $ok = Invoke-FullGate
                try {
                    & (Join-Path $PSScriptRoot 'New-CortexDebugBundle.ps1') `
                        -ProjectRoot $ProjectRoot `
                        -Reason ($(if ($ok) {'FULL_GREEN'} else {'FULL_FAIL'})) `
                        -FailedStage ($(if ($ok) {''} else {$script:LastGateFailedStage})) `
                        -ExitCode ($(if ($ok) {0} else {$script:LastGateExitCode})) `
                        -LogPath $ActiveLog `
                        -OpenFolder | Out-Null
                } catch {}
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '20' {
                & (Join-Path $PSScriptRoot 'New-CortexDebugBundle.ps1') `
                    -ProjectRoot $ProjectRoot `
                    -Reason 'MANUAL_CERTIFICATION' `
                    -LogPath $ActiveLog `
                    -OpenFolder | Out-Null
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '21' {
                [void](Invoke-CortexGitAction -Action 'Status')
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '22' {
                Open-CortexFolder $certificationArtifactsDir
            }
            '0' { break }
            default {
                Event 'WARN' "Unknown Test / Validate / Certify option: $choice"
                Start-Sleep -Milliseconds 700
            }
        }
        if ($choice -eq '0') { break }
    }
}

function Show-ArtifactRecoveryMenu {
    while ($true) {
        Show-Banner
        Write-CortexRule 'DIAGNOSTICS / ARTIFACTS'

        Write-CortexText ' BROWSE' 'Label'
        Write-CortexText '  1. Open artifacts root' 'Accent'
        Write-CortexText '  2. Open current session logs' 'Default'
        Write-CortexText '  3. Open debug bundles' 'Default'
        Write-CortexText '  4. Open build / validation receipts' 'Default'
        Write-CortexText '  5. Open certification evidence' 'Default'
        Write-CortexText '  6. Open status evidence' 'Default'

        Write-CortexText ' CREATE / MAINTAIN' 'Label'
        Write-CortexText ' 10. Create manual debug bundle' 'Accent'
        Write-CortexText ' 11. Refresh artifact latest pointers' 'Default'
        Write-CortexText ' 12. Prune old session logs / debug bundles' 'Warn'

        Write-CortexText ' PATCH / RECOVERY EVIDENCE' 'Label'
        Write-CortexText ' 20. Open patch receipts' 'Default'
        Write-CortexText ' 21. Open applied patch archives' 'Default'
        Write-CortexText ' 22. Open failed patches' 'Warn'
        Write-CortexText ' 23. Open patch recovery backups' 'Default'
        Write-CortexText ' 24. Open migrated legacy logs' 'Default'

        Write-CortexText '  0. Back' 'Default'
        Write-CortexText 'Select an option: ' 'Label' -NoNewline
        $choice = Read-Host

        switch ($choice) {
            '1' { Open-CortexFolder $ArtifactsRoot }
            '2' { Open-CortexFolder $logsDir }
            '3' { Open-CortexFolder $debugDir }
            '4' { Open-CortexFolder $buildArtifactsDir }
            '5' { Open-CortexFolder $certificationArtifactsDir }
            '6' { Open-CortexFolder $statusArtifactsDir }
            '10' {
                & (Join-Path $PSScriptRoot 'New-CortexDebugBundle.ps1') `
                    -ProjectRoot $ProjectRoot `
                    -Reason 'MANUAL' `
                    -LogPath $ActiveLog `
                    -OpenFolder | Out-Null
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '11' {
                [void](Invoke-ArtifactMaintenance)
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '12' {
                $confirm = Read-Host 'Prune old Root session logs and debug bundles using retention policy? [y/N]'
                if ($confirm -match '^(?i)y(?:es)?$') {
                    [void](Invoke-ArtifactMaintenance -Prune)
                } else {
                    Event 'INFO' 'Artifact pruning cancelled.'
                }
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '20' { Open-CortexFolder (Join-Path $patchArtifactsDir 'receipts') }
            '21' { Open-CortexFolder (Join-Path $patchArtifactsDir 'applied') }
            '22' { Open-CortexFolder (Join-Path $patchArtifactsDir 'failed') }
            '23' { Open-CortexFolder (Join-Path $recoveryArtifactsDir 'patch-backups') }
            '24' { Open-CortexFolder (Join-Path $ArtifactLogsRoot 'legacy-sessions') }
            '0' { break }
            default {
                Event 'WARN' "Unknown Diagnostics / Artifacts option: $choice"
                Start-Sleep -Milliseconds 700
            }
        }
        if ($choice -eq '0') { break }
    }
}

function Show-Banner {
    Clear-Host
    $git = Get-CortexGitSummary
    $gitValue = if (-not $git.gitReady) { 'Not a repository' } elseif ($git.clean) { 'Clean' } else { 'Modified' }
    $gitStyle = if ($gitValue -eq 'Clean') { 'Pass' } else { 'Warn' }
    $branchValue = if ($git.gitReady) {
        $head = if ($git.headShort) { [string]$git.headShort } else { '<unborn>' }
        "$($git.branch) @ $head"
    } else { 'Unavailable' }
    $syncValue = if ($git.gitReady -and $null -ne $git.ahead -and $null -ne $git.behind) {
        if ([int]$git.ahead -eq 0 -and [int]$git.behind -eq 0) { 'Synced with origin/main' }
        else { "$($git.ahead) ahead / $($git.behind) behind" }
    } else { 'No upstream state' }
    $greenValue = if ($git.greenMatch) { 'MATCH' } elseif ($git.greenMarker) { 'STALE / CHANGED' } else { 'No marker' }
    $greenStyle = if ($git.greenMatch) { 'Pass' } else { 'Warn' }

    Write-CortexRule 'CORTEX ROOT UTILITY / NATIVE PROJECT CONTROL'
    Write-CortexStatusRow 'Controller' $ControllerVersion 'Accent'
    Write-CortexStatusRow 'Repository' $ProjectRoot
    Write-CortexStatusRow 'Git' $gitValue $gitStyle
    Write-CortexStatusRow 'Branch' $branchValue ($(if ($git.gitReady) {'Value'} else {'Warn'}))
    Write-CortexStatusRow 'Sync' $syncValue ($(if ($syncValue -eq 'Synced with origin/main') {'Pass'} else {'Warn'}))
    Write-CortexStatusRow 'FULL GREEN' $greenValue $greenStyle
    $patchScan = Get-PatchScanSummary
    $updateValue = if ([int]$patchScan.Pending -gt 0) {
        "$($patchScan.Pending) pending"
    } else {
        'None pending'
    }
    $updateStyle = if ([int]$patchScan.Invalid -gt 0) {
        'Fail'
    } elseif ([int]$patchScan.Pending -gt 0) {
        'Warn'
    } else {
        'Pass'
    }
    Write-CortexStatusRow 'Updates' $updateValue $updateStyle
    Write-CortexStatusRow 'Cargo' (Get-StatusValue Cargo) ($(if ((Get-StatusValue Cargo) -eq 'Ready') {'Pass'} else {'Fail'}))
    Write-CortexStatusRow 'Workspace' (Get-StatusValue Workspace) ($(if ((Get-StatusValue Workspace) -eq 'Ready') {'Pass'} else {'Fail'}))
    Write-CortexStatusRow 'Cortex CLI' (Get-StatusValue CLI) ($(if ((Get-StatusValue CLI) -eq 'Ready') {'Pass'} else {'Warn'}))
    Write-CortexStatusRow 'Cortex GUI' (Get-StatusValue GUI) ($(if ((Get-StatusValue GUI) -eq 'Ready') {'Pass'} else {'Warn'}))
    Write-CortexStatusRow 'Active log' $ActiveLog 'Value'
}

function Invoke-StartupSequence {
    Write-CortexRule 'STARTUP PATCH INTAKE'

    $patchSummary = $null
    try {
        $patchOutput = @(
            & (Join-Path $PSScriptRoot 'InvokeRootPatchIntake.ps1') `
                -ProjectRoot $ProjectRoot `
                -LogPath $ActiveLog
        )
        $patchResult = @(
            $patchOutput |
                Where-Object {
                    $_ -is [psobject] -and
                    $_.PSObject.Properties['Applied']
                } |
                Select-Object -Last 1
        )
        if ($patchResult.Count -gt 0) {
            $patchSummary = $patchResult[0]
        }
    } catch {
        Event 'FAIL' "Startup root patch intake failed: $($_.Exception.Message)"
        try {
            & (Join-Path $PSScriptRoot 'New-CortexDebugBundle.ps1') `
                -ProjectRoot $ProjectRoot `
                -Reason 'PATCH_INTAKE_FAIL' `
                -LogPath $ActiveLog `
                -OpenFolder | Out-Null
        } catch {}
        throw
    }

    Reset-CortexStatusCaches

    if ($patchSummary -and $patchSummary.RestartRequired) {
        [void](Restart-CortexRootUtility)
        return
    }

    if ($patchSummary -and [int]$patchSummary.Applied -gt 0) {
        Event 'PASS' ("Startup patch intake applied {0} patch(es)." -f [int]$patchSummary.Applied)
    } else {
        Event 'PASS' 'Startup patch intake: no pending patches.'
    }

    Write-CortexRule 'STARTUP QUICK GATE'
    $quickCode = 1
    try {
        & (Join-Path $PSScriptRoot 'Test-CortexQuickGate.ps1') `
            -ProjectRoot $ProjectRoot `
            -LogPath $ActiveLog
        $quickCode = $LASTEXITCODE
    } catch {
        Event 'FAIL' "Startup quick gate crashed: $($_.Exception.Message)"
    }

    try {
        & (Join-Path $PSScriptRoot 'New-CortexDebugBundle.ps1') `
            -ProjectRoot $ProjectRoot `
            -Reason ($(if ($quickCode -eq 0) {'STARTUP_GREEN'} else {'STARTUP_FAIL'})) `
            -FailedStage ($(if ($quickCode -eq 0) {''} else {'startup-quick-gate'})) `
            -ExitCode $quickCode `
            -LogPath $ActiveLog `
            -OpenFolder | Out-Null
    } catch {
        Event 'FAIL' "Debug bundle generation failed: $($_.Exception.Message)"
    }

    [void](Invoke-ArtifactMaintenance)

    if ($quickCode -ne 0) {
        Event 'FAIL' 'Startup Quick Gate failed. Repair startup health before running Full Quality.'
    }

    Write-CortexRule
}

function Invoke-FastGate {
    Write-CortexRule 'FAST DEVELOPMENT GATE'
    & (Join-Path $PSScriptRoot 'Test-CortexQuickGate.ps1') -ProjectRoot $ProjectRoot -LogPath $ActiveLog
    if ($LASTEXITCODE -ne 0) { return $false }
    if (-not (Invoke-CargoStep -Label 'cargo check --workspace --all-targets' -CargoArgs @('check','--workspace','--all-targets'))) { return $false }
    Event 'PASS' 'Fast development gate GREEN.'
    return $true
}

function Invoke-FullGate {
    Write-CortexRule 'FULL QUALITY GATE'
    $script:LastGateFailedStage = ''
    $script:LastGateExitCode = 0
    $script:LastCargoDiagnosticsPath = ''

    & (Join-Path $PSScriptRoot 'Test-CortexQuickGate.ps1') -ProjectRoot $ProjectRoot -LogPath $ActiveLog
    if ($LASTEXITCODE -ne 0) {
        $script:LastGateFailedStage = 'startup-quick-gate'
        $script:LastGateExitCode = [int]$LASTEXITCODE
        return $false
    }

    if (-not (Invoke-RootSelfAudit)) {
        $script:LastGateFailedStage = 'root-self-audit'
        $script:LastGateExitCode = 1
        return $false
    }

    if (-not (Invoke-CargoStep -Label 'cargo fmt --check' -CargoArgs @('fmt','--all','--','--check'))) { return $false }
    if (-not (Invoke-CargoStep -Label 'cargo check' -CargoArgs @('check','--workspace','--all-targets'))) { return $false }
    if (-not (Invoke-CargoStep -Label 'cargo test' -CargoArgs @('test','--workspace','--all-targets'))) { return $false }
    if (-not (Invoke-CargoStep -Label 'cargo clippy -D warnings' -CargoArgs @('clippy','--workspace','--all-targets','--','-D','warnings'))) { return $false }
    if (-not (Invoke-CargoStep -Label 'cargo build' -CargoArgs @('build','--workspace'))) { return $false }

    Event 'PASS' 'FULL QUALITY GATE GREEN.'
    Write-CortexGreenMarker
    Reset-CortexStatusCaches
    [void](Invoke-ArtifactMaintenance)
    return $true
}

function Invoke-CargoClean {
    Write-CortexRule 'CARGO CLEAN'
    Event 'INFO' 'START cargo clean'
    Push-Location $ProjectRoot
    try {
        & cargo clean
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
        Set-CortexConsoleDefaults
    }
    if ($code -ne 0) {
        Event 'FAIL' "cargo clean failed with exit code $code"
        return $false
    }
    $script:CargoTargetDirectory = $null
    Reset-CortexStatusCaches
    Event 'PASS' 'cargo clean'
    return $true
}

function Invoke-RunCortexCliHelp {
    $cli = Get-CortexBinaryPath CLI
    if (-not $cli -or -not (Test-Path -LiteralPath $cli -PathType Leaf)) {
        Event 'INFO' 'Cortex CLI is not built; building package cortex.'
        if (-not (Invoke-BuildPackage -Package 'cortex' -Label 'Cortex CLI')) {
            return $false
        }
        $cli = Get-CortexBinaryPath CLI
    }
    if (-not $cli -or -not (Test-Path -LiteralPath $cli -PathType Leaf)) {
        Event 'FAIL' 'Cortex CLI executable was not found after build.'
        return $false
    }
    Write-CortexRule 'CORTEX CLI --HELP'
    Push-Location $ProjectRoot
    try {
        & $cli --help
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
        Set-CortexConsoleDefaults
    }
    if ($code -ne 0) {
        Event 'FAIL' "Cortex CLI --help failed with exit code $code"
        return $false
    }
    Event 'PASS' 'Cortex CLI launched successfully.'
    return $true
}

function Show-BuildRunMenu {
    while ($true) {
        Show-Banner
        Write-CortexRule 'BUILD / RUN'

        Write-CortexText ' BUILD TARGETS' 'Label'
        Write-CortexText '  1. Build entire workspace - debug' 'Default'
        Write-CortexText '  2. Build Cortex CLI' 'Default'
        Write-CortexText '  3. Build Cortex GUI / Desktop' 'Default'
        Write-CortexText '  4. Build Cortex CLI + GUI' 'Default'
        Write-CortexText '  5. Build entire workspace - release' 'Accent'

        Write-CortexText ' RUN TARGETS' 'Label'
        Write-CortexText ' 10. Launch Cortex GUI / Project Control' 'Default'
        Write-CortexText ' 11. Run Cortex CLI --help' 'Default'

        Write-CortexText ' BUILD MAINTENANCE' 'Label'
        Write-CortexText ' 20. cargo clean' 'Warn'
        Write-CortexText ' 21. Clean + rebuild entire workspace' 'Warn'

        Write-CortexText '  0. Back' 'Default'
        Write-CortexText 'Select an option: ' 'Label' -NoNewline
        $choice = Read-Host

        switch ($choice) {
            '1' {
                $ok = Invoke-CargoStep -Label 'Build Cortex workspace' -CargoArgs @('build','--workspace')
                if ($ok) { $script:CargoTargetDirectory = $null; Reset-CortexStatusCaches }
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '2' {
                [void](Invoke-BuildPackage -Package 'cortex' -Label 'Cortex CLI')
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '3' {
                [void](Invoke-BuildPackage -Package 'cortex_desktop' -Label 'Cortex Desktop')
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '4' {
                $cliOk = Invoke-BuildPackage -Package 'cortex' -Label 'Cortex CLI'
                $guiOk = $false
                if ($cliOk) {
                    $guiOk = Invoke-BuildPackage -Package 'cortex_desktop' -Label 'Cortex Desktop'
                }
                if ($cliOk -and $guiOk) {
                    Event 'PASS' 'Cortex CLI + GUI build complete.'
                }
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '5' {
                $ok = Invoke-CargoStep -Label 'Build Cortex workspace - release' -CargoArgs @('build','--workspace','--release')
                if ($ok) { $script:CargoTargetDirectory = $null; Reset-CortexStatusCaches }
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '10' {
                $launched = Start-CortexDesktop
                if (-not $launched) { Read-Host 'Press Enter to continue' | Out-Null }
            }
            '11' {
                [void](Invoke-RunCortexCliHelp)
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '20' {
                $confirm = Read-Host 'Run cargo clean and remove build outputs? [y/N]'
                if ($confirm -match '^(?i)y(?:es)?$') {
                    [void](Invoke-CargoClean)
                } else {
                    Event 'INFO' 'cargo clean cancelled.'
                }
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '21' {
                $confirm = Read-Host 'Clean + rebuild the entire workspace? [y/N]'
                if ($confirm -match '^(?i)y(?:es)?$') {
                    if (Invoke-CargoClean) {
                        $ok = Invoke-CargoStep -Label 'Rebuild Cortex workspace' -CargoArgs @('build','--workspace')
                        if ($ok) { $script:CargoTargetDirectory = $null; Reset-CortexStatusCaches }
                    }
                } else {
                    Event 'INFO' 'Clean + rebuild cancelled.'
                }
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '0' { break }
            default {
                Event 'WARN' "Unknown Build / Run option: $choice"
                Start-Sleep -Milliseconds 700
            }
        }

        if ($choice -eq '0') { break }
    }
}

function Invoke-FullQualityFromMenu {
    $ok = Invoke-FullGate
    try {
        & (Join-Path $PSScriptRoot 'New-CortexDebugBundle.ps1') `
            -ProjectRoot $ProjectRoot `
            -Reason ($(if ($ok) {'FULL_GREEN'} else {'FULL_FAIL'})) `
            -FailedStage ($(if ($ok) {''} else {$script:LastGateFailedStage})) `
            -ExitCode ($(if ($ok) {0} else {$script:LastGateExitCode})) `
            -LogPath $ActiveLog `
            -OpenFolder | Out-Null
    } catch {
        Event 'WARN' "Could not create Full Quality debug bundle: $($_.Exception.Message)"
    }
    return $ok
}

function Invoke-ValidateCurrentSource {
    Write-CortexRule 'VALIDATE CURRENT SOURCE'
    if (-not (Invoke-RootSelfAudit)) { return $false }
    if (-not (Invoke-CargoStep -Label 'cargo fmt --check' -CargoArgs @('fmt','--all','--','--check'))) { return $false }
    if (-not (Invoke-CargoStep -Label 'cargo check' -CargoArgs @('check','--workspace','--all-targets'))) { return $false }
    if (-not (Invoke-CargoStep -Label 'cargo clippy -D warnings' -CargoArgs @('clippy','--workspace','--all-targets','--','-D','warnings'))) { return $false }
    Event 'PASS' 'Current source validation GREEN.'
    return $true
}

function Open-CortexTextFile {
    param([Parameter(Mandatory=$true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Event 'WARN' "File not found: $Path"
        return
    }
    try {
        Start-Process notepad.exe -ArgumentList "`"$Path`"" | Out-Null
    } catch {
        Start-Process explorer.exe -ArgumentList "/select,`"$Path`"" | Out-Null
    }
}

function Show-BuildVerifyMenu {
    while ($true) {
        Show-Banner
        Write-CortexRule 'BUILD & VERIFY'
        Write-CortexText '  1. Full quality gate' 'Pass'
        Write-CortexText '     Quick gate + root self-audit + fmt + check + tests + clippy + build + GREEN + debug bundle' 'Muted'
        Write-CortexText '  2. Build all' 'Default'
        Write-CortexText '  3. Run tests' 'Default'
        Write-CortexText '  4. Validate current source' 'Info'
        Write-CortexText '  5. Check native CLI / GUI / workspace' 'Default'
        Write-CortexText '  6. Build native applications (CLI + GUI)' 'Default'
        Write-CortexText '  7. Fast development gate' 'Info'
        Write-CortexText '  8. Root Utility self-audit' 'Info'
        Write-CortexText '  0. Back' 'Default'
        Write-CortexText 'Select an option: ' 'Label' -NoNewline
        $choice = Read-Host

        switch ($choice) {
            '1' {
                [void](Invoke-FullQualityFromMenu)
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '2' {
                $ok = Invoke-CargoStep -Label 'Build Cortex workspace' -CargoArgs @('build','--workspace')
                if ($ok) { $script:CargoTargetDirectory = $null; Reset-CortexStatusCaches }
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '3' {
                [void](Invoke-CargoStep -Label 'cargo test --workspace --all-targets' -CargoArgs @('test','--workspace','--all-targets'))
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '4' {
                [void](Invoke-ValidateCurrentSource)
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '5' {
                Show-Status
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '6' {
                $cliOk = Invoke-BuildPackage -Package 'cortex' -Label 'Cortex CLI'
                $guiOk = $false
                if ($cliOk) {
                    $guiOk = Invoke-BuildPackage -Package 'cortex_desktop' -Label 'Cortex Desktop'
                }
                if ($cliOk -and $guiOk) {
                    Event 'PASS' 'Native Cortex applications built successfully.'
                }
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '7' {
                $ok = Invoke-FastGate
                try {
                    & (Join-Path $PSScriptRoot 'New-CortexDebugBundle.ps1') `
                        -ProjectRoot $ProjectRoot `
                        -Reason ($(if ($ok) {'FAST_GREEN'} else {'FAST_FAIL'})) `
                        -LogPath $ActiveLog | Out-Null
                } catch {}
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '8' {
                [void](Invoke-RootSelfAudit)
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '0' { break }
            default {
                Event 'WARN' "Unknown Build & Verify option: $choice"
                Start-Sleep -Milliseconds 700
            }
        }
        if ($choice -eq '0') { break }
    }
}

function Show-RunLaunchMenu {
    while ($true) {
        Show-Banner
        Write-CortexRule 'RUN & LAUNCH'
        Write-CortexText '  1. Launch Cortex GUI / Project Control' 'Default'
        Write-CortexText '  2. Run Cortex CLI --help' 'Default'
        Write-CortexText '  3. Open project folder' 'Default'
        Write-CortexText '  0. Back' 'Default'
        Write-CortexText 'Select an option: ' 'Label' -NoNewline
        $choice = Read-Host

        switch ($choice) {
            '1' {
                $launched = Start-CortexDesktop
                if (-not $launched) { Read-Host 'Press Enter to continue' | Out-Null }
            }
            '2' {
                [void](Invoke-RunCortexCliHelp)
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '3' { Open-CortexFolder $ProjectRoot }
            '0' { break }
            default {
                Event 'WARN' "Unknown Run & Launch option: $choice"
                Start-Sleep -Milliseconds 700
            }
        }
        if ($choice -eq '0') { break }
    }
}

function Show-ProjectWorkspaceMenu {
    while ($true) {
        Show-Banner
        Write-CortexRule 'PROJECT & WORKSPACE TOOLS'
        Write-CortexText '  1. Project status / health' 'Default'
        Write-CortexText '  2. Root Utility self-audit' 'Info'
        Write-CortexText '  3. Open project root' 'Default'
        Write-CortexText '  4. Open artifacts root' 'Default'
        Write-CortexText '  5. Open updates inbox' 'Default'
        Write-CortexText '  0. Back' 'Default'
        Write-CortexText 'Select an option: ' 'Label' -NoNewline
        $choice = Read-Host

        switch ($choice) {
            '1' { Show-Status; Read-Host 'Press Enter to continue' | Out-Null }
            '2' { [void](Invoke-RootSelfAudit); Read-Host 'Press Enter to continue' | Out-Null }
            '3' { Open-CortexFolder $ProjectRoot }
            '4' { Open-CortexFolder $ArtifactsRoot }
            '5' { Open-CortexFolder (Join-Path $ProjectRoot 'updates\inbox') }
            '0' { break }
            default {
                Event 'WARN' "Unknown Project & Workspace option: $choice"
                Start-Sleep -Milliseconds 700
            }
        }
        if ($choice -eq '0') { break }
    }
}

function Show-MaintenanceDiagnosticsMenu {
    while ($true) {
        Show-Banner
        Write-CortexRule 'PROJECT MAINTENANCE & DIAGNOSTICS'
        Write-CortexText '  1. Artifact maintenance / retention' 'Default'
        Write-CortexText '  2. cargo clean' 'Warn'
        Write-CortexText '  3. Clean + rebuild workspace' 'Warn'
        Write-CortexText '  4. Create manual debug bundle' 'Accent'
        Write-CortexText '  5. Root Utility self-audit' 'Info'
        Write-CortexText '  6. Project status / health' 'Default'
        Write-CortexText '  0. Back' 'Default'
        Write-CortexText 'Select an option: ' 'Label' -NoNewline
        $choice = Read-Host

        switch ($choice) {
            '1' { [void](Invoke-ArtifactMaintenance); Read-Host 'Press Enter to continue' | Out-Null }
            '2' {
                $confirm = Read-Host 'Run cargo clean and remove current build outputs? [y/N]'
                if ($confirm -match '^(?i)y(?:es)?$') { [void](Invoke-CargoClean) }
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '3' {
                $confirm = Read-Host 'Clean and rebuild the entire Cortex workspace? [y/N]'
                if ($confirm -match '^(?i)y(?:es)?$') {
                    if (Invoke-CargoClean) {
                        $ok = Invoke-CargoStep -Label 'Rebuild Cortex workspace' -CargoArgs @('build','--workspace')
                        if ($ok) { $script:CargoTargetDirectory = $null; Reset-CortexStatusCaches }
                    }
                }
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '4' {
                & (Join-Path $PSScriptRoot 'New-CortexDebugBundle.ps1') `
                    -ProjectRoot $ProjectRoot `
                    -Reason 'MANUAL' `
                    -LogPath $ActiveLog `
                    -OpenFolder | Out-Null
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '5' { [void](Invoke-RootSelfAudit); Read-Host 'Press Enter to continue' | Out-Null }
            '6' { Show-Status; Read-Host 'Press Enter to continue' | Out-Null }
            '0' { break }
            default {
                Event 'WARN' "Unknown Maintenance & Diagnostics option: $choice"
                Start-Sleep -Milliseconds 700
            }
        }
        if ($choice -eq '0') { break }
    }
}

function Show-UpdatesRecoveryMenu {
    while ($true) {
        Show-Banner
        Write-CortexRule 'UPDATES & RECOVERY'
        Write-CortexText '  1. Scan pending patches' 'Accent'
        Write-CortexText '  2. Validate pending patch queue' 'Accent'
        Write-CortexText '  3. Apply pending patches now' 'Accent'
        Write-CortexText '  4. Open updates inbox' 'Default'
        Write-CortexText '  5. Open applied patch history' 'Default'
        Write-CortexText '  6. Open failed patch history' 'Warn'
        Write-CortexText '  7. Open patch receipts' 'Default'
        Write-CortexText '  8. Open recovery backups' 'Default'
        Write-CortexText '  0. Back' 'Default'
        Write-CortexText 'Select an option: ' 'Label' -NoNewline
        $choice = Read-Host

        switch ($choice) {
            '1' {
                $scan = Get-PatchScanSummary -Force
                Write-CortexStatusRow 'Pending' ([string]$scan.Pending) ($(if ([int]$scan.Pending -gt 0) {'Warn'} else {'Pass'}))
                Write-CortexStatusRow 'Invalid' ([string]$scan.Invalid) ($(if ([int]$scan.Invalid -gt 0) {'Fail'} else {'Pass'}))
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '2' {
                try {
                    $output = @(
                        & (Join-Path $PSScriptRoot 'InvokeRootPatchIntake.ps1') `
                            -ProjectRoot $ProjectRoot `
                            -LogPath $ActiveLog `
                            -ValidateOnly
                    )
                    $summary = @(
                        $output |
                            Where-Object { $_ -is [psobject] -and $_.PSObject.Properties['Validated'] } |
                            Select-Object -Last 1
                    )
                    if ($summary.Count -gt 0) {
                        Write-CortexStatusRow 'Validated' ([string]$summary[0].Validated) 'Pass'
                        Write-CortexStatusRow 'Invalid' ([string]$summary[0].Invalid) ($(if ([int]$summary[0].Invalid -gt 0) {'Fail'} else {'Pass'}))
                    }
                } catch {
                    Event 'FAIL' "Patch validation failed: $($_.Exception.Message)"
                }
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '3' { [void](Invoke-PendingPatchApply); Read-Host 'Press Enter to continue' | Out-Null }
            '4' { Open-CortexFolder (Join-Path $ProjectRoot 'updates\inbox') }
            '5' { Open-CortexFolder (Join-Path $ArtifactsRoot 'patches\applied') }
            '6' { Open-CortexFolder (Join-Path $ArtifactsRoot 'patches\failed') }
            '7' { Open-CortexFolder (Join-Path $ArtifactsRoot 'patches\receipts') }
            '8' { Open-CortexFolder (Join-Path $ArtifactsRoot 'recovery\patch-backups') }
            '0' { break }
            default {
                Event 'WARN' "Unknown Updates & Recovery option: $choice"
                Start-Sleep -Milliseconds 700
            }
        }
        if ($choice -eq '0') { break }
    }
}

function Show-ArtifactsEvidenceMenu {
    while ($true) {
        Show-Banner
        Write-CortexRule 'ARTIFACTS & EVIDENCE'
        Write-CortexText '  1. Open artifacts root' 'Default'
        Write-CortexText '  2. Open debug bundles' 'Default'
        Write-CortexText '  3. Open build receipts' 'Default'
        Write-CortexText '  4. Open certification evidence' 'Default'
        Write-CortexText '  5. Open patch receipts' 'Default'
        Write-CortexText '  6. Open status evidence' 'Default'
        Write-CortexText '  7. Run artifact maintenance' 'Default'
        Write-CortexText '  0. Back' 'Default'
        Write-CortexText 'Select an option: ' 'Label' -NoNewline
        $choice = Read-Host

        switch ($choice) {
            '1' { Open-CortexFolder $ArtifactsRoot }
            '2' { Open-CortexFolder $debugDir }
            '3' { Open-CortexFolder $buildArtifactsDir }
            '4' { Open-CortexFolder $certificationArtifactsDir }
            '5' { Open-CortexFolder (Join-Path $ArtifactsRoot 'patches\receipts') }
            '6' { Open-CortexFolder $statusArtifactsDir }
            '7' { [void](Invoke-ArtifactMaintenance); Read-Host 'Press Enter to continue' | Out-Null }
            '0' { break }
            default {
                Event 'WARN' "Unknown Artifacts & Evidence option: $choice"
                Start-Sleep -Milliseconds 700
            }
        }
        if ($choice -eq '0') { break }
    }
}

function Show-LogsHelpMenu {
    while ($true) {
        Show-Banner
        Write-CortexRule 'LOGS & HELP'
        Write-CortexText '  1. View active session log' 'Default'
        Write-CortexText '  2. Open logs folder' 'Default'
        Write-CortexText '  3. Open latest debug-bundle pointer' 'Default'
        Write-CortexText '  4. Open latest build receipt' 'Default'
        Write-CortexText '  5. Open latest patch receipt' 'Default'
        Write-CortexText '  6. Open latest Root self-audit' 'Default'
        Write-CortexText '  7. Open latest Root status' 'Default'
        Write-CortexText '  8. Open Root Utility 09B-09K spec' 'Default'
        Write-CortexText '  0. Back' 'Default'
        Write-CortexText 'Select an option: ' 'Label' -NoNewline
        $choice = Read-Host

        switch ($choice) {
            '1' { Open-CortexTextFile $ActiveLog }
            '2' { Open-CortexFolder $logsDir }
            '3' { Open-CortexTextFile (Join-Path $debugDir 'LATEST_DEBUG_BUNDLE.txt') }
            '4' { Open-CortexTextFile (Join-Path $buildArtifactsDir 'LATEST_BUILD_RECEIPT.json') }
            '5' { Open-CortexTextFile (Join-Path $patchArtifactsDir 'LATEST_PATCH_RECEIPT.json') }
            '6' { Open-CortexTextFile (Join-Path $certificationArtifactsDir 'LATEST_ROOT_SELF_AUDIT.json') }
            '7' { Open-CortexTextFile (Join-Path $statusArtifactsDir 'LATEST_ROOT_STATUS.json') }
            '8' { Open-CortexTextFile (Join-Path $ProjectRoot 'docs\cortex\root\CTX_ROOT_09B_09K_10PASS.md') }
            '0' { break }
            default {
                Event 'WARN' "Unknown Logs & Help option: $choice"
                Start-Sleep -Milliseconds 700
            }
        }
        if ($choice -eq '0') { break }
    }
}

function Show-AdvancedCommandsMenu {
    while ($true) {
        Show-Banner
        Write-CortexRule 'ADVANCED / ALL REGISTERED COMMANDS'
        Write-CortexText '  1. Advanced Build / Run commands' 'Default'
        Write-CortexText '  2. Advanced Test / Validate / Certify commands' 'Default'
        Write-CortexText '  3. Advanced Updates / Patch commands' 'Default'
        Write-CortexText '  4. Diagnostics / Artifact commands' 'Default'
        Write-CortexText '  5. Project status / health' 'Default'
        Write-CortexText '  0. Back' 'Default'
        Write-CortexText 'Select an option: ' 'Label' -NoNewline
        $choice = Read-Host

        switch ($choice) {
            '1' { Show-BuildRunMenu }
            '2' { Show-ValidationCertificationMenu }
            '3' { Show-UpdatePatchMenu }
            '4' { Show-ArtifactRecoveryMenu }
            '5' { Show-Status; Read-Host 'Press Enter to continue' | Out-Null }
            '0' { break }
            default {
                Event 'WARN' "Unknown Advanced command option: $choice"
                Start-Sleep -Milliseconds 700
            }
        }
        if ($choice -eq '0') { break }
    }
}

function Show-Status {
    Show-Banner
    Write-CortexRule 'PROJECT STATUS / HEALTH'

    $metadata = Get-CargoMetadata
    $target = Get-CargoTargetDirectory
    $cli = Get-CortexBinaryDescriptor -Kind CLI
    $gui = Get-CortexBinaryDescriptor -Kind GUI
    $git = Get-CortexGitSummary
    $patchScan = Get-PatchScanSummary -Force

    $workspacePackages = 0
    if ($metadata -and $metadata.packages) { $workspacePackages = @($metadata.packages).Count }

    $latestPatch = $null
    $latestPatchPath = Join-Path $patchArtifactsDir 'LATEST_PATCH_RECEIPT.json'
    if (Test-Path -LiteralPath $latestPatchPath -PathType Leaf) {
        try { $latestPatch = Get-Content -LiteralPath $latestPatchPath -Raw | ConvertFrom-Json } catch {}
    }

    $selfAudit = $null
    $selfAuditPath = Join-Path $certificationArtifactsDir 'LATEST_ROOT_SELF_AUDIT.json'
    if (Test-Path -LiteralPath $selfAuditPath -PathType Leaf) {
        try { $selfAudit = Get-Content -LiteralPath $selfAuditPath -Raw | ConvertFrom-Json } catch {}
    }

    $latestBuild = $null
    $latestBuildPath = Join-Path $buildArtifactsDir 'LATEST_BUILD_RECEIPT.json'
    if (Test-Path -LiteralPath $latestBuildPath -PathType Leaf) {
        try { $latestBuild = Get-Content -LiteralPath $latestBuildPath -Raw | ConvertFrom-Json } catch {}
    }

    Write-CortexText ' TOOLCHAIN / WORKSPACE' 'Label'
    Write-CortexStatusRow 'Cargo target' ($(if ($target) {$target} else {'Unavailable'})) 'Value'
    Write-CortexStatusRow 'Workspace packages' ([string]$workspacePackages) ($(if ($workspacePackages -gt 0) {'Pass'} else {'Warn'}))
    Write-CortexStatusRow 'Pending patches' ([string]$patchScan.Pending) ($(if ([int]$patchScan.Pending -gt 0) {'Warn'} else {'Pass'}))
    Write-CortexStatusRow 'Invalid patches' ([string]$patchScan.Invalid) ($(if ([int]$patchScan.Invalid -gt 0) {'Fail'} else {'Pass'}))

    Write-CortexText ' NATIVE TARGETS' 'Label'
    Write-CortexStatusRow 'CLI package/target' "$($cli.Package) / $($cli.TargetName)" 'Value'
    Write-CortexStatusRow 'CLI binary' ($(if ($cli.Exists) {$cli.Path} else {"Not built - expected $($cli.Path)"})) ($(if ($cli.Exists) {'Pass'} else {'Warn'}))
    Write-CortexStatusRow 'GUI package/target' "$($gui.Package) / $($gui.TargetName)" 'Value'
    Write-CortexStatusRow 'GUI binary' ($(if ($gui.Exists) {$gui.Path} else {"Not built - expected $($gui.Path)"})) ($(if ($gui.Exists) {'Pass'} else {'Warn'}))

    Write-CortexText ' SOURCE' 'Label'
    if ($git.gitReady) {
        Write-CortexStatusRow 'Git branch' "$($git.branch) @ $($git.headShort)" 'Value'
        $sync = if ($null -ne $git.ahead -and $null -ne $git.behind) { "$($git.ahead) ahead / $($git.behind) behind" } else { 'Unavailable' }
        Write-CortexStatusRow 'Git sync' $sync ($(if ($git.ahead -eq 0 -and $git.behind -eq 0) {'Pass'} else {'Warn'}))
        Write-CortexStatusRow 'GREEN match' ($(if ($git.greenMatch) {'YES'} else {'NO'})) ($(if ($git.greenMatch) {'Pass'} else {'Warn'}))
    } else {
        Write-CortexStatusRow 'Git' 'Not initialized' 'Warn'
    }

    Write-CortexText ' EVIDENCE' 'Label'
    Write-CortexStatusRow 'Artifacts' $ArtifactsRoot 'Value'
    Write-CortexStatusRow 'Last patch' ($(if ($latestPatch) {"$($latestPatch.status) - $($latestPatch.patchId)"} else {'No receipt yet'})) ($(if ($latestPatch -and $latestPatch.status -eq 'APPLIED') {'Pass'} elseif ($latestPatch) {'Warn'} else {'Value'}))
    Write-CortexStatusRow 'Root self-audit' ($(if ($selfAudit) {$selfAudit.status} else {'Not run yet'})) ($(if ($selfAudit -and $selfAudit.status -eq 'GREEN') {'Pass'} elseif ($selfAudit) {'Fail'} else {'Warn'}))
    Write-CortexStatusRow 'Last Cargo run' ($(if ($latestBuild) {"$($latestBuild.label) / exit $($latestBuild.exitCode)"} else {'No receipt yet'})) ($(if ($latestBuild -and $latestBuild.success) {'Pass'} elseif ($latestBuild) {'Fail'} else {'Value'}))

    try {
        $snapshot = [ordered]@{
            schema = 'cortex.root_status.v1'
            createdUtc = (Get-Date).ToUniversalTime().ToString('o')
            controller = $ControllerVersion
            projectRoot = $ProjectRoot
            workspacePackages = $workspacePackages
            cargoTarget = $target
            pendingPatches = [int]$patchScan.Pending
            invalidPatches = [int]$patchScan.Invalid
            cli = @{
                package = $cli.Package
                target = $cli.TargetName
                path = $cli.Path
                exists = [bool]$cli.Exists
                profile = $cli.Profile
            }
            gui = @{
                package = $gui.Package
                target = $gui.TargetName
                path = $gui.Path
                exists = [bool]$gui.Exists
                profile = $gui.Profile
            }
            git = $git
            latestPatch = $latestPatch
            rootSelfAudit = $selfAudit
            latestCargoRun = $latestBuild
        }
        ($snapshot | ConvertTo-Json -Depth 12) |
            Set-Content -LiteralPath (Join-Path $statusArtifactsDir 'LATEST_ROOT_STATUS.json') -Encoding UTF8
        Event 'PASS' 'Root status snapshot updated.'
    } catch {
        Event 'WARN' "Could not write root status snapshot: $($_.Exception.Message)"
    }
}


Move-CortexLegacyRootSessionLogs
Initialize-RootPatchReceiptBaseline
Invoke-StartupSequence

try {
    while ($true) {
        Show-Banner
        Write-CortexRule 'CORTEX PROJECT CONTROL CENTER'
        Write-CortexText '  1. Build & verify' 'Pass'
        Write-CortexText '  2. Run & launch' 'Default'
        Write-CortexText '  3. Project & workspace tools' 'Default'
        Write-CortexText '  4. Project maintenance & diagnostics' 'Default'
        Write-CortexText '  5. Updates & recovery' 'Accent'
        Write-CortexText '  6. Artifacts & evidence' 'Default'
        Write-CortexText '  7. Logs & help' 'Default'
        Write-CortexText '  8. Advanced / all registered commands' 'Warn'
        Write-CortexText '  9. Source control (GitHub optional)' 'Accent'
        Write-CortexText '  0. Exit' 'Default'
        Write-CortexText 'Select an option: ' 'Label' -NoNewline

        $choice = Read-Host
        switch ($choice) {
            '1' { Show-BuildVerifyMenu }
            '2' { Show-RunLaunchMenu }
            '3' { Show-ProjectWorkspaceMenu }
            '4' { Show-MaintenanceDiagnosticsMenu }
            '5' { Show-UpdatesRecoveryMenu }
            '6' { Show-ArtifactsEvidenceMenu }
            '7' { Show-LogsHelpMenu }
            '8' { Show-AdvancedCommandsMenu }
            '9' { Show-SourceGitMenu }
            '0' { break }
            default {
                Event 'WARN' "Unknown option: $choice"
                Start-Sleep -Milliseconds 700
            }
        }

        if ($choice -eq '0') { break }
    }
} finally {
    if ($transcriptStarted) { try { Stop-Transcript | Out-Null } catch {} }
    Set-CortexConsoleDefaults
}
