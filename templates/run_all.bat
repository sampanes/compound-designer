@echo off
rem Run the whole pipeline for one parcel folder: fetch the GIS inputs, build the site, place every design.
rem Usage: run_all.bat parcels\my_parcel [--no-render]
rem fetch_gis.py skips files that already exist, so re-running after a config or design edit is cheap.
rem Stops at the first failing step and returns its exit code.
setlocal
if "%~1"=="" (echo usage: %~nx0 PARCEL_DIR [--no-render] & exit /b 2)
if exist "%~f1\parcel.json" goto :start
echo [X] no parcel.json in %~f1
exit /b 2
:start
python --version >nul 2>&1 || (echo [X] python not found on PATH & exit /b 2)

set "STEP=fetch_gis.py"
echo [STEP] fetch GIS inputs for %~f1
python "%~dp0fetch_gis.py" "%~f1"
if errorlevel 1 goto :fail

set "STEP=build_site.bat"
echo [STEP] build site_master.blend
call "%~dp0build_site.bat" "%~f1" %2
if errorlevel 1 goto :fail

set /a K=0
for %%D in ("%~f1\design_*.json") do (
    set /a K+=1
    set "STEP=place_masses.bat %%~nxD"
    echo [STEP] place masses from %%~nxD
    call "%~dp0place_masses.bat" "%~f1" "%%~fD" %2
    if errorlevel 1 goto :fail
)
if %K%==0 echo [INFO] no design_*.json in %~f1, nothing to place
echo [DONE] %~f1: site + %K% design(s)
echo        scenes in blender\, renders in renders\, stats in exports\ (under the parcel folder)
exit /b 0

:fail
set "RC=%ERRORLEVEL%"
echo [X] step failed: %STEP% (exit %RC%)
exit /b %RC%
