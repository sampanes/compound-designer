@echo off
rem Rebuild a parcel's site_master.blend headless. Usage: build_site.bat parcels\my_parcel [--no-render]
rem Uses BLENDER if set, else Blender 5.1. Short-lived (no window, quits when done).
setlocal
if "%~1"=="" (echo usage: %~nx0 PARCEL_DIR [--no-render] & exit /b 2)
if not defined BLENDER set "BLENDER=C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
"%BLENDER%" -b --factory-startup -noaudio --python "%~dp0build_site.py" -- "%~f1" %2
exit /b %ERRORLEVEL%
