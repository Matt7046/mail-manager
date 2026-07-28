@echo off
setlocal
call "%~dp0..\deploy\_load-config.bat" 2>nul
set "IMG=docker.io/matt7046/mail-manager:2.0.0"
if not "%DEPLOY_HUB_IMAGE%"=="" set "IMG=%DEPLOY_HUB_IMAGE%"
echo Pushing %IMG% ...
docker push %IMG%
exit /b %errorlevel%
