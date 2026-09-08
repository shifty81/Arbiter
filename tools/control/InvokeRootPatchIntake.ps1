[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$LogPath,
    [switch]$Apply,
    [switch]$ScanOnly
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $ProjectRoot) {
    $ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
}
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$console = Join-Path $PSScriptRoot 'Cortex.Console.ps1'
if (Test-Path -LiteralPath $console) { . $console }

function Emit([string]$kind, [string]$message) {
    if (Get-Command Write-CortexEvent -ErrorAction SilentlyContinue) {
        Write-CortexEvent $kind $message $LogPath
    } else {
        Write-Host "[$kind] $message"
    }
}

function Test-PatchName([string]$name) {
    if ($name -match '(?i)(debugbundle|debug[-_ ]?bundle|handoff|source[-_ ]?(rollup|bundle)|rollup|backup|support[-_ ]?bundle|archive)') {
        return $false
    }
    return ($name -match '(?i)(root[-_ ]?patch|rootpatch|incremental[-_ ]?patch|patch[-_ ]?update)')
}

function Get-ZipManifestFlag([string]$zipPath) {
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
        $zip = [IO.Compression.ZipFile]::OpenRead($zipPath)
        try {
            foreach ($entry in $zip.Entries) {
                $n = $entry.FullName.Replace('\','/').TrimStart('/')
                if ($n -match '^(?i)(PATCH_MANIFEST\.json|\.cortex-patch\.json)$') { return $true }
            }
        } finally { $zip.Dispose() }
    } catch {}
    return $false
}

function Assert-SafeZip([string]$zipPath, [string]$stageRoot) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
    $stageFull = [IO.Path]::GetFullPath($stageRoot).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    $zip = [IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        foreach ($entry in $zip.Entries) {
            $raw = $entry.FullName.Replace('\','/')
            if ([string]::IsNullOrWhiteSpace($raw)) { continue }
            if ($raw.StartsWith('/') -or $raw -match '^[A-Za-z]:') { throw "Unsafe rooted ZIP entry: $raw" }
            $target = [IO.Path]::GetFullPath((Join-Path $stageRoot $raw))
            if (-not $target.StartsWith($stageFull, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Unsafe ZIP traversal entry: $raw"
            }
        }
    } finally { $zip.Dispose() }
}


function Assert-StagedPowerShellSyntax {
    param([Parameter(Mandatory=$true)][string]$StageRoot)

    $scriptFiles = @(
        Get-ChildItem -LiteralPath $StageRoot -Recurse -File -ErrorAction Stop |
            Where-Object { $_.Extension -in @('.ps1', '.psm1') }
    )

    foreach ($scriptFile in $scriptFiles) {
        $tokens = $null
        $parseErrors = $null
        [System.Management.Automation.Language.Parser]::ParseFile(
            $scriptFile.FullName,
            [ref]$tokens,
            [ref]$parseErrors
        ) | Out-Null

        if (@($parseErrors).Count -gt 0) {
            $first = $parseErrors[0]
            throw ("PowerShell parse validation failed before apply: {0}: {1}" -f
                $scriptFile.FullName.Substring($StageRoot.Length).TrimStart([char]'\',[char]'/'),
                $first.Message)
        }
    }
}

function Apply-Patch([string]$zipPath) {
    $name = [IO.Path]::GetFileName($zipPath)
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $controlRoot = Join-Path $ProjectRoot '.project_control'
    $stage = Join-Path $controlRoot ("patch-stage\{0}-{1}" -f $stamp, [guid]::NewGuid().ToString('N'))
    $backup = Join-Path $controlRoot ("patch-backups\{0}-{1}" -f $stamp, ([IO.Path]::GetFileNameWithoutExtension($name)))
    $appliedDir = Join-Path $ProjectRoot 'artifacts\patches\applied'
    New-Item -ItemType Directory -Force -Path $stage,$backup,$appliedDir | Out-Null

    Assert-SafeZip $zipPath $stage
    Expand-Archive -LiteralPath $zipPath -DestinationPath $stage -Force

    # Reject malformed PowerShell before any live project file is backed up or overwritten.
    Assert-StagedPowerShellSyntax -StageRoot $stage

    $newFiles = New-Object System.Collections.Generic.List[string]
    $touched = New-Object System.Collections.Generic.List[string]
    $restartRequired = $false
    Get-ChildItem -LiteralPath $stage -Recurse -File | ForEach-Object {
        $relative = $_.FullName.Substring($stage.Length).TrimStart([char]'\',[char]'/')
        if ($relative -match '^(?i)(PATCH_MANIFEST\.json|\.cortex-patch\.json)$') { return }
        $touched.Add($relative) | Out-Null
        if ($relative -match '^(?i)(tools[\\/]+control[\\/]+(ProjectControlCenter|InvokeRootPatchIntake|Cortex\.Console|Test-CortexQuickGate|New-CortexDebugBundle)\.ps1|[^\\/]+\.(cmd|ps1))$') { $restartRequired = $true }
        $dest = Join-Path $ProjectRoot $relative
        if (Test-Path -LiteralPath $dest) {
            $bak = Join-Path $backup $relative
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $bak) | Out-Null
            Copy-Item -LiteralPath $dest -Destination $bak -Force
        } else {
            $newFiles.Add($dest) | Out-Null
        }
    }

    $rc = 0
    try {
        $robo = Get-Command robocopy.exe -ErrorAction SilentlyContinue
        if ($robo) {
            & $robo.Source $stage $ProjectRoot /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Host
            $rc = $LASTEXITCODE
            if ($rc -ge 8) { throw "Robocopy patch apply failed with exit code $rc" }
        } else {
            Get-ChildItem -LiteralPath $stage -Force | ForEach-Object {
                if ($_.Name -in @('PATCH_MANIFEST.json','.cortex-patch.json')) { return }
                Copy-Item -LiteralPath $_.FullName -Destination $ProjectRoot -Recurse -Force
            }
        }
    } catch {
        Emit 'FAIL' "Patch apply failed; restoring backup: $name"
        if (Test-Path -LiteralPath $backup) {
            $robo = Get-Command robocopy.exe -ErrorAction SilentlyContinue
            if ($robo) {
                & $robo.Source $backup $ProjectRoot /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
            } else {
                Get-ChildItem -LiteralPath $backup -Force | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $ProjectRoot -Recurse -Force }
            }
        }
        foreach ($p in $newFiles) { if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue } }
        throw
    } finally {
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    }

    $archiveName = "{0}_{1}" -f $stamp,$name
    $archivePath = Join-Path $appliedDir $archiveName
    Move-Item -LiteralPath $zipPath -Destination $archivePath -Force
    Emit 'PASS' "APPLIED: $name"
    return [pscustomobject]@{ ArchivePath = $archivePath; RestartRequired = $restartRequired; Touched = @($touched) }
}

Emit 'INFO' 'START Root incremental patch intake'
$roots = @($ProjectRoot)
$inbox = Join-Path $ProjectRoot 'updates\inbox'
if (Test-Path -LiteralPath $inbox) { $roots += $inbox }

$candidates = @()
foreach ($r in $roots) {
    $candidates += @(Get-ChildItem -LiteralPath $r -Filter '*.zip' -File -ErrorAction SilentlyContinue)
}
$candidates = @($candidates | Sort-Object FullName -Unique)
$patches = @()
foreach ($f in $candidates) {
    $explicit = Test-PatchName $f.Name
    $manifest = $false
    if (-not $explicit) { $manifest = Get-ZipManifestFlag $f.FullName }
    if ($explicit -or $manifest) {
        $patches += $f
    } else {
        Emit 'DEBUG' "IGNORED non-patch ZIP: $($f.Name)"
    }
}

if (@($patches).Count -eq 0) {
    Emit 'PASS' 'Root patch intake: no pending patch ZIPs detected.'
    return [pscustomobject]@{ Applied = 0; Ignored = @($candidates).Count; Archives = @(); RestartRequired = $false }
}

$results = @()
foreach ($patch in $patches) {
    Emit 'INFO' "PATCH DETECTED: $($patch.Name)"
    if ($ScanOnly) {
        Emit 'INFO' "SCAN ONLY: would apply $($patch.Name)"
        continue
    }
    $results += @(Apply-Patch $patch.FullName)
}
$archives = @($results | ForEach-Object { $_.ArchivePath })
$restartRequired = @($results | Where-Object { $_.RestartRequired }).Count -gt 0
Emit 'PASS' ("Root patch intake complete: {0} applied." -f @($archives).Count)
return [pscustomobject]@{ Applied = @($archives).Count; Ignored = (@($candidates).Count - @($patches).Count); Archives = $archives; RestartRequired = $restartRequired }
