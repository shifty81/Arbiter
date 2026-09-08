@echo off
setlocal EnableExtensions
set "CORTEX_ROOT=%~dp0"
if "%CORTEX_ROOT:~-1%"=="\" set "CORTEX_ROOT=%CORTEX_ROOT:~0,-1%"

rem Recovery guard: do not let the known-bad generated controller patches reapply.
set "CORTEX_QUARANTINE=%CORTEX_ROOT%\artifacts\updates\failed\recovery-quarantine"
if not exist "%CORTEX_QUARANTINE%" mkdir "%CORTEX_QUARANTINE%" >nul 2>nul
for %%F in (
  "%CORTEX_ROOT%\Cortex_CTX-ROOT-01*.zip"
  "%CORTEX_ROOT%\Cortex_CTX-ROOT-02*.zip"
  "%CORTEX_ROOT%\Cortex_CTX-NORM-*.zip"
) do (
  if exist "%%~fF" move /Y "%%~fF" "%CORTEX_QUARANTINE%\" >nul 2>nul
)

where pwsh.exe >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  set "PCC_PS=pwsh.exe"
) else (
  set "PCC_PS=powershell.exe"
)

rem This controller is the exact last-FULL-GREEN version and resolves its own root.
"%PCC_PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%CORTEX_ROOT%\tools\control\ProjectControlCenter.ps1"
set "PCC_EXIT=%ERRORLEVEL%"
if not "%PCC_EXIT%"=="0" (
  echo.
  echo Cortex Root Project Control Center exited with code %PCC_EXIT%.
  echo The recovery baseline is the exact controller captured in the last FULL_GREEN bundle.
  echo Check artifacts\debug and logs\sessions for the newest handoff evidence.
  echo.
  pause
)
exit /b %PCC_EXIT%
