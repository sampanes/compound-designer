@echo off
rem Rebuild a parcel's site_master.blend headless. Usage: build_site.bat parcels\my_parcel [--no-render]
rem Blender: BLENDER if set, else Blender 5.1, else the newest Blender under Program Files (_find_blender.bat).
rem Short-lived (no window, quits when done).
setlocal
if "%~1"=="" (echo usage: %~nx0 PARCEL_DIR [--no-render] & exit /b 2)
call "%~dp0_find_blender.bat" || exit /b 2
"%BLENDER%" -b --factory-startup -noaudio --python "%~dp0build_site.py" -- "%~f1" %2
exit /b %ERRORLEVEL%
