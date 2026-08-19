@echo off
cd /d "%~dp0"

if not exist ".env" (
    echo ERROR: .env file not found in this folder.
    echo Please create .env before running this ^(see .env.example^).
    pause
    exit /b 1
)

echo Building image ^(first run may take a few minutes^)...
docker build -t prompt-masking-tool . || goto :error

echo Starting container...
docker rm -f prompt-masking-tool >nul 2>&1
docker run -d --rm --name prompt-masking-tool -p 127.0.0.1:8501:8501 --env-file .env prompt-masking-tool || goto :error

echo Waiting for the app to become ready...
timeout /t 5 /nobreak >nul

start http://localhost:8501
echo.
echo Prompt Masking Tool is running.
echo To stop it, run stop-docker.bat
pause
exit /b 0

:error
echo.
echo Failed to start. See the error above.
pause
exit /b 1
