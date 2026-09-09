param(
    [Parameter(Mandatory=$true)][int]$ProcessId
)

$ErrorActionPreference = "Stop"
Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class CortexWindowInspectNative {
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);

    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool IsHungAppWindow(IntPtr hWnd);
}
"@

$process = Get-Process -Id $ProcessId -ErrorAction Stop
$process.Refresh()
$handle = $process.MainWindowHandle
$hasWindow = $handle -ne [IntPtr]::Zero
$visible = $false
$responsive = $false
$bounds = $null
if ($hasWindow) {
    $visible = [CortexWindowInspectNative]::IsWindowVisible($handle)
    $responsive = -not [CortexWindowInspectNative]::IsHungAppWindow($handle)
    $rect = New-Object CortexWindowInspectNative+RECT
    if ([CortexWindowInspectNative]::GetWindowRect($handle, [ref]$rect)) {
        $bounds = [ordered]@{
            x = $rect.Left
            y = $rect.Top
            width = $rect.Right - $rect.Left
            height = $rect.Bottom - $rect.Top
        }
    }
}

$result = [ordered]@{
    schema_version = 1
    pid = $ProcessId
    process_name = $process.ProcessName
    title = $process.MainWindowTitle
    has_window = $hasWindow
    visible = $visible
    responsive = $responsive
    bounds = $bounds
}
$result | ConvertTo-Json -Depth 4 -Compress
