[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$Branch = 'main',
    [string]$RemoteName = 'origin',
    [string]$RemoteUrl = 'https://github.com/shifty81/Cortex.git',
    [switch]$ReplaceRemote
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Normalize-PathArgument {
    param([AllowNull()][string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $null }
    $value = $Path.Trim().Trim('"').Trim("'").Trim()
    if ([string]::IsNullOrWhiteSpace($value)) { return $null }
    return $value
}

$normalizedRoot = Normalize-PathArgument $ProjectRoot
if (-not $normalizedRoot) { throw 'Project root was empty or malformed.' }

try { $root = [System.IO.Path]::GetFullPath($normalizedRoot) }
catch { throw "Project root could not be resolved safely: '$ProjectRoot'" }

if (-not (Test-Path -LiteralPath $root -PathType Container)) {
    throw "Project root does not exist: $root"
}

$git = Get-Command git -ErrorAction Stop

Push-Location $root
try {
    $inside = (& $git.Source rev-parse --is-inside-work-tree 2>$null)
    if ($LASTEXITCODE -ne 0 -or $inside -ne 'true') {
        if ($PSCmdlet.ShouldProcess($root, "Initialize Git repository with branch '$Branch'")) {
            & $git.Source init -b $Branch
            if ($LASTEXITCODE -ne 0) { throw 'git init failed' }
        }
    }

    $currentBranch = (& $git.Source branch --show-current 2>$null)
    if ($LASTEXITCODE -eq 0 -and $currentBranch -and $currentBranch -ne $Branch) {
        if ($PSCmdlet.ShouldProcess($root, "Rename current Git branch '$currentBranch' to '$Branch'")) {
            & $git.Source branch -M $Branch
            if ($LASTEXITCODE -ne 0) { throw "git branch -M $Branch failed" }
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($RemoteUrl)) {
        & $git.Source remote get-url $RemoteName *> $null
        $remoteExists = ($LASTEXITCODE -eq 0)

        if ($remoteExists) {
            $existingUrl = (& $git.Source remote get-url $RemoteName).Trim()
            if ($existingUrl -eq $RemoteUrl) {
                Write-Host "Remote '$RemoteName' already points to $RemoteUrl"
            } elseif ($ReplaceRemote) {
                & $git.Source remote set-url $RemoteName $RemoteUrl
                if ($LASTEXITCODE -ne 0) { throw 'remote replacement failed' }
            } else {
                Write-Warning "Remote '$RemoteName' currently points to '$existingUrl'."
                Write-Warning "Expected Cortex remote: '$RemoteUrl'"
                Write-Warning "Re-run with -ReplaceRemote to make the Cortex remote authoritative."
            }
        } else {
            & $git.Source remote add $RemoteName $RemoteUrl
            if ($LASTEXITCODE -ne 0) { throw 'remote configuration failed' }
        }
    }

    Write-Host ''
    Write-Host 'Cortex Git bootstrap complete.'
    & $git.Source status --short --branch
    Write-Host ''
    & $git.Source remote -v
    Write-Host ''
    Write-Host 'No commit or push was performed.'
} finally {
    Pop-Location
}
