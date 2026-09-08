[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$ControllerVersion = 'CTX-ROOT-06'
$CortexGitRemoteUrl = 'https://github.com/shifty81/Cortex.git'
. (Join-Path $PSScriptRoot 'Cortex.Console.ps1')
Set-CortexConsoleDefaults

$sessionStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$logsDir = Join-Path $ProjectRoot 'logs\sessions'
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
$ActiveLog = Join-Path $logsDir "cortex-root-$sessionStamp.log"
$TranscriptLog = Join-Path $logsDir "cortex-root-$sessionStamp.transcript.log"
$transcriptStarted = $false
try {
    Start-Transcript -LiteralPath $TranscriptLog -Force | Out-Null
    $transcriptStarted = $true
} catch {}

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
            if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot '.git'))) { return 'Not a repository' }
            Push-Location $ProjectRoot
            try { if (@(& git status --porcelain 2>$null).Count -gt 0) { return 'Modified' } else { return 'Clean' } } finally { Pop-Location }
        }
        'Cargo' { if (Get-Command cargo -ErrorAction SilentlyContinue) { return 'Ready' } else { return 'Missing' } }
        'Workspace' { if (Test-Path -LiteralPath (Join-Path $ProjectRoot 'Cargo.toml')) { return 'Ready' } else { return 'Missing' } }
        'CLI' {
            $target = Join-Path $ProjectRoot 'target\debug'
            if (Test-Path $target) {
                $hit = @(Get-ChildItem $target -Filter 'cortex*.exe' -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -notmatch '(?i)(gui|desktop)' } | Select-Object -First 1)
                if ($hit.Count -gt 0) { return 'Ready' }
            }
            return 'Not built yet'
        }
        'GUI' {
            $target = Join-Path $ProjectRoot 'target\debug'
            if (Test-Path $target) {
                $hit = @(Get-ChildItem $target -Filter '*.exe' -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '(?i)cortex.*(gui|desktop)|(gui|desktop).*cortex' } | Select-Object -First 1)
                if ($hit.Count -gt 0) { return 'Ready' }
            }
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

    Event 'PASS' "Git action $Action"
    return $true
}


function Write-CortexGreenMarker {
    $ok = Invoke-CortexGitAction -Action 'MarkGreen'
    if (-not $ok) {
        Event 'WARN' 'Full Quality is GREEN, but the optional Git GREEN-source marker could not be written.'
    }
}

function Show-GitMenu {
    while ($true) {
        Show-Banner
        Write-CortexRule 'GIT / SOURCE CONTROL'
        Write-CortexText '  1. Detailed Git status / branch / remote / GREEN eligibility' 'Default'
        Write-CortexText '  2. Initialize / connect / repair against origin/main' 'Accent'
        Write-CortexText '  3. Review working changes' 'Default'
        Write-CortexText '  4. Commit current source only if it still matches last FULL GREEN' 'Pass'
        Write-CortexText '  5. Commit + push current source only if it still matches FULL GREEN' 'Pass'
        Write-CortexText '  6. Push main to origin' 'Default'
        Write-CortexText '  7. Pull origin/main (fast-forward only)' 'Default'
        Write-CortexText '  8. Open Cortex GitHub repository' 'Default'
        Write-CortexText '  9. Advanced manual commit (not GREEN-gate protected)' 'Warn'
        Write-CortexText '  0. Back' 'Default'
        Write-CortexText 'Select an option: ' 'Label' -NoNewline
        $gitChoice = Read-Host

        switch ($gitChoice) {
            '1' {
                [void](Invoke-CortexGitAction -Action 'Status')
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '2' {
                [void](Invoke-CortexGitAction -Action 'Setup')
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '3' {
                [void](Invoke-CortexGitAction -Action 'Review')
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '4' {
                $default = "Cortex GREEN checkpoint - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
                $message = Read-Host "Commit message [$default]"
                if ([string]::IsNullOrWhiteSpace($message)) { $message = $default }
                [void](Invoke-CortexGitAction -Action 'CommitGreen' -Message $message)
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '5' {
                $default = "Cortex GREEN checkpoint - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
                $message = Read-Host "Commit message [$default]"
                if ([string]::IsNullOrWhiteSpace($message)) { $message = $default }
                [void](Invoke-CortexGitAction -Action 'CommitPushGreen' -Message $message)
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '6' {
                [void](Invoke-CortexGitAction -Action 'Push')
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '7' {
                [void](Invoke-CortexGitAction -Action 'Pull')
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '8' {
                Start-Process $CortexGitRemoteUrl | Out-Null
            }
            '9' {
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
                Event 'WARN' "Unknown Git option: $gitChoice"
                Start-Sleep -Milliseconds 700
            }
        }

        if ($gitChoice -eq '0') { break }
    }
}

function Show-Banner {
    Clear-Host
    Write-CortexRule 'CORTEX ROOT UTILITY / NATIVE PROJECT CONTROL'
    Write-CortexStatusRow 'Controller' $ControllerVersion 'Accent'
    Write-CortexStatusRow 'Repository' $ProjectRoot
    Write-CortexStatusRow 'Git' (Get-StatusValue Git) ($(if ((Get-StatusValue Git) -eq 'Clean') {'Pass'} else {'Warn'}))
    Write-CortexStatusRow 'Cargo' (Get-StatusValue Cargo) ($(if ((Get-StatusValue Cargo) -eq 'Ready') {'Pass'} else {'Fail'}))
    Write-CortexStatusRow 'Workspace' (Get-StatusValue Workspace) ($(if ((Get-StatusValue Workspace) -eq 'Ready') {'Pass'} else {'Fail'}))
    Write-CortexStatusRow 'Cortex CLI' (Get-StatusValue CLI) ($(if ((Get-StatusValue CLI) -eq 'Ready') {'Pass'} else {'Warn'}))
    Write-CortexStatusRow 'Cortex GUI' (Get-StatusValue GUI) ($(if ((Get-StatusValue GUI) -eq 'Ready') {'Pass'} else {'Warn'}))
    Write-CortexStatusRow 'Active log' $ActiveLog 'Value'
}

function Invoke-StartupSequence {
    Write-CortexRule 'STARTUP HANDOFF CHECK'
    $patchSummary = $null
    try {
        $patchOutput = @(& (Join-Path $PSScriptRoot 'InvokeRootPatchIntake.ps1') -ProjectRoot $ProjectRoot -LogPath $ActiveLog)
        $patchSummary = @($patchOutput | Where-Object { $_ -is [psobject] -and $_.PSObject.Properties['Applied'] } | Select-Object -Last 1)
        if ($patchSummary.Count -gt 0) { $patchSummary = $patchSummary[0] } else { $patchSummary = $null }
    } catch {
        Event 'FAIL' "Root patch intake failed: $($_.Exception.Message)"
    }

    if ($patchSummary -and $patchSummary.RestartRequired) {
        Event 'WARN' 'Control-center files were updated; relaunching Cortex root utility so the new scripts become authoritative.'
        try {
            $pwsh = (Get-Process -Id $PID).Path
            Start-Process -FilePath $pwsh -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',"`"$PSCommandPath`"") -WorkingDirectory $ProjectRoot | Out-Null
            if ($transcriptStarted) { try { Stop-Transcript | Out-Null } catch {} }
            exit 0
        } catch {
            Event 'WARN' "Automatic relaunch failed: $($_.Exception.Message). Close and relaunch the root utility once."
        }
    }

    $quickCode = 1
    try {
        & (Join-Path $PSScriptRoot 'Test-CortexQuickGate.ps1') -ProjectRoot $ProjectRoot -LogPath $ActiveLog
        $quickCode = $LASTEXITCODE
    } catch {
        Event 'FAIL' "Startup quick gate crashed: $($_.Exception.Message)"
    }

    try {
        & (Join-Path $PSScriptRoot 'New-CortexDebugBundle.ps1') -ProjectRoot $ProjectRoot -Reason ($(if ($quickCode -eq 0) {'STARTUP_GREEN'} else {'STARTUP_FAIL'})) -LogPath $ActiveLog -OpenFolder | Out-Null
    } catch {
        Event 'FAIL' "Debug bundle generation failed: $($_.Exception.Message)"
    }
    Write-CortexRule
}

function Invoke-FastGate {
    Write-CortexRule 'FAST DEVELOPMENT GATE'
    & (Join-Path $PSScriptRoot 'InvokeRootPatchIntake.ps1') -ProjectRoot $ProjectRoot -LogPath $ActiveLog | Out-Null
    & (Join-Path $PSScriptRoot 'Test-CortexQuickGate.ps1') -ProjectRoot $ProjectRoot -LogPath $ActiveLog
    if ($LASTEXITCODE -ne 0) { return $false }
    if (-not (Invoke-CargoStep 'cargo check --workspace --all-targets' @('check','--workspace','--all-targets'))) { return $false }
    Event 'PASS' 'Fast development gate GREEN.'
    return $true
}

function Invoke-FullGate {
    Write-CortexRule 'FULL QUALITY GATE'
    & (Join-Path $PSScriptRoot 'InvokeRootPatchIntake.ps1') -ProjectRoot $ProjectRoot -LogPath $ActiveLog | Out-Null
    & (Join-Path $PSScriptRoot 'Test-CortexQuickGate.ps1') -ProjectRoot $ProjectRoot -LogPath $ActiveLog
    if ($LASTEXITCODE -ne 0) { return $false }
    if (-not (Invoke-CargoStep 'cargo fmt --check' @('fmt','--all','--','--check'))) { return $false }
    if (-not (Invoke-CargoStep 'cargo check' @('check','--workspace','--all-targets'))) { return $false }
    if (-not (Invoke-CargoStep 'cargo test' @('test','--workspace','--all-targets'))) { return $false }
    if (-not (Invoke-CargoStep 'cargo clippy -D warnings' @('clippy','--workspace','--all-targets','--','-D','warnings'))) { return $false }
    if (-not (Invoke-CargoStep 'cargo build' @('build','--workspace'))) { return $false }
    Event 'PASS' 'FULL QUALITY GATE GREEN.'
    Write-CortexGreenMarker
    return $true
}

function Show-Status {
    Show-Banner
    Write-CortexRule 'NATIVE PROJECT STATUS'
    try {
        Push-Location $ProjectRoot
        if (Get-Command cargo -ErrorAction SilentlyContinue) { & cargo metadata --no-deps --format-version 1 --quiet | Out-Null; Event 'PASS' 'Cargo metadata valid.' }
        if (Test-Path -LiteralPath (Join-Path $ProjectRoot '.git')) { & git status --short }
    } finally { Pop-Location; Set-CortexConsoleDefaults }
}

Invoke-StartupSequence

try {
    while ($true) {
        Show-Banner
        Write-CortexRule 'CORTEX BOOTSTRAP / RECOVERY'
        Write-CortexText '  1. Launch Cortex GUI / Project Control' 'Default'
        Write-CortexText '  2. FULL QUALITY GATE' 'Pass'
        Write-CortexText '  3. Fast development gate' 'Info'
        Write-CortexText '  4. Build Cortex workspace' 'Default'
        Write-CortexText '  5. Native project status' 'Default'
        Write-CortexText '  6. Apply pending root/inbox updates' 'Accent'
        Write-CortexText '  7. Create debug bundle + open handoff folder' 'Accent'
        Write-CortexText '  8. Open project folder' 'Default'
        Write-CortexText '  9. Open logs folder' 'Default'
        Write-CortexText ' 10. Git / Source Control' 'Accent'
        Write-CortexText '  0. Exit' 'Default'
        Write-CortexText 'Select an option: ' 'Label' -NoNewline
        $choice = Read-Host
        switch ($choice) {
            '1' {
                $target = Join-Path $ProjectRoot 'target\debug'
                $gui = @(Get-ChildItem $target -Filter '*.exe' -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '(?i)cortex.*(gui|desktop)|(gui|desktop).*cortex' } | Select-Object -First 1)
                if ($gui.Count -gt 0) { Start-Process -FilePath $gui[0].FullName -WorkingDirectory $ProjectRoot | Out-Null }
                else { Event 'WARN' 'Native Cortex GUI is not built yet.'; Read-Host 'Press Enter to continue' | Out-Null }
            }
            '2' {
                $ok = Invoke-FullGate
                try { & (Join-Path $PSScriptRoot 'New-CortexDebugBundle.ps1') -ProjectRoot $ProjectRoot -Reason ($(if ($ok) {'FULL_GREEN'} else {'FULL_FAIL'})) -LogPath $ActiveLog -OpenFolder | Out-Null } catch {}
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '3' {
                $ok = Invoke-FastGate
                try { & (Join-Path $PSScriptRoot 'New-CortexDebugBundle.ps1') -ProjectRoot $ProjectRoot -Reason ($(if ($ok) {'FAST_GREEN'} else {'FAST_FAIL'})) -LogPath $ActiveLog -OpenFolder | Out-Null } catch {}
                Read-Host 'Press Enter to continue' | Out-Null
            }
            '4' { Invoke-CargoStep 'Build Cortex workspace' @('build','--workspace') | Out-Null; Read-Host 'Press Enter to continue' | Out-Null }
            '5' { Show-Status; Read-Host 'Press Enter to continue' | Out-Null }
            '6' { & (Join-Path $PSScriptRoot 'InvokeRootPatchIntake.ps1') -ProjectRoot $ProjectRoot -LogPath $ActiveLog | Out-Null; Read-Host 'Press Enter to continue' | Out-Null }
            '7' { & (Join-Path $PSScriptRoot 'New-CortexDebugBundle.ps1') -ProjectRoot $ProjectRoot -Reason 'MANUAL' -LogPath $ActiveLog -OpenFolder | Out-Null; Read-Host 'Press Enter to continue' | Out-Null }
            '8' { Start-Process explorer.exe -ArgumentList "`"$ProjectRoot`"" | Out-Null }
            '9' { Start-Process explorer.exe -ArgumentList "`"$logsDir`"" | Out-Null }
            '10' { Show-GitMenu }
            '0' { break }
            default { Event 'WARN' "Unknown option: $choice"; Start-Sleep -Milliseconds 700 }
        }
        if ($choice -eq '0') { break }
    }
} finally {
    if ($transcriptStarted) { try { Stop-Transcript | Out-Null } catch {} }
    Set-CortexConsoleDefaults
}
