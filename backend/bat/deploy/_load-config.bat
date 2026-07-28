@echo off
rem Carica config.bat se presente, altrimenti example.
if exist "%~dp0config.bat" (
  call "%~dp0config.bat"
) else (
  echo [WARN] Manca deploy\config.bat — uso config.bat.example
  if exist "%~dp0config.bat.example" call "%~dp0config.bat.example"
)

if "%DEPLOY_HOST%"=="" set "DEPLOY_HOST=173.212.220.20"
if "%DEPLOY_USER%"=="" set "DEPLOY_USER=root"
if "%DEPLOY_API_PATH%"=="" set "DEPLOY_API_PATH=/root/mail-manager/backend"
if "%DEPLOY_COMPOSE_FILE%"=="" set "DEPLOY_COMPOSE_FILE=docker-compose.yml"
if "%DEPLOY_COMPOSE_NETWORK%"=="" set "DEPLOY_COMPOSE_NETWORK=backend_app-network"
if "%DEPLOY_WEB_PATH%"=="" set "DEPLOY_WEB_PATH=/root/mail-manager/web"
if "%DEPLOY_NGINX_CONTAINER%"=="" set "DEPLOY_NGINX_CONTAINER=nginx"
if "%DEPLOY_HUB_IMAGE%"=="" set "DEPLOY_HUB_IMAGE=docker.io/matt7046/mail-manager:2.0.0"
if "%DEPLOY_NGINX_APPS%"=="" set "DEPLOY_NGINX_APPS=/root/nginx-apps"

set "BACKEND_DIR=%~dp0..\.."
for %%I in ("%BACKEND_DIR%") do set "BACKEND_DIR=%%~fI"
set "REPO_ROOT=%BACKEND_DIR%\.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
set "FRONTEND_DIR=%REPO_ROOT%\frontend"

if not exist "%BACKEND_DIR%\docker-compose.yml" (
  echo [ERRORE] Non trovo docker-compose.yml in:
  echo   %BACKEND_DIR%
  exit /b 1
)
if not exist "%FRONTEND_DIR%\package.json" (
  echo [ERRORE] Non trovo frontend in:
  echo   %FRONTEND_DIR%
  exit /b 1
)
