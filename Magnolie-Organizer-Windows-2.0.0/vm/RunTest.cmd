@echo off
taskkill /IM "Magnolie Organizer.exe" /F >nul 2>nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0StartTest.ps1"
