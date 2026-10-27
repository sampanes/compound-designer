@echo off
rem Find blender.exe for the wrapper that called this and set BLENDER in the caller's environment
rem (no setlocal here, on purpose). Order: BLENDER if already set, then Blender 5.1, then the newest
rem "Blender *" folder under Program Files. Prints [BLENDER] path, or [X] and exits 2.
if not defined BLENDER goto :search
if exist "%BLENDER%" goto :found
echo [X] BLENDER not found: %BLENDER%
exit /b 2
:search
set "BLENDER=C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
if exist "%BLENDER%" goto :found
set "BLENDER="
for /d %%D in ("C:\Program Files\Blender Foundation\Blender *") do if exist "%%~D\blender.exe" set "BLENDER=%%~D\blender.exe"
if defined BLENDER goto :found
echo [X] no Blender found; set BLENDER=^<path to blender.exe^>
exit /b 2
:found
echo [BLENDER] %BLENDER%
exit /b 0
