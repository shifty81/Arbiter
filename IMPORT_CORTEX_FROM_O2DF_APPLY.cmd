@echo off
setlocal
echo.
echo ========================================================================
echo  CORTEX STANDALONE LIVE-SOURCE IMPORT
echo ========================================================================
echo This copies current Cortex-owned source out of O2DF into this Cortex root.
echo O2DF is read-only. Open2D adapters are quarantined under migration.
echo Existing destination files are backed up before overwrite.
echo.
set /p CONFIRM=Type IMPORT to continue: 
if /I not "%CONFIRM%"=="IMPORT" (
    echo Cancelled.
    pause
    exit /b 2
)
where pwsh.exe >nul 2>nul
if %ERRORLEVEL% EQU 0 (set "PS=pwsh.exe") else (set "PS=powershell.exe")
"%PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Import-CortexStandaloneFromO2DF.ps1" -Apply
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
