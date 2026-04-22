@echo off
REM SCP: Information Containment — start the daemon
setlocal
set "SCRIPT_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run-daemon.ps1" %*
exit /b %ERRORLEVEL%
