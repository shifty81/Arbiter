@echo off
setlocal EnableExtensions
set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

set "CORTEX_DESKTOP="
if defined CORTEX_HOME if exist "%CORTEX_HOME%\target\release\cortex_desktop.exe" set "CORTEX_DESKTOP=%CORTEX_HOME%\target\release\cortex_desktop.exe"
if not defined CORTEX_DESKTOP if defined CORTEX_HOME if exist "%CORTEX_HOME%\target\debug\cortex_desktop.exe" set "CORTEX_DESKTOP=%CORTEX_HOME%\target\debug\cortex_desktop.exe"
if not defined CORTEX_DESKTOP if exist "%PROJECT_ROOT%\..\Cortex\target\release\cortex_desktop.exe" set "CORTEX_DESKTOP=%PROJECT_ROOT%\..\Cortex\target\release\cortex_desktop.exe"
if not defined CORTEX_DESKTOP if exist "%PROJECT_ROOT%\..\Cortex\target\debug\cortex_desktop.exe" set "CORTEX_DESKTOP=%PROJECT_ROOT%\..\Cortex\target\debug\cortex_desktop.exe"
if not defined CORTEX_DESKTOP if exist "%LOCALAPPDATA%\Cortex\bin\cortex_desktop.exe" set "CORTEX_DESKTOP=%LOCALAPPDATA%\Cortex\bin\cortex_desktop.exe"

if not defined CORTEX_DESKTOP (
  echo Cortex Desktop could not be resolved.
  echo Set CORTEX_HOME to the Cortex checkout/install root or install Cortex.
  pause
  exit /b 1
)

set "CORTEX_WORKSPACE=%PROJECT_ROOT%"
start "Cortex" /D "%PROJECT_ROOT%" "%CORTEX_DESKTOP%"
exit /b 0
