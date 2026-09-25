@echo off
echo Dang tat LMS DLU...

taskkill /FI "WINDOWTITLE eq LMS Backend*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq LMS Frontend*" /T /F >nul 2>&1

echo Da tat LMS DLU.
timeout /t 2 >nul