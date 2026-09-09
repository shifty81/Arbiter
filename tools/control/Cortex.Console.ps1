Set-StrictMode -Version Latest

function Set-CortexConsoleDefaults {
    try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false) } catch {}
    try { $Host.UI.RawUI.ForegroundColor = 'Gray' } catch {}
    try { $Host.UI.RawUI.BackgroundColor = 'Black' } catch {}
    $env:CARGO_TERM_COLOR = 'always'
    $env:CLICOLOR = '1'
    $env:CLICOLOR_FORCE = '1'
}

function Write-CortexText {
    param(
        [Parameter(Mandatory=$true)][string]$Text,
        [ValidateSet('Default','Header','Info','Pass','Warn','Fail','Debug','Muted','Label','Value','Accent')]
        [string]$Style = 'Default',
        [switch]$NoNewline
    )
    $color = switch ($Style) {
        'Header' { 'Cyan' }
        'Info'   { 'Cyan' }
        'Pass'   { 'Green' }
        'Warn'   { 'Yellow' }
        'Fail'   { 'Red' }
        'Debug'  { 'DarkGray' }
        'Muted'  { 'DarkGray' }
        'Label'  { 'DarkCyan' }
        'Value'  { 'White' }
        'Accent' { 'Magenta' }
        default  { 'Gray' }
    }
    Write-Host $Text -ForegroundColor $color -NoNewline:$NoNewline
}

function Write-CortexRule {
    param([string]$Title = '', [int]$Width = 72)
    if ([string]::IsNullOrWhiteSpace($Title)) {
        Write-CortexText ('=' * $Width) 'Header'
        return
    }
    $inner = " $Title "
    $remaining = [Math]::Max(0, $Width - $inner.Length)
    $left = [Math]::Floor($remaining / 2)
    $right = $remaining - $left
    Write-CortexText (("=" * $left) + $inner + ("=" * $right)) 'Header'
}

function Write-CortexEvent {
    param(
        [ValidateSet('INFO','PASS','WARN','FAIL','DEBUG','SKIP')][string]$Kind,
        [Parameter(Mandatory=$true)][string]$Message,
        [string]$LogPath
    )
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $style = switch ($Kind) {
        'PASS' { 'Pass' }
        'WARN' { 'Warn' }
        'FAIL' { 'Fail' }
        'DEBUG' { 'Debug' }
        'SKIP' { 'Warn' }
        default { 'Info' }
    }
    $line = "[$stamp] [$Kind] $Message"
    Write-CortexText $line $style
    if ($LogPath) {
        try {
            $dir = Split-Path -Parent $LogPath
            if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
            Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
        } catch {}
    }
}

function Write-CortexStatusRow {
    param([string]$Label, [string]$Value, [string]$ValueStyle = 'Value')
    Write-CortexText ((" {0,-11}: " -f $Label)) 'Label' -NoNewline
    Write-CortexText $Value $ValueStyle
}
