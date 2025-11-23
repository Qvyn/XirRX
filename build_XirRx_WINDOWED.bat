@echo off
setlocal ENABLEEXTENSIONS ENABLEDELAYEDEXPANSION

REM === Build XirRx.exe (WINDOWED / NO CONSOLE) ===
cd /d "%~dp0"

set NAME=XirRx
set ENTRY=suite_one_app_safe_baseline_PRO.py
set ICON=XirRx.ico

where pyinstaller >nul 2>nul
if errorlevel 1 (
    echo [ERROR] PyInstaller not found. Install with:  python -m pip install pyinstaller
    exit /b 1
)

set ERR=0
for %%F in ("%ENTRY%" "input_refiner_pyqt6_stable_patched_ultrasens.py" "crosshair_x_designer_stack_patched.py" "launcher.py" "%ICON%") do (
    if not exist %%~F (
        echo [ERROR] Missing file: %%~F
        set ERR=1
    )
)
if %ERR% NEQ 0 exit /b 2

if exist build rd /s /q build
if exist dist rd /s /q dist
if exist "%NAME%.spec" del /q "%NAME%.spec"
if exist "%NAME%.exe" del /q "%NAME%.exe"

REM --windowed == --noconsole (no terminal window)
pyinstaller ^
  --noconfirm ^
  --name "%NAME%" ^
  --icon "%ICON%" ^
  --onefile ^
  --windowed ^
  --clean ^
  --hidden-import launcher ^
  --hidden-import comtypes ^
  --hidden-import psutil ^
  "%ENTRY%"

if errorlevel 1 (
    echo [ERROR] PyInstaller failed.
    exit /b 3
)

if exist "dist\%NAME%.exe" (
    copy /y "dist\%NAME%.exe" ".\%NAME%.exe" >nul
) else if exist "dist\%NAME%\%NAME%.exe" (
    copy /y "dist\%NAME%\%NAME%.exe" ".\%NAME%.exe" >nul
)

echo Done.
exit /b 0
