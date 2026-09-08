[CmdletBinding()]
param()
# Cortex is already the authoritative standalone project.
# This file remains only as a compatibility shim for older adapters that still dispatch the retired stage.
Write-Host '[SKIP] Legacy standalone-boundary migration gate retired; no enforcement performed.' -ForegroundColor Yellow
exit 0
