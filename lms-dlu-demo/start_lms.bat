@echo off
title LMS DLU - Launcher
color 0A

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

if not defined LMS_VENV_DIR set "LMS_VENV_DIR=%SCRIPT_DIR%venv"

echo ==========================================
echo       LMS DLU + DEEPTUTOR LAUNCHER
echo ==========================================
echo.

REM ============================================
REM 1. KIEM TRA SQL SERVER
REM ============================================

echo [1/4] Kiem tra SQL Server...

sc query MSSQLSERVER | find "RUNNING" >nul 2>&1

if %errorlevel%==0 (
    echo [OK] SQL Server dang chay.
) else (
    echo [!] SQL Server chua chay.
    echo Dang thu khoi dong SQL Server...

    net start MSSQLSERVER >nul 2>&1

    timeout /t 3 /nobreak >nul

    sc query MSSQLSERVER | find "RUNNING" >nul 2>&1

    if %errorlevel%==0 (
        echo [OK] SQL Server da duoc khoi dong.
    ) else (
        echo.
        echo [ERROR] Khong the khoi dong SQL Server.
        echo Hay kiem tra SQL Server Service.
        echo.
        pause
        exit /b
    )
)

REM ============================================
REM 2. KIEM TRA PYTHON VENV
REM ============================================

echo.
echo [2/4] Kiem tra moi truong Python...

if not exist "%LMS_VENV_DIR%\Scripts\python.exe" (
    echo [ERROR] Khong tim thay:
    echo %LMS_VENV_DIR%\Scripts\python.exe
    echo.
    pause
    exit /b
)

echo [OK] Python virtual environment san sang.

REM ============================================
REM 3. KHOI DONG FASTAPI
REM ============================================

echo.
echo [3/4] Khoi dong FastAPI Backend...

start "LMS Backend" cmd /k ^
""%LMS_VENV_DIR%\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload"

echo Dang cho Backend khoi dong...
timeout /t 4 /nobreak >nul

REM ============================================
REM 4. KHOI DONG STREAMLIT
REM ============================================

echo.
echo [4/4] Khoi dong Streamlit Frontend...

start "LMS Frontend" cmd /k ^
""%LMS_VENV_DIR%\Scripts\python.exe" -m streamlit run app.py --server.port 8501 --server.headless true"

echo.
echo Dang cho Frontend khoi dong...
timeout /t 4 /nobreak >nul

REM ============================================
REM MO TRINH DUYET
REM ============================================

echo.
echo ==========================================
echo             LMS DLU DA SAN SANG
echo ==========================================
echo.
echo Backend:
echo http://127.0.0.1:8000
echo.
echo API Docs:
echo http://127.0.0.1:8000/docs
echo.
echo Frontend:
echo http://localhost:8501
echo.
echo DeepTutor se duoc Backend tu dong goi khi
echo sinh vien su dung AI Assistant.
echo.
echo ==========================================

start "" http://localhost:8501

timeout /t 3 /nobreak >nul
exit
