[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$ControllerVersion = 'CTX-ROOT-09A2R2'
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
New-Item -ItemType Directory -Force -Path @(
    $ArtifactsRoot,
    $ArtifactLogsRoot,
    $logsDir,
    $debugDir,
    $patchArtifactsDir,
    $recoveryArtifactsDir,
    $certificationArtifactsDir
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
$script:GitSummaryCache = $null
$script:GitSummaryCacheUtc = [datetime]::MinValue
$script:PatchScanCache = $null
$script:PatchScanCacheUtc = [datetime]::MinValue

function Reset-CortexStatusCaches {
    $script:GitSummaryCache = $null
    $script:GitSummaryCacheUtc = [datetime]::MinValue
    $script:PatchScanCache = $null
    $script:PatchScanCacheUtc = [datetime]::MinValue
}

function Get-CargoTargetDirectory {
    if ($script:CargoTargetDirectory) { return $script:CargoTargetDirectory }
    if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { return $null }

    Push-Location $ProjectRoot
    try {
        $raw = & cargo metadata --no-deps --format-version 1 --quiet 2>$null
        if ($LASTEXITCODE -eq 0 -and $raw) {
            $metadata = $raw | ConvertFrom-Json
            if ($metadata.target_directory) {
                $script:CargoTargetDirectory = [IO.Path]::GetFullPath([string]$metadata.target_directory)
                return $script:CargoTargetDirectory
            }
        }
    } catch {
    } finally {
        Pop-Location
        Set-CortexConsoleDefaults
    }
    return (Join-Path $ProjectRoot 'target')
}

function Get-CortexBinaryPath {
    param([ValidateSet('CLI','GUI')][string]$Kind)
    $target = Get-CargoTargetDirectory
    if (-not $target) { return $null }
    $name = if ($Kind -eq 'CLI') { 'cortex.exe' } else { 'cortex_desktop.exe' }
    foreach ($profile in @('debug','release')) {
        $candidate = Join-Path (Join-Path $target $profile) $name
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    return (Join-Path (Join-Path $target 'debug') $name)
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
    $ok = Invoke-CargoStep "Build $Label" @('build','-p',$Package)
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
function Invoke-CargoStep([string]$label,[string[]]$args) {
    Event 'INFO' "START $label"
    Push-Location $ProjectRoot
    try {
        & cargo @args
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
        Set-CortexConsoleDefaults
    }
    if ($code -ne 0) { Event 'FAIL' "$label failed with exit code $code"; return $false }
    Event 'PASS' $label
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

function Show-SourceGitMenu {
    while ($true) {
        Show-Banner
        Write-CortexRule 'SOURCE CONTROL / GIT'

        Write-CortexText ' INSPECT' 'Label'
        Write-CortexText '  1. Detailed Git / branch / remote / GREEN status' 'Default'
        Write-CortexText '  2. Review working changes' 'Default'

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
            '10' {
                $default = "Cortex GREEN checkpoint - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
                $message = Read-Host "Commit message [$default]"
                if ([string]::IsNullOrWhiteSpace($message)) { $message = $default }
                [void](Invoke-CortexGitAction -Action 'CommitGreen' -Message $message)
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '11' {
                $default = "Cortex GREEN checkpoint - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
                $message = Read-Host "Commit message [$default]"
                if ([string]::IsNullOrWhiteSpace($message)) { $message = $default }
                [void](Invoke-CortexGitAction -Action 'CommitPushGreen' -Message $message)
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '12' {
                [void](Invoke-CortexGitAction -Action 'Push')
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '20' {
                [void](Invoke-CortexGitAction -Action 'Pull')
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '21' {
                [void](Invoke-CortexGitAction -Action 'Setup')
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
                    [void](Invoke-CortexGitAction -Action 'ManualCommit' -Message $message)
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
        Write-CortexText '  1. Scan for pending patches' 'Accent'
        Write-CortexText '  2. Apply pending patches now' 'Accent'
        Write-CortexText '  3. Open updates inbox' 'Default'

        Write-CortexText ' HISTORY / RECOVERY' 'Label'
        Write-CortexText ' 10. Open applied patch history' 'Default'
        Write-CortexText ' 11. Open patch recovery backups' 'Default'

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
                [void](Invoke-PendingPatchApply)
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '3' {
                Open-CortexFolder (Join-Path $ProjectRoot 'updates\inbox')
            }
            '10' {
                Open-CortexFolder (Join-Path $ArtifactsRoot 'patches\applied')
            }
            '11' {
                Open-CortexFolder (Join-Path $ArtifactsRoot 'recovery\patch-backups')
            }
            '0' { break }
            default {
                Event 'WARN' "Unknown Updates / Patches option: $choice"
                Start-Sleep -Milliseconds 700
            }
        }

        if ($choice -eq '0') { break }
    }
}

function Show-ValidationCertificationMenu {
    while ($true) {
        Show-Banner
        Write-CortexRule 'TEST / VALIDATE / CERTIFY'

        Write-CortexText ' INDIVIDUAL CHECKS' 'Label'
        Write-CortexText '  1. Quick project gate' 'Info'
        Write-CortexText '  2. cargo fmt --all -- --check' 'Info'
        Write-CortexText '  3. cargo check --workspace --all-targets' 'Info'
        Write-CortexText '  4. cargo test --workspace --all-targets' 'Info'
        Write-CortexText '  5. cargo clippy --workspace --all-targets -D warnings' 'Info'

        Write-CortexText ' COMPOSITE GATES' 'Label'
        Write-CortexText ' 10. Fast development gate' 'Info'
        Write-CortexText ' 11. FULL QUALITY GATE' 'Pass'

        Write-CortexText ' CERTIFICATION EVIDENCE' 'Label'
        Write-CortexText ' 20. Create certification / debug bundle' 'Accent'
        Write-CortexText ' 21. Show current GREEN eligibility' 'Default'

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
                [void](Invoke-CargoStep 'cargo fmt --check' @('fmt','--all','--','--check'))
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '3' {
                [void](Invoke-CargoStep 'cargo check --workspace --all-targets' @('check','--workspace','--all-targets'))
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '4' {
                [void](Invoke-CargoStep 'cargo test --workspace --all-targets' @('test','--workspace','--all-targets'))
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '5' {
                [void](Invoke-CargoStep 'cargo clippy -D warnings' @('clippy','--workspace','--all-targets','--','-D','warnings'))
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

        Write-CortexText ' ARTIFACTS' 'Label'
        Write-CortexText '  1. Open artifacts root' 'Accent'
        Write-CortexText '  2. Open debug bundles' 'Default'
        Write-CortexText '  3. Open current session logs' 'Default'
        Write-CortexText '  4. Open legacy migrated logs' 'Default'

        Write-CortexText ' EVIDENCE' 'Label'
        Write-CortexText ' 10. Create manual debug bundle' 'Accent'
        Write-CortexText ' 11. Open applied patch history' 'Default'

        Write-CortexText ' RECOVERY EVIDENCE' 'Label'
        Write-CortexText ' 20. Open patch recovery backups' 'Default'

        Write-CortexText '  0. Back' 'Default'
        Write-CortexText 'Select an option: ' 'Label' -NoNewline
        $choice = Read-Host

        switch ($choice) {
            '1' { Open-CortexFolder $ArtifactsRoot }
            '2' { Open-CortexFolder $debugDir }
            '3' { Open-CortexFolder $logsDir }
            '4' { Open-CortexFolder (Join-Path $ArtifactLogsRoot 'legacy-sessions') }
            '10' {
                & (Join-Path $PSScriptRoot 'New-CortexDebugBundle.ps1') `
                    -ProjectRoot $ProjectRoot `
                    -Reason 'MANUAL' `
                    -LogPath $ActiveLog `
                    -OpenFolder | Out-Null
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '11' { Open-CortexFolder (Join-Path $ArtifactsRoot 'patches\applied') }
            '20' { Open-CortexFolder (Join-Path $ArtifactsRoot 'recovery\patch-backups') }
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
            -LogPath $ActiveLog `
            -OpenFolder | Out-Null
    } catch {
        Event 'FAIL' "Debug bundle generation failed: $($_.Exception.Message)"
    }

    if ($quickCode -ne 0) {
        Event 'FAIL' 'Startup Quick Gate failed. Repair startup health before running Full Quality.'
    }

    Write-CortexRule
}

function Invoke-FastGate {
    Write-CortexRule 'FAST DEVELOPMENT GATE'
    & (Join-Path $PSScriptRoot 'Test-CortexQuickGate.ps1') -ProjectRoot $ProjectRoot -LogPath $ActiveLog
    if ($LASTEXITCODE -ne 0) { return $false }
    if (-not (Invoke-CargoStep 'cargo check --workspace --all-targets' @('check','--workspace','--all-targets'))) { return $false }
    Event 'PASS' 'Fast development gate GREEN.'
    return $true
}

function Invoke-FullGate {
    Write-CortexRule 'FULL QUALITY GATE'
    & (Join-Path $PSScriptRoot 'Test-CortexQuickGate.ps1') -ProjectRoot $ProjectRoot -LogPath $ActiveLog
    if ($LASTEXITCODE -ne 0) { return $false }
    if (-not (Invoke-CargoStep 'cargo fmt --check' @('fmt','--all','--','--check'))) { return $false }
    if (-not (Invoke-CargoStep 'cargo check' @('check','--workspace','--all-targets'))) { return $false }
    if (-not (Invoke-CargoStep 'cargo test' @('test','--workspace','--all-targets'))) { return $false }
    if (-not (Invoke-CargoStep 'cargo clippy -D warnings' @('clippy','--workspace','--all-targets','--','-D','warnings'))) { return $false }
    if (-not (Invoke-CargoStep 'cargo build' @('build','--workspace'))) { return $false }
    Event 'PASS' 'FULL QUALITY GATE GREEN.'
    Write-CortexGreenMarker
    Reset-CortexStatusCaches
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
                $ok = Invoke-CargoStep 'Build Cortex workspace' @('build','--workspace')
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
                $ok = Invoke-CargoStep 'Build Cortex workspace - release' @('build','--workspace','--release')
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
                        $ok = Invoke-CargoStep 'Rebuild Cortex workspace' @('build','--workspace')
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

function Show-Status {
    Show-Banner
    Write-CortexRule 'NATIVE PROJECT STATUS'
    $target = Get-CargoTargetDirectory
    $cli = Get-CortexBinaryPath CLI
    $gui = Get-CortexBinaryPath GUI
    $git = Get-CortexGitSummary

    Write-CortexStatusRow 'Cargo target' ($(if ($target) {$target} else {'Unavailable'})) 'Value'
    Write-CortexStatusRow 'CLI binary' ($(if ($cli -and (Test-Path -LiteralPath $cli -PathType Leaf)) {$cli} else {'Not built'})) ($(if ($cli -and (Test-Path -LiteralPath $cli -PathType Leaf)) {'Pass'} else {'Warn'}))
    Write-CortexStatusRow 'GUI binary' ($(if ($gui -and (Test-Path -LiteralPath $gui -PathType Leaf)) {$gui} else {'Not built'})) ($(if ($gui -and (Test-Path -LiteralPath $gui -PathType Leaf)) {'Pass'} else {'Warn'}))
    if ($git.gitReady) {
        Write-CortexStatusRow 'Git branch' "$($git.branch) @ $($git.headShort)" 'Value'
        $sync = if ($null -ne $git.ahead -and $null -ne $git.behind) { "$($git.ahead) ahead / $($git.behind) behind" } else { 'Unavailable' }
        Write-CortexStatusRow 'Git sync' $sync ($(if ($git.ahead -eq 0 -and $git.behind -eq 0) {'Pass'} else {'Warn'}))
        Write-CortexStatusRow 'GREEN match' ($(if ($git.greenMatch) {'YES'} else {'NO'})) ($(if ($git.greenMatch) {'Pass'} else {'Warn'}))
    }

    try {
        Push-Location $ProjectRoot
        if (Get-Command cargo -ErrorAction SilentlyContinue) {
            & cargo metadata --no-deps --format-version 1 --quiet | Out-Null
            Event 'PASS' 'Cargo metadata valid.'
        }
    } finally {
        Pop-Location
        Set-CortexConsoleDefaults
    }
}

Move-CortexLegacyRootSessionLogs
Invoke-StartupSequence

try {
    while ($true) {
        Show-Banner
        Write-CortexRule 'CORTEX ROOT CONTROL'

        Write-CortexText ' APPLICATION' 'Label'
        Write-CortexText '  1. Launch Cortex GUI / Project Control' 'Default'

        Write-CortexText ' DEVELOPMENT' 'Label'
        Write-CortexText '  2. Build / Run' 'Accent'
        Write-CortexText '  3. Test / Validate / Certify' 'Pass'

        Write-CortexText ' SOURCE' 'Label'
        Write-CortexText '  4. Source Control / Git' 'Accent'
        Write-CortexText '  5. Updates / Patches' 'Accent'

        Write-CortexText ' OPERATIONS' 'Label'
        Write-CortexText '  6. Diagnostics / Artifacts' 'Accent'
        Write-CortexText '  7. Project Status / Health' 'Default'
        Write-CortexText '  8. Open project folder' 'Default'

        Write-CortexText '  0. Exit' 'Default'
        Write-CortexText 'Select an option: ' 'Label' -NoNewline

        $choice = Read-Host
        switch ($choice) {
            '1' {
                $launched = Start-CortexDesktop
                if (-not $launched) { Read-Host 'Press Enter to continue' | Out-Null }
            }
            '2' { Show-BuildRunMenu }
            '3' { Show-ValidationCertificationMenu }
            '4' { Show-SourceGitMenu }
            '5' { Show-UpdatePatchMenu }
            '6' { Show-ArtifactRecoveryMenu }
            '7' {
                Show-Status
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '8' { Open-CortexFolder $ProjectRoot }
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
