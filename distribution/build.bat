@echo off
rem ===== Microscope Controller: build exe + installer =====
rem Usage: build.bat            (build exe, then installer)
rem        build.bat noinstall  (build exe only)
setlocal
cd /d "%~dp0"

set APP_DIR=output\MicroscopeController
set SCRCPY_SRC=..\release\scrcpy-win64-v5.0.1\scrcpy-win64-v5.0.1
set ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe

echo [1/4] Cleaning previous output...
if exist output rmdir /s /q output
if exist build rmdir /s /q build

echo [2/4] Running PyInstaller...
python -m PyInstaller microscope.spec --noconfirm --distpath output --workpath build
if errorlevel 1 goto :fail

echo [3/4] Copying scrcpy bundle and license files...
if not exist "%SCRCPY_SRC%\scrcpy.exe" (
    echo ERROR: scrcpy bundle not found: %SCRCPY_SRC%
    goto :fail
)
rem Exclude backups and helper scripts
robocopy "%SCRCPY_SRC%" "%APP_DIR%\scrcpy" /E /XF *.bak scrcpy-noconsole.vbs open_a_terminal_here.bat /NFL /NDL /NJH /NJS /NP
if errorlevel 8 goto :fail
copy /y "..\LICENSE" "%APP_DIR%\LICENSE-scrcpy.txt" >nul
copy /y "README_distribution.txt" "%APP_DIR%\README.txt" >nul
copy /y "MODIFICATIONS.txt" "%APP_DIR%\MODIFICATIONS.txt" >nul

if /i "%1"=="noinstall" goto :done

echo [4/4] Building installer with Inno Setup...
if not exist "%ISCC%" goto :noiscc
"%ISCC%" installer.iss
if errorlevel 1 goto :fail

:done
echo.
echo Build finished. See the "output" folder.
exit /b 0

:noiscc
echo ERROR: Inno Setup compiler not found.
goto :fail

:fail
echo.
echo BUILD FAILED.
exit /b 1
