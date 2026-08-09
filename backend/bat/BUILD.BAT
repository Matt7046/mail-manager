@echo off
setlocal
call "%~dp0deploy\_load-config.bat" 2>nul
rem Dockerfile + build context live in backend\ (parent of bat\)
cd /d "%~dp0.."
set DOCKER_BUILDKIT=1
set "IMG=docker.io/matt7046/mail-manager:2.0.0"
if not "%DEPLOY_HUB_IMAGE%"=="" set "IMG=%DEPLOY_HUB_IMAGE%"
if not exist "Dockerfile" (
  echo [ERRORE] Dockerfile non trovato in:
  echo   %CD%
  exit /b 1
)
echo Building %IMG% ...
echo Context: %CD%
docker build -t %IMG% .
exit /b %errorlevel%
