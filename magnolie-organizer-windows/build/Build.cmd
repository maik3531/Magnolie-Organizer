@echo off
setlocal
pwsh.exe -NoLogo -NoProfile -File "%~dp0Build.ps1"
exit /b %errorlevel%
