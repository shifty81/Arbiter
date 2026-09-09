[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$LogPath,
    [switch]$Apply,
    [switch]$ScanOnly,
    [switch]$ValidateOnly,
    [switch]$Quiet
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# CTX-ROOT-09K-R1: PowerShell generic-list binder recovery; native arrays are authoritative.

if (-not $ProjectRoot) {
    $ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
}
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$console = Join-Path $PSScriptRoot 'Cortex.Console.ps1'
if (Test-Path -LiteralPath $console) { . $console }

$ArtifactsRoot = Join-Path $ProjectRoot 'artifacts'
$PatchRoot = Join-Path $ArtifactsRoot 'patches'
$AppliedDir = Join-Path $PatchRoot 'applied'
$FailedDir = Join-Path $PatchRoot 'failed'
$ReceiptDir = Join-Path $PatchRoot 'receipts'
$BackupRoot = Join-Path $ArtifactsRoot 'recovery\patch-backups'
$StageRoot = Join-Path $ProjectRoot '.project_control\patch-stage'
$StartupEvidencePath = Join-Path $ArtifactsRoot 'status\PENDING_PATCH_STARTUP_EVIDENCE.json'
New-Item -ItemType Directory -Force -Path @(
    $PatchRoot,$AppliedDir,$FailedDir,$ReceiptDir,$BackupRoot,$StageRoot,(Split-Path -Parent $StartupEvidencePath)
) | Out-Null

function Emit([string]$kind, [string]$message) {
    if ($Quiet -and $kind -in @('INFO','PASS','DEBUG','SKIP')) { return }
    if (Get-Command Write-CortexEvent -ErrorAction SilentlyContinue) {
        Write-CortexEvent $kind $message $LogPath
    } else {
        Write-Host "[$kind] $message"
    }
}

function ConvertTo-SafeRelativePath {
    param([Parameter(Mandatory=$true)][string]$Path)

    $raw = $Path.Replace('\','/').Trim()
    if ([string]::IsNullOrWhiteSpace($raw)) { throw 'Patch path is empty.' }
    if ($raw.StartsWith('/') -or $raw -match '^[A-Za-z]:') {
        throw "Patch path must be repository-relative: $Path"
    }

    $parts = @($raw.Split('/') | Where-Object { $_ -ne '' -and $_ -ne '.' })
    if ($parts.Count -eq 0) { throw "Patch path resolves to root: $Path" }
    if ($parts -contains '..') { throw "Patch path escapes repository root: $Path" }

    $normalized = ($parts -join '/')
    $candidate = [IO.Path]::GetFullPath((Join-Path $ProjectRoot ($normalized.Replace('/','\'))))
    $rootPrefix = $ProjectRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($rootPrefix,[StringComparison]::OrdinalIgnoreCase)) {
        throw "Patch path escapes repository root: $Path"
    }

    $cursor = $ProjectRoot
    foreach ($part in $parts) {
        $cursor = Join-Path $cursor $part
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Patch path traverses a reparse point: $normalized"
            }
        }
    }

    return $normalized
}

function Get-PatchSidecarPath {
    param([Parameter(Mandatory=$true)][string]$ZipPath)
    foreach ($candidate in @("$ZipPath.sha256","$ZipPath.sha256.txt")) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    return $null
}

function Assert-PatchSidecarHash {
    param([Parameter(Mandatory=$true)][string]$ZipPath)

    $sidecar = Get-PatchSidecarPath -ZipPath $ZipPath
    if (-not $sidecar) { return $null }

    $text = (Get-Content -LiteralPath $sidecar -Raw).Trim()
    if ($text -notmatch '(?i)^([a-f0-9]{64})(?:\s+\*?.+)?$') {
        throw "Malformed SHA-256 sidecar: $(Split-Path -Leaf $sidecar)"
    }

    $expected = $Matches[1].ToLowerInvariant()
    $actual = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        throw "ZIP SHA-256 mismatch for $(Split-Path -Leaf $ZipPath)."
    }
    return $actual
}

function Test-PatchName([string]$Name) {
    if ($Name -match '(?i)(debugbundle|debug[-_ ]?bundle|source[-_ ]?(rollup|bundle)|rollup|backup|support[-_ ]?bundle|archive)') {
        return $false
    }
    return ($Name -match '(?i)(root[-_ ]?patch|rootpatch|incremental[-_ ]?patch|patch[-_ ]?update|handoff)')
}

function Get-ZipFileEntries {
    param([Parameter(Mandatory=$true)][string]$ZipPath)

    Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
    $zip = [IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        $rows = @()
        foreach ($entry in $zip.Entries) {
            $raw = $entry.FullName.Replace('\','/')
            if ([string]::IsNullOrWhiteSpace($raw) -or $raw.EndsWith('/')) { continue }
            if ($raw.StartsWith('/') -or $raw -match '^[A-Za-z]:') {
                throw "Unsafe rooted ZIP entry: $raw"
            }
            $parts = @($raw.Split('/') | Where-Object { $_ -ne '' -and $_ -ne '.' })
            if ($parts -contains '..') { throw "Unsafe ZIP traversal entry: $raw" }
            $rows += ($parts -join '/')
        }
        return $rows
    } finally {
        $zip.Dispose()
    }
}

function Test-RootPatchTransport {
    param([Parameter(Mandatory=$true)][string]$ZipPath)
    try {
        $entries = @(Get-ZipFileEntries -ZipPath $ZipPath)
        $manifestEntries = @($entries | Where-Object { $_ -eq 'PATCH_MANIFEST.json' })
        return ($manifestEntries.Count -eq 1)
    } catch {
        return $false
    }
}

function Read-PatchManifest {
    param([Parameter(Mandatory=$true)][string]$ZipPath)

    Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
    $zip = [IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        $manifestEntry = @($zip.Entries | Where-Object {
            $_.FullName.Replace('\','/').TrimStart('/') -ieq 'PATCH_MANIFEST.json'
        })
        if ($manifestEntry.Count -ne 1) {
            throw 'Patch ZIP must contain exactly one root PATCH_MANIFEST.json.'
        }

        $reader = [IO.StreamReader]::new($manifestEntry[0].Open())
        try { $text = $reader.ReadToEnd() } finally { $reader.Dispose() }
        try { $manifest = $text | ConvertFrom-Json } catch { throw "PATCH_MANIFEST.json is invalid JSON: $($_.Exception.Message)" }

        if ([string]$manifest.schema -ne 'cortex.root_patch.v1') {
            throw "Unsupported patch manifest schema: $($manifest.schema)"
        }
        if ([string]$manifest.project -ne 'Cortex') {
            throw "Patch manifest project must be Cortex, got: $($manifest.project)"
        }

        $patchId = [string]$manifest.patchId
        if ([string]::IsNullOrWhiteSpace($patchId) -or $patchId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$') {
            throw "Invalid patchId: $patchId"
        }

        $fileRows = @($manifest.files)
        $removeRows = @($manifest.remove)
        if ($fileRows.Count -eq 0 -and $removeRows.Count -eq 0) {
            throw 'Patch manifest must contain at least one file or removal.'
        }

        $files = @()
        $seen = @{}
        foreach ($row in $fileRows) {
            $path = ConvertTo-SafeRelativePath ([string]$row.path)
            $key = $path.ToLowerInvariant()
            if ($seen.ContainsKey($key)) { throw "Duplicate manifest path: $path" }
            $seen[$key] = 'file'

            $sha = ([string]$row.sha256).ToLowerInvariant()
            if ($sha -notmatch '^[a-f0-9]{64}$') { throw "Invalid SHA-256 for manifest file: $path" }
            try { $bytes = [int64]$row.bytes } catch { throw "Invalid byte count for manifest file: $path" }
            if ($bytes -lt 0) { throw "Invalid negative byte count for manifest file: $path" }

            $beforeSha = $null
            if ($row.PSObject.Properties['beforeSha256'] -and $null -ne $row.beforeSha256) {
                $beforeSha = ([string]$row.beforeSha256).ToLowerInvariant()
                if ($beforeSha -notmatch '^[a-f0-9]{64}$') { throw "Invalid beforeSha256 for: $path" }
            }

            $files += [pscustomobject]@{
                Path = $path
                Sha256 = $sha
                Bytes = $bytes
                BeforeSha256 = $beforeSha
            }
        }

        $removes = @()
        foreach ($row in $removeRows) {
            $candidate = if ($row -is [string]) { [string]$row } elseif ($row.PSObject.Properties['path']) { [string]$row.path } else { throw 'Removal entry must be a path string or object with path.' }
            $path = ConvertTo-SafeRelativePath $candidate
            $key = $path.ToLowerInvariant()
            if ($seen.ContainsKey($key)) { throw "Manifest file/removal conflict: $path" }
            $seen[$key] = 'remove'
            $removes += $path
        }

        $zipEntries = @(Get-ZipFileEntries -ZipPath $ZipPath)
        $zipSeen = @{}
        foreach ($entry in $zipEntries) {
            $key = $entry.ToLowerInvariant()
            if ($zipSeen.ContainsKey($key)) { throw "Duplicate ZIP payload path: $entry" }
            $zipSeen[$key] = $true
        }

        $expected = @{}
        $expected['patch_manifest.json'] = $true
        foreach ($f in $files) { $expected[$f.Path.ToLowerInvariant()] = $true }

        foreach ($entry in $zipEntries) {
            if (-not $expected.ContainsKey($entry.ToLowerInvariant())) {
                throw "ZIP contains undeclared payload file: $entry"
            }
        }
        foreach ($key in $expected.Keys) {
            if (-not $zipSeen.ContainsKey($key)) {
                throw "Manifest declares a payload file missing from ZIP: $key"
            }
        }

        $depends = @()
        if ($manifest.PSObject.Properties['dependsOn'] -and $null -ne $manifest.dependsOn) {
            $depends = @($manifest.dependsOn | ForEach-Object { [string]$_ } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        }

        return [pscustomobject]@{
            ZipPath = $ZipPath
            Name = [IO.Path]::GetFileName($ZipPath)
            PatchId = $patchId
            Title = [string]$manifest.title
            Series = $(if ($manifest.PSObject.Properties['series']) { [string]$manifest.series } else { '' })
            Sequence = $(if ($manifest.PSObject.Properties['sequence']) { [string]$manifest.sequence } else { '' })
            DependsOn = $depends
            Files = $files
            Removes = $removes
            Manifest = $manifest
        }
    } finally {
        $zip.Dispose()
    }
}

function Assert-StagedPayload {
    param(
        [Parameter(Mandatory=$true)][string]$Stage,
        [Parameter(Mandatory=$true)]$Descriptor
    )

    foreach ($file in $Descriptor.Files) {
        $path = Join-Path $Stage ($file.Path.Replace('/','\'))
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Staged payload missing: $($file.Path)"
        }
        $info = Get-Item -LiteralPath $path
        if ([int64]$info.Length -ne [int64]$file.Bytes) {
            throw "Staged payload byte mismatch: $($file.Path)"
        }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $file.Sha256) {
            throw "Staged payload SHA-256 mismatch: $($file.Path)"
        }
    }

    $scriptFiles = @(
        Get-ChildItem -LiteralPath $Stage -Recurse -File -ErrorAction Stop |
            Where-Object { $_.Extension -in @('.ps1','.psm1') }
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
            throw "PowerShell parse validation failed before apply: $($scriptFile.Name): $($parseErrors[0].Message)"
        }
    }
}

function Get-NormalizedTextSha256 {
    param([Parameter(Mandatory=$true)][string]$Path)

    $extension = [IO.Path]::GetExtension($Path).ToLowerInvariant()
    $textExtensions = @(
        '.cmd','.bat','.ps1','.psm1','.rs','.toml','.json','.md','.txt',
        '.py','.yml','.yaml','.xml','.html','.css','.js','.ts','.tsx','.jsx',
        '.c','.cc','.cpp','.cxx','.h','.hh','.hpp','.hxx','.cs','.java',
        '.kt','.kts','.go','.sh','.ini','.cfg','.conf'
    )
    if ($extension -notin $textExtensions) { return $null }

    try {
        $bytes = [IO.File]::ReadAllBytes($Path)
        $strictUtf8 = [Text.UTF8Encoding]::new($false, $true)
        $text = $strictUtf8.GetString($bytes)
        if ($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF) {
            $text = $text.Substring(1)
        }
        $text = $text.Replace("`r`n","`n").Replace("`r","`n")
        $normalizedBytes = [Text.UTF8Encoding]::new($false).GetBytes($text)
        $hasher = [Security.Cryptography.SHA256]::Create()
        try {
            return ([BitConverter]::ToString($hasher.ComputeHash($normalizedBytes))).Replace('-','').ToLowerInvariant()
        } finally {
            $hasher.Dispose()
        }
    } catch {
        return $null
    }
}

function Assert-Preconditions {
    param([Parameter(Mandatory=$true)]$Descriptor)
    foreach ($file in $Descriptor.Files) {
        if (-not $file.BeforeSha256) { continue }
        $dest = Join-Path $ProjectRoot ($file.Path.Replace('/','\'))
        if (-not (Test-Path -LiteralPath $dest -PathType Leaf)) {
            throw "Precondition failed; expected existing file: $($file.Path)"
        }

        $actual = (Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -eq $file.BeforeSha256) { continue }

        # Git and ZIP transports commonly normalize UTF-8 text to LF while a
        # Windows working tree can materialize equivalent CRLF/BOM bytes.
        # Accept only an exact normalized-text hash match; any content change
        # still fails closed.
        $normalized = Get-NormalizedTextSha256 -Path $dest
        if ($normalized -and $normalized -eq $file.BeforeSha256) {
            Emit 'INFO' ("Precondition text-normalization match: {0} (raw={1})" -f $file.Path,$actual)
            continue
        }

        $normalizedDetail = if ($normalized) { $normalized } else { '<not-text-or-invalid-utf8>' }
        throw ("Precondition SHA-256 mismatch for: {0}; expected={1}; actual={2}; normalized={3}" -f `
            $file.Path,$file.BeforeSha256,$actual,$normalizedDetail)
    }
}

function Write-PatchReceipt {
    param(
        [Parameter(Mandatory=$true)][hashtable]$Receipt,
        [Parameter(Mandatory=$true)][string]$Stamp
    )
    $patchId = [string]$Receipt.patchId
    $safeId = ($patchId -replace '[^A-Za-z0-9._-]','_')
    $path = Join-Path $ReceiptDir ("{0}_{1}.json" -f $Stamp,$safeId)
    $json = $Receipt | ConvertTo-Json -Depth 12
    $json | Set-Content -LiteralPath $path -Encoding UTF8
    $json | Set-Content -LiteralPath (Join-Path $PatchRoot 'LATEST_PATCH_RECEIPT.json') -Encoding UTF8
    return $path
}

function Move-PatchTransport {
    param(
        [Parameter(Mandatory=$true)][string]$ZipPath,
        [Parameter(Mandatory=$true)][ValidateSet('applied','failed')][string]$Disposition,
        [Parameter(Mandatory=$true)][string]$Stamp
    )
    $destRoot = if ($Disposition -eq 'applied') { $AppliedDir } else { $FailedDir }
    $name = [IO.Path]::GetFileName($ZipPath)
    $archive = Join-Path $destRoot ("{0}_{1}" -f $Stamp,$name)
    $sidecar = Get-PatchSidecarPath -ZipPath $ZipPath
    Move-Item -LiteralPath $ZipPath -Destination $archive -Force
    if ($sidecar -and (Test-Path -LiteralPath $sidecar -PathType Leaf)) {
        Move-Item -LiteralPath $sidecar -Destination "$archive.sha256" -Force
    }
    return $archive
}

function Restore-PatchBackup {
    param(
        [Parameter(Mandatory=$true)][string]$Backup,
        [Parameter(Mandatory=$true)][AllowEmptyCollection()][string[]]$OriginallyExisting,
        [Parameter(Mandatory=$true)][AllowEmptyCollection()][string[]]$OriginallyMissing
    )

    foreach ($relative in $OriginallyMissing) {
        $dest = Join-Path $ProjectRoot ($relative.Replace('/','\'))
        if (Test-Path -LiteralPath $dest) {
            Remove-Item -LiteralPath $dest -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    foreach ($relative in $OriginallyExisting) {
        $source = Join-Path $Backup ($relative.Replace('/','\'))
        $dest = Join-Path $ProjectRoot ($relative.Replace('/','\'))
        if (Test-Path -LiteralPath $source) {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
            Copy-Item -LiteralPath $source -Destination $dest -Recurse -Force
        }
    }
}

function Test-RestartRequired {
    param([string[]]$Touched)
    foreach ($relative in $Touched) {
        $n = $relative.Replace('\','/')
        if ($n -match '^(?i)tools/control/' -or $n -match '^(?i)[^/]+\.(cmd|ps1)$') {
            return $true
        }
    }
    return $false
}

function Test-AppliedPatchId {
    param([Parameter(Mandatory=$true)][string]$PatchId)
    foreach ($receipt in @(Get-ChildItem -LiteralPath $ReceiptDir -Filter '*.json' -File -ErrorAction SilentlyContinue)) {
        try {
            $data = Get-Content -LiteralPath $receipt.FullName -Raw | ConvertFrom-Json
            if ([string]$data.patchId -eq $PatchId -and [string]$data.status -eq 'APPLIED') { return $true }
        } catch {}
    }
    return $false
}

function Assert-QueueDependencies {
    param([Parameter(Mandatory=$true)][object[]]$Descriptors)

    $seenIds = @{}
    foreach ($d in $Descriptors) {
        $key = $d.PatchId.ToLowerInvariant()
        if ($seenIds.ContainsKey($key)) { throw "Duplicate pending patchId: $($d.PatchId)" }
        $seenIds[$key] = $true
    }

    $available = @{}
    foreach ($receipt in @(Get-ChildItem -LiteralPath $ReceiptDir -Filter '*.json' -File -ErrorAction SilentlyContinue)) {
        try {
            $data = Get-Content -LiteralPath $receipt.FullName -Raw | ConvertFrom-Json
            if ([string]$data.status -eq 'APPLIED' -and $data.patchId) {
                $receiptId = ([string]$data.patchId).ToLowerInvariant()
                $available[$receiptId] = $true
            }
        } catch {}
    }

    foreach ($d in $Descriptors) {
        foreach ($dependency in @($d.DependsOn)) {
            $depKey = ([string]$dependency).ToLowerInvariant()
            if (-not $available.ContainsKey($depKey)) {
                throw "Patch $($d.PatchId) depends on unapplied patch: $dependency"
            }
        }
        $available[$d.PatchId.ToLowerInvariant()] = $true
    }
}

function Validate-PatchPayload {
    param([Parameter(Mandatory=$true)]$Descriptor)

    [void](Assert-PatchSidecarHash -ZipPath $Descriptor.ZipPath)
    $stage = Join-Path $StageRoot ("validate-{0}-{1}" -f $Descriptor.PatchId,[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    try {
        Expand-Archive -LiteralPath $Descriptor.ZipPath -DestinationPath $stage -Force
        Assert-StagedPayload -Stage $stage -Descriptor $Descriptor
        Assert-Preconditions -Descriptor $Descriptor
    } finally {
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Apply-Patch {
    param([Parameter(Mandatory=$true)]$Descriptor)

    $zipPath = $Descriptor.ZipPath
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $stage = Join-Path $StageRoot ("{0}-{1}" -f $Descriptor.PatchId,[guid]::NewGuid().ToString('N'))
    $backup = Join-Path $BackupRoot ("{0}-{1}" -f $stamp,$Descriptor.PatchId)
    New-Item -ItemType Directory -Force -Path $stage,$backup | Out-Null

    $zipHash = $null
    $archive = $null
    $receiptPath = $null
    $existing = @()
    $missing = @()
    $touched = @()
    $rollbackAttempted = $false
    $rollbackSucceeded = $false

    try {
        $zipHash = Assert-PatchSidecarHash -ZipPath $zipPath
        if (-not $zipHash) {
            $zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
        }

        Expand-Archive -LiteralPath $zipPath -DestinationPath $stage -Force
        Assert-StagedPayload -Stage $stage -Descriptor $Descriptor
        Assert-Preconditions -Descriptor $Descriptor

        $allPaths = @()
        foreach ($file in $Descriptor.Files) { $allPaths += $file.Path }
        foreach ($remove in $Descriptor.Removes) { $allPaths += $remove }

        foreach ($relative in $allPaths) {
            $dest = Join-Path $ProjectRoot ($relative.Replace('/','\'))
            $touched += $relative
            if (Test-Path -LiteralPath $dest) {
                $existing += $relative
                $bak = Join-Path $backup ($relative.Replace('/','\'))
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $bak) | Out-Null
                Copy-Item -LiteralPath $dest -Destination $bak -Recurse -Force
            } else {
                $missing += $relative
            }
        }

        foreach ($file in $Descriptor.Files) {
            $source = Join-Path $stage ($file.Path.Replace('/','\'))
            $dest = Join-Path $ProjectRoot ($file.Path.Replace('/','\'))
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
            Copy-Item -LiteralPath $source -Destination $dest -Force
        }

        foreach ($remove in $Descriptor.Removes) {
            $dest = Join-Path $ProjectRoot ($remove.Replace('/','\'))
            if (Test-Path -LiteralPath $dest) {
                Remove-Item -LiteralPath $dest -Recurse -Force
            }
        }

        foreach ($file in $Descriptor.Files) {
            $dest = Join-Path $ProjectRoot ($file.Path.Replace('/','\'))
            if (-not (Test-Path -LiteralPath $dest -PathType Leaf)) {
                throw "Post-apply verification missing file: $($file.Path)"
            }
            $info = Get-Item -LiteralPath $dest
            if ([int64]$info.Length -ne [int64]$file.Bytes) {
                throw "Post-apply byte mismatch: $($file.Path)"
            }
            $actual = (Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actual -ne $file.Sha256) {
                throw "Post-apply SHA-256 mismatch: $($file.Path)"
            }
        }
        foreach ($remove in $Descriptor.Removes) {
            $dest = Join-Path $ProjectRoot ($remove.Replace('/','\'))
            if (Test-Path -LiteralPath $dest) {
                throw "Post-apply removal verification failed: $remove"
            }
        }

        $archive = Move-PatchTransport -ZipPath $zipPath -Disposition applied -Stamp $stamp
        $receipt = @{
            schema = 'cortex.patch_receipt.v1'
            status = 'APPLIED'
            patchId = $Descriptor.PatchId
            title = $Descriptor.Title
            series = $Descriptor.Series
            sequence = $Descriptor.Sequence
            appliedUtc = (Get-Date).ToUniversalTime().ToString('o')
            sourceZipSha256 = $zipHash
            archivePath = $archive
            backupPath = $backup
            files = @($Descriptor.Files | ForEach-Object { $_.Path })
            removed = @($Descriptor.Removes)
            rollbackAttempted = $false
            rollbackSucceeded = $false
        }
        try {
            $receiptPath = Write-PatchReceipt -Receipt $receipt -Stamp $stamp
        } catch {
            Emit 'WARN' "Patch applied but receipt write failed: $($_.Exception.Message)"
        }
        try { Emit 'PASS' "APPLIED: $($Descriptor.Name)" } catch {}
        return [pscustomobject]@{
            ArchivePath = $archive
            ReceiptPath = $receiptPath
            RestartRequired = (Test-RestartRequired -Touched $touched)
            Touched = $touched
            PatchId = $Descriptor.PatchId
            Title = $Descriptor.Title
            Series = $Descriptor.Series
            Sequence = $Descriptor.Sequence
        }
    } catch {
        $errorMessage = $_.Exception.Message
        Emit 'FAIL' "Patch apply failed; rolling back $($Descriptor.Name): $errorMessage"
        $rollbackAttempted = $true
        try {
            Restore-PatchBackup -Backup $backup -OriginallyExisting $existing -OriginallyMissing $missing
            $rollbackSucceeded = $true
        } catch {
            Emit 'FAIL' "Patch rollback encountered an error: $($_.Exception.Message)"
        }

        if (Test-Path -LiteralPath $zipPath -PathType Leaf) {
            try { $archive = Move-PatchTransport -ZipPath $zipPath -Disposition failed -Stamp $stamp } catch {}
        }

        $receipt = @{
            schema = 'cortex.patch_receipt.v1'
            status = 'FAILED'
            patchId = $Descriptor.PatchId
            title = $Descriptor.Title
            series = $Descriptor.Series
            sequence = $Descriptor.Sequence
            failedUtc = (Get-Date).ToUniversalTime().ToString('o')
            sourceZipSha256 = $zipHash
            archivePath = $archive
            backupPath = $backup
            files = @($Descriptor.Files | ForEach-Object { $_.Path })
            removed = @($Descriptor.Removes)
            error = $errorMessage
            rollbackAttempted = $rollbackAttempted
            rollbackSucceeded = $rollbackSucceeded
        }
        try { $receiptPath = Write-PatchReceipt -Receipt $receipt -Stamp $stamp } catch {}

        # Arm one-shot evidence for the failure bundle too. This lets the
        # controller name PATCH_INTAKE_FAIL evidence after the actual patch
        # instead of producing an anonymous generic debug ZIP.
        $failureEvidence = @{
            schema = 'cortex.post_patch_startup_evidence.v1'
            createdUtc = (Get-Date).ToUniversalTime().ToString('o')
            patchCount = 1
            primaryPatchId = [string]$Descriptor.PatchId
            primaryTitle = [string]$Descriptor.Title
            restartRequired = $false
            failed = $true
            failureReason = $errorMessage
            patches = @(
                @{
                    patchId = [string]$Descriptor.PatchId
                    title = [string]$Descriptor.Title
                    series = [string]$Descriptor.Series
                    sequence = [string]$Descriptor.Sequence
                    archivePath = [string]$archive
                    receiptPath = [string]$receiptPath
                    restartRequired = $false
                    status = 'FAILED'
                }
            )
        }
        try {
            $failureEvidence | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $StartupEvidencePath -Encoding UTF8
            Emit 'INFO' ("Patch failure evidence armed for {0}." -f $Descriptor.PatchId)
        } catch {
            Emit 'WARN' ("Could not write patch failure evidence marker: {0}" -f $_.Exception.Message)
        }

        throw "Failed patch $($Descriptor.PatchId): $errorMessage"
    } finally {
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Quarantine-InvalidPatch {
    param(
        [Parameter(Mandatory=$true)][string]$ZipPath,
        [Parameter(Mandatory=$true)][string]$Reason
    )
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $name = [IO.Path]::GetFileName($ZipPath)
    $patchId = ([IO.Path]::GetFileNameWithoutExtension($name) -replace '[^A-Za-z0-9._-]','_')
    $archive = $null
    try { $archive = Move-PatchTransport -ZipPath $ZipPath -Disposition failed -Stamp $stamp } catch {}
    $receipt = @{
        schema = 'cortex.patch_receipt.v1'
        status = 'INVALID'
        patchId = $patchId
        title = 'Invalid patch transport'
        failedUtc = (Get-Date).ToUniversalTime().ToString('o')
        archivePath = $archive
        error = $Reason
        rollbackAttempted = $false
        rollbackSucceeded = $false
    }
    try { [void](Write-PatchReceipt -Receipt $receipt -Stamp $stamp) } catch {}
}

Emit 'INFO' 'START Root manifest-authoritative patch intake'

$roots = @($ProjectRoot)
$inbox = Join-Path $ProjectRoot 'updates\inbox'
if (Test-Path -LiteralPath $inbox) { $roots += $inbox }

$candidates = @()
foreach ($root in $roots) {
    $candidates += @(Get-ChildItem -LiteralPath $root -Filter '*.zip' -File -ErrorAction SilentlyContinue)
}
$candidates = @($candidates | Sort-Object FullName -Unique)

# Manifest authority wins over transport naming. A handoff-named ZIP is still a
# patch when it carries exactly one root PATCH_MANIFEST.json. Non-patch ZIPs
# remain ignored instead of being quarantined merely because they are present.
$patchCandidates = @($candidates | Where-Object { Test-RootPatchTransport $_.FullName })
$ignored = @($candidates).Count - @($patchCandidates).Count

if (@($patchCandidates).Count -eq 0) {
    Emit 'PASS' 'Root patch intake: no pending patch ZIPs detected.'
    return [pscustomobject]@{
        Applied = 0
        Pending = 0
        Validated = 0
        Invalid = 0
        Ignored = $ignored
        Archives = @()
        Receipts = @()
        RestartRequired = $false
    }
}

$descriptors = @()
$invalidRows = @()

foreach ($patch in $patchCandidates) {
    try {
        $descriptor = Read-PatchManifest -ZipPath $patch.FullName
        $descriptors += $descriptor
    } catch {
        $invalidRows += [pscustomobject]@{ Path = $patch.FullName; Name = $patch.Name; Error = $_.Exception.Message }
    }
}

$descriptors = @($descriptors | Sort-Object Series,Sequence,Name)

try {
    if ($descriptors.Count -gt 0) {
        Assert-QueueDependencies -Descriptors $descriptors
    }
} catch {
    if ($ScanOnly -or $ValidateOnly) {
        $invalidRows += [pscustomobject]@{ Path = ''; Name = 'queue'; Error = $_.Exception.Message }
    } else {
        throw
    }
}

if ($ScanOnly) {
    foreach ($invalid in $invalidRows) { Emit 'WARN' "INVALID PATCH: $($invalid.Name): $($invalid.Error)" }
    foreach ($descriptor in $descriptors) { Emit 'INFO' "PENDING: $($descriptor.PatchId) - $($descriptor.Name)" }
    return [pscustomobject]@{
        Applied = 0
        Pending = $descriptors.Count
        Validated = 0
        Invalid = $invalidRows.Count
        Ignored = $ignored
        Archives = @()
        Receipts = @()
        RestartRequired = $false
    }
}

if ($ValidateOnly) {
    $validated = 0
    foreach ($descriptor in $descriptors) {
        try {
            Validate-PatchPayload -Descriptor $descriptor
            $validated++
            Emit 'PASS' "VALIDATED: $($descriptor.PatchId)"
        } catch {
            $invalidRows += [pscustomobject]@{ Path = $descriptor.ZipPath; Name = $descriptor.Name; Error = $_.Exception.Message }
            Emit 'WARN' "INVALID PATCH: $($descriptor.Name): $($_.Exception.Message)"
        }
    }
    return [pscustomobject]@{
        Applied = 0
        Pending = $descriptors.Count
        Validated = $validated
        Invalid = $invalidRows.Count
        Ignored = $ignored
        Archives = @()
        Receipts = @()
        RestartRequired = $false
    }
}

if ($invalidRows.Count -gt 0) {
    foreach ($invalid in $invalidRows) {
        Emit 'FAIL' "INVALID PATCH: $($invalid.Name): $($invalid.Error)"
        if ($invalid.Path -and (Test-Path -LiteralPath $invalid.Path -PathType Leaf)) {
            Quarantine-InvalidPatch -ZipPath $invalid.Path -Reason $invalid.Error
        }
    }
    throw "Patch intake refused because $($invalidRows.Count) pending patch transport(s) are invalid."
}

$results = @()
foreach ($descriptor in $descriptors) {
    Emit 'INFO' "PATCH DETECTED: $($descriptor.PatchId) - $($descriptor.Name)"
    $results += (Apply-Patch -Descriptor $descriptor)
}

$archives = @($results | ForEach-Object { $_.ArchivePath })
$receipts = @($results | ForEach-Object { $_.ReceiptPath })
$restartRequired = @($results | Where-Object { $_.RestartRequired }).Count -gt 0

if ($results.Count -gt 0) {
    $primary = $results[-1]
    $startupEvidence = @{
        schema = 'cortex.post_patch_startup_evidence.v1'
        createdUtc = (Get-Date).ToUniversalTime().ToString('o')
        patchCount = $results.Count
        primaryPatchId = [string]$primary.PatchId
        primaryTitle = [string]$primary.Title
        restartRequired = $restartRequired
        patches = @(
            $results | ForEach-Object {
                @{
                    patchId = [string]$_.PatchId
                    title = [string]$_.Title
                    series = [string]$_.Series
                    sequence = [string]$_.Sequence
                    archivePath = [string]$_.ArchivePath
                    receiptPath = [string]$_.ReceiptPath
                    restartRequired = [bool]$_.RestartRequired
                }
            }
        )
    }
    try {
        $startupEvidence | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $StartupEvidencePath -Encoding UTF8
        Emit 'INFO' ("Post-patch startup evidence armed for {0}." -f $startupEvidence.primaryPatchId)
    } catch {
        Emit 'WARN' ("Could not write post-patch startup evidence marker: {0}" -f $_.Exception.Message)
    }
}

Emit 'PASS' ("Root patch intake complete: {0} applied." -f $results.Count)
return [pscustomobject]@{
    Applied = $results.Count
    Pending = 0
    Validated = $results.Count
    Invalid = 0
    Ignored = $ignored
    Archives = $archives
    Receipts = $receipts
    RestartRequired = $restartRequired
}
