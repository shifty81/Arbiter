[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ForwardArgs
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$bridge = Join-Path $PSScriptRoot 'ProjectControlCenter.ps1'
if (-not (Test-Path -LiteralPath $bridge -PathType Leaf)) {
    throw "Cortex root utility bridge missing: $bridge"
}
Write-Warning 'Invoke-UniversalPCC.ps1 is a compatibility name only. Cortex now owns universal project operations natively.'
$argsList = @('-ProjectRoot', $ProjectRoot)
if ($ForwardArgs) { $argsList += $ForwardArgs }
& $bridge @argsList
exit $LASTEXITCODE
