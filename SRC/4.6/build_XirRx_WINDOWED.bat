@echo off
setlocal ENABLEEXTENSIONS ENABLEDELAYEDEXPANSION

REM === Build XirRx.exe (WINDOWED / NO CONSOLE) ===
cd /d "%~dp0"

set "NAME=XirRx"
set "ENTRY=suite_one_app_safe_baseline_PRO.py"
set "ICON=XirRx.ico"

REM ---- pick a Python launcher ----
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo [ERROR] Python not found on PATH. Install Python or add it to PATH.
  goto :err
)

REM ---- sanity checks ----
set "ERR=0"
for %%F in ("%ENTRY%" "input_refiner_pyqt6_stable_patched_ultrasens.py" "crosshair_x_designer_stack_patched.py" "%ICON%") do (
  if not exist "%%~F" (
    echo [ERROR] Missing file: %%~F
    set "ERR=1"
  )
)
if "!ERR!" NEQ "0" goto :err

REM ---- clean previous outputs ----
if exist build rd /s /q build
if exist dist rd /s /q dist
if exist "%NAME%.spec" del /q "%NAME%.spec"
if exist "%NAME%.exe" del /q "%NAME%.exe"

echo.
echo Using: %PY%
echo Running PyInstaller...
echo.

REM ---- run PyInstaller via python module (more reliable than PATH pyinstaller.exe) ----
%PY% -m PyInstaller ^
  --noconfirm ^
  --name "%NAME%" ^
  --icon "%ICON%" ^
  --onefile ^
  --windowed ^
  --clean ^
  --hidden-import comtypes ^
  --hidden-import psutil ^
  "%ENTRY%"

if errorlevel 1 (
  echo [ERROR] PyInstaller failed. Scroll up for the first error.
  goto :err
)

REM ---- copy output next to this script ----
if exist "dist\%NAME%.exe" (
  copy /y "dist\%NAME%.exe" ".\%NAME%.exe" >nul
) else if exist "dist\%NAME%\%NAME%.exe" (
  copy /y "dist\%NAME%\%NAME%.exe" ".\%NAME%.exe" >nul
) else (
  echo [ERROR] Build succeeded but output EXE not found under dist\.
  goto :err
)

echo.
echo Done. Output: "%~dp0%NAME%.exe"
echo.
pause
exit /b 0

:err
echo.
echo Build failed.
echo.
pause
exit /b 1
