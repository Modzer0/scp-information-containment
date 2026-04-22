@echo off
REM SCP: Information Containment — Windows cmd wrapper for install.ps1
setlocal
set "SCRIPT_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%install.ps1" %*
exit /b %ERRORLEVEL%
