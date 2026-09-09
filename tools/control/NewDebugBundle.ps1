[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ProjectRoot,
    [string]$Status = 'MANUAL'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'New-CortexDebugBundle.ps1') -ProjectRoot $ProjectRoot -Reason $Status -OpenFolder
exit $LASTEXITCODE
