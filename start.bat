@echo off
rem One-click start for the web page (Windows). Double-click this file.
rem It starts Docker Desktop and the database if they are not running, then opens
rem http://localhost:8501 in your browser. Close this window to stop the app.

setlocal
cd /d "%~dp0"
title Regulatory RAG

where uv >nul 2>nul
if errorlevel 1 goto no_uv
if not exist .env goto no_env

docker info >nul 2>nul
if not errorlevel 1 goto docker_ready
if not exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" goto no_docker
echo Starting Docker Desktop. This can take a minute...
start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
set /a tries=0

:wait_docker
timeout /t 5 /nobreak >nul
docker info >nul 2>nul
if not errorlevel 1 goto docker_ready
set /a tries+=1
if %tries% lss 36 goto wait_docker
echo Docker did not start within 3 minutes.
echo Open Docker Desktop, wait for "Engine running", then double-click this file again.
goto fail

:docker_ready
echo Starting the database...
docker compose up -d
if errorlevel 1 goto fail

echo.
echo Opening http://localhost:8501 - keep this window open while you use the app.
echo.
rem 127.0.0.1 keeps the page on this computer only (each question uses your AWS credits).
uv run streamlit run src/regrag/ui/app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
goto end

:no_uv
echo uv is not installed. See "Setup" in README.md.
goto fail

:no_env
echo The .env file is missing. Copy .env.example to .env and fill it in (see README.md).
goto fail

:no_docker
echo Docker Desktop is not installed. Install it, then double-click this file again.
goto fail

:fail
echo.
pause
exit /b 1

:end
endlocal
