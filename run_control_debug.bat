@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo === Codex Hybrid Control DEBUG ===
echo Folder: %CD%
echo.
set "EXE=%~dp0dist\Codex-Hybrid-Control.exe"
if exist "%~dp0dist\7.3.2\Codex-Hybrid-Control.exe" set "EXE=%~dp0dist\7.3.2\Codex-Hybrid-Control.exe"
if not exist "%EXE%" set "EXE=%~dp0Codex-Hybrid-Control.exe"
if exist "%EXE%" (
  "%EXE%"
  echo Exit code: %ERRORLEVEL%
  pause
  exit /b %ERRORLEVEL%
)
where py.exe >nul 2>&1
if not errorlevel 1 (
  py.exe -3 "control_entry.py"
  echo Exit code: %ERRORLEVEL%
  pause
  exit /b %ERRORLEVEL%
)
where python.exe >nul 2>&1
if not errorlevel 1 (
  python.exe "control_entry.py"
  echo Exit code: %ERRORLEVEL%
  pause
  exit /b %ERRORLEVEL%
)
echo Python 3 was not found.
pause
exit /b 3
