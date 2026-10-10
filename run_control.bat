@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "APP=%~dp0control_entry.py"
set "EXE=%~dp0dist\Codex-Hybrid-Control.exe"
if exist "%~dp0dist\7.3.2\Codex-Hybrid-Control.exe" set "EXE=%~dp0dist\7.3.2\Codex-Hybrid-Control.exe"
if not exist "%EXE%" set "EXE=%~dp0Codex-Hybrid-Control.exe"
set "LOG=%~dp0Codex-Hybrid-Control-launch.log"

>"%LOG%" echo Codex Hybrid Control launcher
>>"%LOG%" echo Folder: %~dp0
>>"%LOG%" echo Date: %DATE% %TIME%

if exist "%EXE%" (
  >>"%LOG%" echo Using packaged EXE.
  start "" "%EXE%"
  exit /b 0
)

if not exist "%APP%" goto :missing_app

where py.exe >nul 2>&1
if not errorlevel 1 (
  >>"%LOG%" echo Trying Python launcher py.exe -3.
  py.exe -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 42)" >>"%LOG%" 2>&1
  if errorlevel 1 goto :after_py_launcher
  py.exe -3 "%APP%" --startup-check >>"%LOG%" 2>&1
  if not errorlevel 1 (
    where pyw.exe >nul 2>&1
    if not errorlevel 1 (
      >>"%LOG%" echo Startup check OK. Launching with pyw.exe.
      start "" pyw.exe -3 "%APP%"
      exit /b 0
    )
    >>"%LOG%" echo pyw.exe not found. Launching py.exe minimized.
    start "Codex Hybrid Control" /min py.exe -3 "%APP%"
    exit /b 0
  )
  >>"%LOG%" echo py.exe startup check failed.
)
:after_py_launcher

where python.exe >nul 2>&1
if not errorlevel 1 (
  >>"%LOG%" echo Trying python.exe from PATH.
  python.exe -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 42)" >>"%LOG%" 2>&1
  if errorlevel 1 goto :after_python_path
  python.exe "%APP%" --startup-check >>"%LOG%" 2>&1
  if not errorlevel 1 (
    where pythonw.exe >nul 2>&1
    if not errorlevel 1 (
      >>"%LOG%" echo Startup check OK. Launching with pythonw.exe.
      start "" pythonw.exe "%APP%"
      exit /b 0
    )
    >>"%LOG%" echo pythonw.exe not found. Launching python.exe minimized.
    start "Codex Hybrid Control" /min python.exe "%APP%"
    exit /b 0
  )
  >>"%LOG%" echo python.exe startup check failed.
)
:after_python_path

set "PYEXE="
if exist "%LocalAppData%\Programs\Python" (
  for /f "delims=" %%P in ('where /r "%LocalAppData%\Programs\Python" python.exe 2^>nul') do if not defined PYEXE set "PYEXE=%%P"
)
if not defined PYEXE if exist "%ProgramFiles%\Python" (
  for /f "delims=" %%P in ('where /r "%ProgramFiles%\Python" python.exe 2^>nul') do if not defined PYEXE set "PYEXE=%%P"
)
if defined PYEXE goto :try_found_python
goto :no_python

:try_found_python
>>"%LOG%" echo Trying discovered Python: %PYEXE%
"%PYEXE%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 42)" >>"%LOG%" 2>&1
if errorlevel 1 goto :no_python
"%PYEXE%" "%APP%" --startup-check >>"%LOG%" 2>&1
if errorlevel 1 goto :startup_failed
for %%P in ("%PYEXE%") do set "PYDIR=%%~dpP"
if exist "%PYDIR%pythonw.exe" (
  >>"%LOG%" echo Startup check OK. Launching discovered pythonw.exe.
  start "" "%PYDIR%pythonw.exe" "%APP%"
  exit /b 0
)
>>"%LOG%" echo Startup check OK. Launching discovered python.exe minimized.
start "Codex Hybrid Control" /min "%PYEXE%" "%APP%"
exit /b 0

:startup_failed
>>"%LOG%" echo Startup check failed for discovered Python.
goto :show_failure

:missing_app
>>"%LOG%" echo ERROR: codex_hybrid_control.py is missing.
goto :show_failure

:no_python
>>"%LOG%" echo ERROR: Python 3 was not found.
goto :show_failure

:show_failure
call :show_ru_error
start "" notepad.exe "%LOG%"
exit /b 1

:show_ru_error
powershell.exe -NoLogo -NoProfile -EncodedCommand JABtAHMAZwA9ACcAQwBvAGQAZQB4ACAASAB5AGIAcgBpAGQAIABDAG8AbgB0AHIAbwBsACAAPQQ1BCAAQwQ0BDAEOwQ+BEEETAQgADcEMAQ/BEMEQQRCBDgEQgRMBC4AIAAeBEIEOgRABD4EOQQgADsEPgQzBCAAQwBvAGQAZQB4AC0ASAB5AGIAcgBpAGQALQBDAG8AbgB0AHIAbwBsAC0AbABhAHUAbgBjAGgALgBsAG8AZwAgADIEIAA/BDAEPwQ6BDUEIAA/BEAEOAQ7BD4ENgQ1BD0EOARPBC4AJwA7ACAAQQBkAGQALQBUAHkAcABlACAALQBBAHMAcwBlAG0AYgBsAHkATgBhAG0AZQAgAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwA7ACAAWwB2AG8AaQBkAF0AWwBTAHkAcwB0AGUAbQAuAFcAaQBuAGQAbwB3AHMALgBGAG8AcgBtAHMALgBNAGUAcwBzAGEAZwBlAEIAbwB4AF0AOgA6AFMAaABvAHcAKAAkAG0AcwBnACwAJwBDAG8AZABlAHgAIABIAHkAYgByAGkAZAAgAEMAbwBuAHQAcgBvAGwAJwAsAFsAUwB5AHMAdABlAG0ALgBXAGkAbgBkAG8AdwBzAC4ARgBvAHIAbQBzAC4ATQBlAHMAcwBhAGcAZQBCAG8AeABCAHUAdAB0AG8AbgBzAF0AOgA6AE8ASwAsAFsAUwB5AHMAdABlAG0ALgBXAGkAbgBkAG8AdwBzAC4ARgBvAHIAbQBzAC4ATQBlAHMAcwBhAGcAZQBCAG8AeABJAGMAbwBuAF0AOgA6AEUAcgByAG8AcgApAA== >nul 2>&1
exit /b 0
