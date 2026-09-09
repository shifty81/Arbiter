@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>nul
set "CORTEX_ROOT=%~dp0"
if "%CORTEX_ROOT:~-1%"=="\" set "CORTEX_ROOT=%CORTEX_ROOT:~0,-1%"
set "PCC=%CORTEX_ROOT%\tools\control\CortexPCC.py"
set "PCC_EXIT=1"

where py.exe >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  py.exe -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
  if %ERRORLEVEL% EQU 0 (
    py.exe -3 "%PCC%" --root "%CORTEX_ROOT%"
    set "PCC_EXIT=%ERRORLEVEL%"
    goto :done
  )
)

where python.exe >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  python.exe -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
  if %ERRORLEVEL% EQU 0 (
    python.exe "%PCC%" --root "%CORTEX_ROOT%"
    set "PCC_EXIT=%ERRORLEVEL%"
    goto :done
  )
)

echo [FAIL] Cortex Python Project Control Center requires Python 3.10 or newer.
set "PCC_EXIT=1"

:done
if not "%PCC_EXIT%"=="0" (
  echo.
  echo Cortex Project Control Center exited with code %PCC_EXIT%.
  echo Latest evidence: %CORTEX_ROOT%\artifacts\debug\LATEST_DEBUG_BUNDLE.txt
  if exist "%CORTEX_ROOT%\artifacts\debug" start "" explorer.exe "%CORTEX_ROOT%\artifacts\debug"
  echo.
  pause
)
exit /b %PCC_EXIT%
