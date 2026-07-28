@echo off
rem SSH helper: legge il comando da DEPLOY_REMOTE_CMD oppure da %1.
setlocal EnableDelayedExpansion
call "%~dp0_load-config.bat"
if errorlevel 1 exit /b 1

set "REMOTE_CMD="
if not "%~1"=="" set "REMOTE_CMD=%~1"
if "!REMOTE_CMD!"=="" if defined DEPLOY_REMOTE_CMD set "REMOTE_CMD=!DEPLOY_REMOTE_CMD!"
if "!REMOTE_CMD!"=="" (
  echo Uso:
  echo   set DEPLOY_REMOTE_CMD=comando remoto
  echo   call _ssh.bat
  exit /b 1
)

set "SSH_TARGET=%DEPLOY_USER%@%DEPLOY_HOST%"

echo.
echo === SSH %SSH_TARGET% ===
echo Cmd: !REMOTE_CMD!
echo.

if defined DEPLOY_SSH_KEY (
  ssh -i "%DEPLOY_SSH_KEY%" -o StrictHostKeyChecking=accept-new !SSH_TARGET! "!REMOTE_CMD!"
) else (
  ssh -o StrictHostKeyChecking=accept-new !SSH_TARGET! "!REMOTE_CMD!"
)
exit /b %errorlevel%
