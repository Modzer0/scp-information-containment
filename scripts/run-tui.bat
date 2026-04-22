@echo off
REM SCP: Information Containment — attach the TUI
setlocal
set "SCRIPT_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run-tui.ps1" %*
exit /b %ERRORLEVEL%
