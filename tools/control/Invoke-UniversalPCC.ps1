[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$ForwardArgs
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')) }
$controller = Join-Path $PSScriptRoot 'ProjectControlCenter.ps1'
Write-Warning 'Invoke-UniversalPCC.ps1 is a compatibility bridge to the authoritative Cortex Project Control Center.'
if ($ForwardArgs -and $ForwardArgs.Count -gt 0) {
    & $controller -ProjectRoot $ProjectRoot -Command $ForwardArgs[0] -NonInteractive
} else {
    & $controller -ProjectRoot $ProjectRoot
}
exit $LASTEXITCODE
