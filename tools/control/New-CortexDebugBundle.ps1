[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$Reason = 'MANUAL',
    [string]$FailedStage,
    [int]$ExitCode = 0,
    [string]$LogPath,
    [switch]$OpenFolder
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $ProjectRoot) { $ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')) }
$console = Join-Path $PSScriptRoot 'Cortex.Console.ps1'
if (Test-Path -LiteralPath $console) { . $console }
function Emit([string]$kind,[string]$msg) { Write-CortexEvent $kind $msg $LogPath }

function New-ProjectedArtifactStatus {
    param([Parameter(Mandatory=$true)][string]$BundlePath)

    $artifactRoot = Join-Path $ProjectRoot 'artifacts'
    $sessionRoot = Join-Path $artifactRoot 'logs\sessions'
    $debugRoot = Join-Path $artifactRoot 'debug'

    $sessionFiles = @(
        Get-ChildItem -LiteralPath $sessionRoot -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -ne 'LATEST_ROOT_SESSION.txt' } |
            Sort-Object LastWriteTime -Descending
    )
    $debugFiles = @(
        Get-ChildItem -LiteralPath $debugRoot -Filter 'Cortex_*.zip' -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending
    )

    $bundleAlreadyExists = Test-Path -LiteralPath $BundlePath -PathType Leaf
    return [ordered]@{
        schema = 'cortex.artifact_maintenance.v1'
        createdUtc = (Get-Date).ToUniversalTime().ToString('o')
        projectRoot = $ProjectRoot
        pruneRequested = $false
        removedSessionLogs = 0
        removedDebugBundles = 0
        sessionLogCount = $sessionFiles.Count
        debugBundleCount = $debugFiles.Count + $(if ($bundleAlreadyExists) { 0 } else { 1 })
        latestSessionLog = $(if ($sessionFiles.Count -gt 0) { $sessionFiles[0].FullName } else { $null })
        latestDebugBundle = $BundlePath
    }
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outDir = Join-Path $ProjectRoot 'artifacts\debug'
$stage = Join-Path $ProjectRoot (".project_control\debug-stage\{0}-{1}" -f $stamp,[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $outDir,$stage | Out-Null

$startupEvidencePath = Join-Path $ProjectRoot 'artifacts\status\PENDING_PATCH_STARTUP_EVIDENCE.json'
$patchStartupEvidence = $null
if ($Reason -match '^(STARTUP_(GREEN|FAIL)|PATCH_INTAKE_FAIL|ROOT_BOOTSTRAP_FAIL)$' -and (Test-Path -LiteralPath $startupEvidencePath -PathType Leaf)) {
    try {
        $candidate = Get-Content -LiteralPath $startupEvidencePath -Raw | ConvertFrom-Json
        if ([string]$candidate.schema -eq 'cortex.post_patch_startup_evidence.v1' -and -not [string]::IsNullOrWhiteSpace([string]$candidate.primaryPatchId)) {
            $patchStartupEvidence = $candidate
        }
    } catch {
        Emit 'WARN' "Post-patch startup evidence marker could not be read: $($_.Exception.Message)"
    }
}

$safeReason = ($Reason -replace '[^A-Za-z0-9_-]','_')
if ($patchStartupEvidence) {
    $safePatchId = ([string]$patchStartupEvidence.primaryPatchId -replace '[^A-Za-z0-9._-]','_')
    $batchSuffix = if ([int]$patchStartupEvidence.patchCount -gt 1) { '_BATCH' + [int]$patchStartupEvidence.patchCount } else { '' }
    $zipName = "Cortex_PostPatch_{0}{1}_{2}_{3}.zip" -f $safePatchId,$batchSuffix,$stamp,$safeReason
} else {
    $zipName = "Cortex_DebugBundle_{0}_{1}.zip" -f $stamp,$safeReason
}
$zipPath = Join-Path $outDir $zipName

try {
    $summary = New-Object System.Collections.Generic.List[string]
    $summary.Add('========================================================================')
    $summary.Add(' CORTEX DEBUG / HANDOFF BUNDLE')
    $summary.Add('========================================================================')
    $summary.Add("Created     : $(Get-Date -Format o)")
    $summary.Add("Reason      : $Reason")
    $summary.Add("Failed stage: $FailedStage")
    $summary.Add("Exit code   : $ExitCode")
    if ($patchStartupEvidence) {
        $summary.Add("Patch ID    : $([string]$patchStartupEvidence.primaryPatchId)")
        $summary.Add("Patch title : $([string]$patchStartupEvidence.primaryTitle)")
        $summary.Add("Patch count : $([int]$patchStartupEvidence.patchCount)")
    }
    $summary.Add("Repository  : $ProjectRoot")
    $summary.Add("PowerShell  : $($PSVersionTable.PSVersion)")
    $summary.Add("OS          : $([Environment]::OSVersion.VersionString)")
    try { $summary.Add("Cargo       : $(& cargo --version 2>&1)") } catch { $summary.Add('Cargo       : unavailable') }
    try { $summary.Add("Rustc       : $(& rustc --version 2>&1)") } catch { $summary.Add('Rustc       : unavailable') }
    try {
        if (Test-Path -LiteralPath (Join-Path $ProjectRoot '.git')) {
            Push-Location $ProjectRoot
            $summary.Add("Git branch  : $(& git branch --show-current 2>&1)")
            $summary.Add('Git status  :')
            foreach ($line in @(& git status --short 2>&1)) { $summary.Add("  $line") }
            Pop-Location
        } else { $summary.Add('Git         : Not a repository') }
    } catch { try { Pop-Location } catch {} }
    $summary.Add("Active log  : $LogPath")
    $summary | Set-Content -LiteralPath (Join-Path $stage 'DEBUG_SUMMARY.txt') -Encoding UTF8

    $gitEvidence = New-Object System.Collections.Generic.List[string]
    $gitEvidence.Add('========================================================================')
    $gitEvidence.Add(' CORTEX GIT EVIDENCE')
    $gitEvidence.Add('========================================================================')
    if (Test-Path -LiteralPath (Join-Path $ProjectRoot '.git')) {
        try {
            $gitEvidence.Add("Branch=$(git -C $ProjectRoot branch --show-current 2>&1)")
            $gitEvidence.Add("Head=$(git -C $ProjectRoot rev-parse HEAD 2>&1)")
            $gitEvidence.Add("Origin=$(git -C $ProjectRoot remote get-url origin 2>&1)")
            $gitEvidence.Add("Upstream=$(git -C $ProjectRoot rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>&1)")
            $gitEvidence.Add('Status:')
            foreach ($line in @(git -C $ProjectRoot status --porcelain=v1 -uall 2>&1)) {
                $gitEvidence.Add($line)
            }
            $gitEvidence.Add('Ignored operational examples:')
            foreach ($line in @(git -C $ProjectRoot status --porcelain=v1 --ignored --untracked-files=all 2>&1 |
                Where-Object { $_ -like '!! *' } |
                Select-Object -First 80)) {
                $gitEvidence.Add($line)
            }
        } catch {
            $gitEvidence.Add("Git evidence collection failed: $($_.Exception.Message)")
        }
    } else {
        $gitEvidence.Add('Git=Not a repository')
    }
    $gitEvidence | Set-Content -LiteralPath (Join-Path $stage 'GIT_STATUS.txt') -Encoding UTF8

    $sourceDir = Join-Path $stage 'control-source'
    New-Item -ItemType Directory -Force -Path $sourceDir | Out-Null
    $copyFiles = @(
        'Cargo.toml','Cargo.lock','rust-toolchain','rust-toolchain.toml',
        'project.control.json','cortex.integration.json','.gitignore','.gitattributes'
    )
    foreach ($name in $copyFiles) {
        $src = Join-Path $ProjectRoot $name
        if (Test-Path -LiteralPath $src) { Copy-Item -LiteralPath $src -Destination $sourceDir -Force }
    }
    Get-ChildItem -LiteralPath $ProjectRoot -Filter '*.cmd' -File -ErrorAction SilentlyContinue | Copy-Item -Destination $sourceDir -Force -ErrorAction SilentlyContinue
    Get-ChildItem -LiteralPath $ProjectRoot -Filter '*.ps1' -File -ErrorAction SilentlyContinue | Copy-Item -Destination $sourceDir -Force -ErrorAction SilentlyContinue

    $ctl = Join-Path $ProjectRoot 'tools\control'
    if (Test-Path -LiteralPath $ctl) {
        $dest = Join-Path $sourceDir 'tools-control'
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        Get-ChildItem -LiteralPath $ctl -Filter '*.ps1' -File -ErrorAction SilentlyContinue | Copy-Item -Destination $dest -Force
        Get-ChildItem -LiteralPath $ctl -Filter '*.py' -File -ErrorAction SilentlyContinue | Copy-Item -Destination $dest -Force
    }
    $scripts = Join-Path $ProjectRoot 'scripts'
    if (Test-Path -LiteralPath $scripts) {
        $dest = Join-Path $sourceDir 'scripts'
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        Get-ChildItem -LiteralPath $scripts -Filter '*.ps1' -File -ErrorAction SilentlyContinue | Copy-Item -Destination $dest -Force
    }

    $logsDest = Join-Path $stage 'logs'
    New-Item -ItemType Directory -Force -Path $logsDest | Out-Null
    $logRoots = @(
        (Join-Path $ProjectRoot 'artifacts\logs\sessions'),
        (Join-Path $ProjectRoot 'artifacts\logs\legacy-sessions'),
        (Join-Path $ProjectRoot 'logs\sessions')
    )
    $logFiles = @()
    foreach ($logsRoot in $logRoots) {
        if (Test-Path -LiteralPath $logsRoot -PathType Container) {
            $logFiles += @(Get-ChildItem -LiteralPath $logsRoot -File -ErrorAction SilentlyContinue)
        }
    }
    @($logFiles | Sort-Object LastWriteTime -Descending | Select-Object -First 12) |
        Copy-Item -Destination $logsDest -Force -ErrorAction SilentlyContinue

    $evidenceDest = Join-Path $stage 'latest-evidence'
    New-Item -ItemType Directory -Force -Path $evidenceDest | Out-Null
    $evidenceFiles = @(
        'artifacts\builds\LATEST_BUILD_RECEIPT.json',
        'artifacts\builds\LATEST_CARGO_DIAGNOSTICS.log',
        'artifacts\certification\LATEST_ROOT_SELF_AUDIT.json',
        'artifacts\status\LATEST_ROOT_STATUS.json',
        'artifacts\status\LATEST_PUBLISHED_STATE.json',
        'artifacts\patches\LATEST_PATCH_RECEIPT.json',
        'artifacts\status\LATEST_ARTIFACT_STATUS.json'
    )
    foreach ($relative in $evidenceFiles) {
        $src = Join-Path $ProjectRoot $relative
        if (Test-Path -LiteralPath $src -PathType Leaf) {
            Copy-Item -LiteralPath $src -Destination (Join-Path $evidenceDest ([IO.Path]::GetFileName($src))) -Force
        }
    }

    try {
        $projectedArtifactStatus = New-ProjectedArtifactStatus -BundlePath $zipPath
        ($projectedArtifactStatus | ConvertTo-Json -Depth 6) |
            Set-Content -LiteralPath (Join-Path $evidenceDest 'LATEST_ARTIFACT_STATUS.json') -Encoding UTF8
    } catch {
        Emit 'WARN' "Projected artifact status could not be staged: $($_.Exception.Message)"
    }

    # Capture only the source files explicitly referenced by the latest Cargo
    # diagnostics. This keeps debug bundles bounded while giving repair tooling
    # the exact working-tree preimages that produced the compiler error.
    $cargoDiagnosticsPath = Join-Path $ProjectRoot 'artifacts\builds\LATEST_CARGO_DIAGNOSTICS.log'
    if (Test-Path -LiteralPath $cargoDiagnosticsPath -PathType Leaf) {
        try {
            $diagnosticText = Get-Content -LiteralPath $cargoDiagnosticsPath -Raw
            $diagnosticText = [regex]::Replace(
                $diagnosticText,
                '\x1B\[[0-?]*[ -/]*[@-~]',
                ''
            )
            $sourceMatches = [regex]::Matches(
                $diagnosticText,
                '(?m)^\s*-->\s+(?<path>.+?\.rs):\d+:\d+\s*$'
            )

            $projectRootFull = [IO.Path]::GetFullPath($ProjectRoot)
            $projectRootPrefix = $projectRootFull.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
            $seenDiagnosticSources = @{}
            $diagnosticRows = @()
            $diagnosticSourceDir = Join-Path $stage 'diagnostic-source'
            $diagnosticFileLimit = 12
            $diagnosticPerFileLimit = 1048576
            $diagnosticTotalLimit = 4194304
            $diagnosticTotalBytes = 0

            foreach ($match in $sourceMatches) {
                if ($diagnosticRows.Count -ge $diagnosticFileLimit) { break }

                $candidateText = [string]$match.Groups['path'].Value
                if ([string]::IsNullOrWhiteSpace($candidateText)) { continue }
                $candidateText = $candidateText.Trim().Trim('"')

                $candidatePath = if ([IO.Path]::IsPathRooted($candidateText)) {
                    $candidateText
                } else {
                    Join-Path $ProjectRoot $candidateText
                }

                try {
                    $fullPath = [IO.Path]::GetFullPath($candidatePath)
                } catch {
                    continue
                }

                if (-not $fullPath.StartsWith($projectRootPrefix,[StringComparison]::OrdinalIgnoreCase)) {
                    continue
                }
                if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) { continue }

                $relativePath = [IO.Path]::GetRelativePath($projectRootFull,$fullPath)
                if ($relativePath.StartsWith('..')) { continue }
                $key = $relativePath.ToLowerInvariant()
                if ($seenDiagnosticSources.ContainsKey($key)) { continue }

                $item = Get-Item -LiteralPath $fullPath
                if ($item.Length -gt $diagnosticPerFileLimit) { continue }
                if (($diagnosticTotalBytes + $item.Length) -gt $diagnosticTotalLimit) { break }

                $destination = Join-Path $diagnosticSourceDir $relativePath
                $destinationParent = Split-Path -Parent $destination
                New-Item -ItemType Directory -Force -Path $destinationParent | Out-Null
                Copy-Item -LiteralPath $fullPath -Destination $destination -Force

                $sha = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash.ToLowerInvariant()
                $diagnosticRows += [pscustomobject]@{
                    path = $relativePath.Replace('\','/')
                    bytes = [int64]$item.Length
                    sha256 = $sha
                    evidence = 'LATEST_CARGO_DIAGNOSTICS.log'
                }
                $seenDiagnosticSources[$key] = $true
                $diagnosticTotalBytes += [int64]$item.Length
            }

            if ($diagnosticRows.Count -gt 0) {
                [pscustomobject]@{
                    schema = 'cortex.diagnostic_source_manifest.v1'
                    generatedUtc = (Get-Date).ToUniversalTime().ToString('o')
                    source = 'artifacts/builds/LATEST_CARGO_DIAGNOSTICS.log'
                    fileCount = $diagnosticRows.Count
                    totalBytes = $diagnosticTotalBytes
                    limits = [pscustomobject]@{
                        files = $diagnosticFileLimit
                        bytesPerFile = $diagnosticPerFileLimit
                        totalBytes = $diagnosticTotalLimit
                    }
                    files = $diagnosticRows
                } | ConvertTo-Json -Depth 6 |
                    Set-Content -LiteralPath (Join-Path $diagnosticSourceDir 'DIAGNOSTIC_SOURCE_MANIFEST.json') -Encoding UTF8
                Emit 'PASS' ("Diagnostic source evidence: {0} file(s), {1} byte(s)." -f $diagnosticRows.Count,$diagnosticTotalBytes)
            }
        } catch {
            Emit 'WARN' "Diagnostic source evidence collection failed: $($_.Exception.Message)"
        }
    }

    if ($patchStartupEvidence) {
        $patchStartupEvidence | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $stage 'PATCH_STARTUP_EVIDENCE.json') -Encoding UTF8
    }

    $latest = Join-Path $outDir 'LATEST_DEBUG_BUNDLE.txt'
    $latestLines = @(
        "Created=$(Get-Date -Format o)",
        "Reason=$Reason",
        "FailedStage=$FailedStage",
        "ExitCode=$ExitCode",
        "Bundle=$zipPath",
        "ActiveLog=$LogPath"
    )
    if ($patchStartupEvidence) {
        $latestLines += "PatchId=$([string]$patchStartupEvidence.primaryPatchId)"
        $latestLines += "PatchTitle=$([string]$patchStartupEvidence.primaryTitle)"
        $latestLines += "PatchCount=$([int]$patchStartupEvidence.patchCount)"
    }
    $latestLines | Set-Content -LiteralPath $latest -Encoding UTF8

    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zipPath -CompressionLevel Optimal

    try {
        $maintenanceScript = Join-Path $PSScriptRoot 'Invoke-CortexArtifactMaintenance.ps1'
        if (Test-Path -LiteralPath $maintenanceScript -PathType Leaf) {
            & $maintenanceScript -ProjectRoot $ProjectRoot -LogPath $LogPath | Out-Null
        }
    } catch {
        Emit 'WARN' "Post-bundle artifact status refresh failed: $($_.Exception.Message)"
    }

    if ($patchStartupEvidence -and (Test-Path -LiteralPath $startupEvidencePath -PathType Leaf)) {
        Remove-Item -LiteralPath $startupEvidencePath -Force -ErrorAction SilentlyContinue
    }
    Emit 'PASS' "Debug handoff bundle: $zipPath"
    Write-CortexText " HANDOFF ZIP : $zipPath" 'Accent'

    if ($OpenFolder) {
        try { Start-Process explorer.exe -ArgumentList "`"$outDir`"" | Out-Null } catch { Emit 'WARN' "Could not open debug folder: $($_.Exception.Message)" }
    }
    Write-Output $zipPath
} finally {
    Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
}
