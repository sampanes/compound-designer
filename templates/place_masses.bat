@echo off
rem Place building masses from a design JSON. Usage: place_masses.bat parcels\my_parcel parcels\my_parcel\design_v1.json [--no-render]
rem Uses BLENDER if set, else Blender 5.1. Short-lived (no window, quits when done).
setlocal
if "%~2"=="" (echo usage: %~nx0 PARCEL_DIR DESIGN.json [--no-render] & exit /b 2)
if not defined BLENDER set "BLENDER=C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
"%BLENDER%" -b --factory-startup -noaudio --python "%~dp0place_masses.py" -- "%~f1" "%~f2" %3
exit /b %ERRORLEVEL%
