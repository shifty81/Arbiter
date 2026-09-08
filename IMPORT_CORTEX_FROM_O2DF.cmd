@echo off
setlocal
where pwsh.exe >nul 2>nul
if %ERRORLEVEL% EQU 0 (set "PS=pwsh.exe") else (set "PS=powershell.exe")
"%PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Import-CortexStandaloneFromO2DF.ps1"
echo.
pause
