[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$LogPath
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
} else {
    $ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
}
$console = Join-Path $PSScriptRoot 'Cortex.Console.ps1'
if (Test-Path -LiteralPath $console -PathType Leaf) { . $console }
function Emit([string]$Kind,[string]$Message) {
    if (Get-Command Write-CortexEvent -ErrorAction SilentlyContinue) { Write-CortexEvent $Kind $Message $LogPath }
    else { Write-Host "[$Kind] $Message" }
}
function Get-ScriptParameterNames($Ast) {
    if ($null -eq $Ast.ParamBlock) { return @() }
    return @($Ast.ParamBlock.Parameters | ForEach-Object { $_.Name.VariablePath.UserPath })
}

$failed = $false
$asts = @{}
$controlScripts = @(Get-ChildItem -LiteralPath $PSScriptRoot -Recurse -File -ErrorAction Stop | Where-Object { $_.Extension -in @('.ps1','.psm1') } | Sort-Object FullName)
foreach ($file in $controlScripts) {
    $tokens = $null
    $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($file.FullName,[ref]$tokens,[ref]$parseErrors)
    if (@($parseErrors).Count -gt 0) {
        Emit 'FAIL' ("PowerShell parse failure in {0}: {1}" -f $file.Name,$parseErrors[0].Message)
        $failed = $true
    } else {
        $asts[$file.Name] = $ast
    }
}

$contracts = @(
    @{ File='ProjectControlCenter.ps1'; Required=@('ProjectRoot','Command','LogPath','NonInteractive') },
    @{ File='InvokeRootPatchIntake.ps1'; Required=@('ProjectRoot','LogPath','Apply','ScanOnly') },
    @{ File='Test-CortexQuickGate.ps1'; Required=@('ProjectRoot','LogPath') },
    @{ File='Test-CortexControlContracts.ps1'; Required=@('ProjectRoot','LogPath') },
    @{ File='New-CortexDebugBundle.ps1'; Required=@('ProjectRoot','Reason','LogPath','FailedStage','ExitCode','OpenFolder') }
)
foreach ($contract in $contracts) {
    $path = Join-Path $PSScriptRoot $contract.File
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Emit 'FAIL' ("Control contract file missing: {0}" -f $contract.File)
        $failed = $true
        continue
    }
    if (-not $asts.ContainsKey($contract.File)) { $failed = $true; continue }
    $names = @(Get-ScriptParameterNames -Ast $asts[$contract.File])
    foreach ($required in $contract.Required) {
        if ($required -notin $names) {
            Emit 'FAIL' ("Parameter contract mismatch: {0} missing -{1}" -f $contract.File,$required)
            $failed = $true
        }
    }
}

foreach ($requiredFile in @('Cortex.Console.ps1','CortexPCC.py','CortexGitAuthority.py','CortexPatchAuthority.py','CortexPCCMaintenance.py','GitSourceControl.ps1')) {
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $requiredFile) -PathType Leaf)) {
        Emit 'FAIL' "Required control authority missing: $requiredFile"
        $failed = $true
    }
}

$python = Get-Command python -ErrorAction SilentlyContinue
$prefix = @()
if ($null -eq $python) { $python = Get-Command py -ErrorAction SilentlyContinue; if ($null -ne $python) { $prefix = @('-3') } }
if ($null -eq $python) {
    Emit 'FAIL' 'Python 3 is required by the authoritative Cortex PCC.'
    $failed = $true
} else {
    $pyFiles = @(Get-ChildItem -LiteralPath $PSScriptRoot -Recurse -Filter '*.py' -File -ErrorAction Stop | Select-Object -ExpandProperty FullName)
    if ($pyFiles.Count -gt 0) {
        $code = 'import ast,sys; [ast.parse(open(p,"r",encoding="utf-8-sig").read(),p) for p in sys.argv[1:]]'
        & $python.Source @prefix '-c' $code @pyFiles
        if ($LASTEXITCODE -ne 0) { Emit 'FAIL' 'Python PCC authority parse validation failed.'; $failed = $true }
        else { Emit 'PASS' ("Python PCC contracts parsed: {0} files." -f $pyFiles.Count) }
    }
}

if ($failed) { Emit 'FAIL' 'Cortex root control contracts FAILED.'; exit 1 }
Emit 'PASS' ("Cortex root control contracts valid: {0} PowerShell files parsed." -f $controlScripts.Count)
exit 0
