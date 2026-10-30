@echo off
setlocal EnableExtensions EnableDelayedExpansion
title LMS DLU - DeepTutor Launcher

set "DEMO_QUICK_LOGIN_ENABLED=true"
set "APP_ROOT=%~dp0"
cd /d "%APP_ROOT%" || goto :fail_repo
if not defined LMS_VENV_DIR set "LMS_VENV_DIR=%APP_ROOT%venv"
set "PYTHON=%LMS_VENV_DIR%\Scripts\python.exe"
set "BACKEND_URL=http://127.0.0.1:8001"
set "FRONTEND_URL=http://127.0.0.1:8502"
set "LMS_FASTAPI_URL=%BACKEND_URL%"
set "MOODLE_BASE_URL=http://127.0.0.1:8088"
if not defined LMS_DB_SERVER set "LMS_DB_SERVER=localhost"
if not defined LMS_DB_NAME set "LMS_DB_NAME=LMS_DeepTutor"
if not defined OLLAMA_BASE_URL set "OLLAMA_BASE_URL=http://127.0.0.1:11434"
if not defined OLLAMA_MODEL set "OLLAMA_MODEL=qwen2.5:3b"
if not defined LEARNING_GENERATION_PROVIDER_TIMEOUT_SECONDS set "LEARNING_GENERATION_PROVIDER_TIMEOUT_SECONDS=120"

set "MODE=%~1"
if "%MODE%"=="" (
  choice /c GO /n /m "Select provider: [G]roq or [O]llama"
  if errorlevel 2 (set "MODE=ollama") else set "MODE=groq"
)
if /I "%MODE%"=="groq" goto :groq
if /I "%MODE%"=="ollama" goto :ollama
echo [ERROR] Provider must be groq or ollama.
goto :fail

:groq
if not defined GROQ_API_KEY (
  echo [ERROR] GROQ_API_KEY is not configured for this process.
  echo Set it securely in the operator shell or Windows user environment, then rerun.
  goto :fail
)
if not defined LEARNING_GENERATION_MODEL set "LEARNING_GENERATION_MODEL=qwen/qwen3.8-27b"
if not defined DEMO_CHAT_MODEL set "DEMO_CHAT_MODEL=%LEARNING_GENERATION_MODEL%"
set "LEARNING_GENERATION_PROVIDER=groq"
set "DEMO_CHAT_PROVIDER=groq"
set "DEMO_CHAT_FALLBACK=none"
goto :preflight

:ollama
set "LEARNING_GENERATION_PROVIDER=ollama"
set "LEARNING_GENERATION_MODEL=%OLLAMA_MODEL%"
set "DEMO_CHAT_PROVIDER=ollama"
set "DEMO_CHAT_FALLBACK=none"
goto :preflight

:preflight
echo.
echo DeepTutor launcher: %LEARNING_GENERATION_PROVIDER% mode
if not exist "%PYTHON%" (echo [ERROR] Python environment not found.&goto :fail)
if not exist "%APP_ROOT%main.py" (echo [ERROR] FastAPI entrypoint not found.&goto :fail)
if not exist "%APP_ROOT%app.py" (echo [ERROR] Streamlit entrypoint not found.&goto :fail)
if not defined MOODLE_BASE_URL (echo [ERROR] MOODLE_BASE_URL is not configured.&goto :fail)
curl.exe -fsS --max-time 5 "%MOODLE_BASE_URL%/login/index.php" >nul 2>&1 || (echo [ERROR] Moodle endpoint is not reachable.&goto :fail)
echo [OK] Moodle endpoint is reachable.

for %%C in (deeptutor-moodle deeptutor-moodle-db) do (
  docker.exe inspect -f "{{.State.Running}}" %%C >nul 2>&1 || (echo [ERROR] Required Docker container %%C was not found.&goto :fail)
  for /f %%S in ('docker.exe inspect -f "{{.State.Running}}" %%C 2^>nul') do if /I not "%%S"=="true" (echo [ERROR] Required Docker container %%C is not running.&goto :fail)
)
echo [OK] Existing Moodle containers are running.
if /I not "%LMS_DB_SERVER%"=="localhost" (echo [ERROR] LMS_DB_SERVER must be localhost.&goto :fail)
if /I not "%LMS_DB_NAME%"=="LMS_DeepTutor" (echo [ERROR] LMS_DB_NAME must be LMS_DeepTutor.&goto :fail)
where sqlcmd.exe >nul 2>&1 || (echo [ERROR] sqlcmd.exe is required to verify SQL Server.&goto :fail)
sqlcmd.exe -S "%LMS_DB_SERVER%" -E -d "%LMS_DB_NAME%" -l 5 -Q "SELECT 1" >nul 2>&1 || (echo [ERROR] Approved SQL target is not reachable.&goto :fail)
echo [OK] Approved SQL Server target is reachable.

if /I "%LEARNING_GENERATION_PROVIDER%"=="ollama" (
  curl.exe -fsS --max-time 5 "%OLLAMA_BASE_URL%/api/tags" | findstr /I /C:"%OLLAMA_MODEL%" >nul || (echo [ERROR] Required Ollama model is unavailable.&goto :fail)
  echo [OK] Ollama and configured model are available.
) else (
  echo [OK] Groq key is configured. Model: %LEARNING_GENERATION_MODEL%
)

powershell.exe -NoProfile -Command "exit [int][bool](Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue)" >nul 2>&1
if errorlevel 1 (echo [ERROR] Port 8001 is already in use. Refusing to replace a process.&goto :fail)
powershell.exe -NoProfile -Command "exit [int][bool](Get-NetTCPConnection -LocalPort 8502 -State Listen -ErrorAction SilentlyContinue)" >nul 2>&1
if errorlevel 1 (echo [ERROR] Port 8502 is already in use. Refusing to replace a process.&goto :fail)

echo Starting FastAPI on 127.0.0.1:8001...
echo [INFO] Waiting for FastAPI /openapi.json. Check the FastAPI window for startup errors.
start "LMS FastAPI - 8001" /D "%APP_ROOT%" "%PYTHON%" -m uvicorn main:app --host 127.0.0.1 --port 8001
for /l %%I in (1,1,30) do (
  curl.exe -fsS --max-time 2 "%BACKEND_URL%/openapi.json" >nul 2>&1 && goto :backend_ready
  timeout /t 2 /nobreak >nul
)
echo [ERROR] FastAPI did not become ready. Check the FastAPI window for the actual error.
echo [INFO] No process was terminated. Check ports 8001 and 8502 before retrying.
goto :fail

:backend_ready
echo [OK] FastAPI is ready.
echo Starting Streamlit on 127.0.0.1:8502...
echo [INFO] Waiting for Streamlit /_stcore/health.
start "LMS Streamlit - 8502" /D "%APP_ROOT%" "%PYTHON%" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502 --server.headless true
for /l %%I in (1,1,30) do (
  curl.exe -fsS --max-time 2 "%FRONTEND_URL%/_stcore/health" >nul 2>&1 && goto :ready
  timeout /t 2 /nobreak >nul
)
echo [ERROR] Streamlit did not become ready. Check the Streamlit window for the actual error.
echo [INFO] No process was terminated. Check ports 8001 and 8502 before retrying.
goto :fail

:ready
echo [OK] Streamlit is ready: %FRONTEND_URL%
echo [INFO] Opening DeepTutor...
start "" "%FRONTEND_URL%"
endlocal
exit /b 0

:fail_repo
echo [ERROR] Cannot resolve the launcher directory.
:fail
echo Startup stopped without changing Docker resources or terminating processes.
pause
endlocal
exit /b 1
