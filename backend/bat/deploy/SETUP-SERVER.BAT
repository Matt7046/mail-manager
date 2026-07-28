@echo off
rem Copia file compose/nginx-app/cert sul VPS (una tantum).
rem Poi: GoDaddy A record + certbot + recreate nginx AM (mount web).
setlocal EnableDelayedExpansion
call "%~dp0_load-config.bat"
if errorlevel 1 exit /b 1

set "SSH_TARGET=%DEPLOY_USER%@%DEPLOY_HOST%"
echo.
echo === SETUP SERVER ^(GoDaddy / nginx AM^) -^> %SSH_TARGET% ===

set "DEPLOY_REMOTE_CMD=mkdir -p %DEPLOY_API_PATH%/certificate %DEPLOY_WEB_PATH% %DEPLOY_NGINX_APPS%"
call "%~dp0_ssh.bat"
if errorlevel 1 exit /b 1

if defined DEPLOY_SSH_KEY (
  set "SCP=scp -i %DEPLOY_SSH_KEY% -o StrictHostKeyChecking=accept-new"
) else (
  set "SCP=scp -o StrictHostKeyChecking=accept-new"
)

%SCP% "%BACKEND_DIR%\docker-compose.yml" "%SSH_TARGET%:%DEPLOY_API_PATH%/docker-compose.yml"
if errorlevel 1 exit /b 1
%SCP% "%BACKEND_DIR%\nginx\mail.colorsdev.tech.conf" "%SSH_TARGET%:%DEPLOY_NGINX_APPS%/mail.colorsdev.tech.conf"
if errorlevel 1 exit /b 1
if exist "%BACKEND_DIR%\.env" (
  %SCP% "%BACKEND_DIR%\.env" "%SSH_TARGET%:%DEPLOY_API_PATH%/.env"
  if errorlevel 1 exit /b 1
) else (
  echo [WARN] Manca backend\.env — crealo sul server ^(MONGO_URL, SERVER_SECRET, DB_NAME=mail_manager^)
)
if exist "%BACKEND_DIR%\certificate\client.pem" (
  %SCP% "%BACKEND_DIR%\certificate\client.pem" "%BACKEND_DIR%\certificate\client-key.pem" "%SSH_TARGET%:%DEPLOY_API_PATH%/certificate/"
  if errorlevel 1 exit /b 1
)

echo.
echo [OK] File sul server.
echo.
echo Prossimi passi UNA TANTUM:
echo   1^) GoDaddy: A record  mail  -^> IP VPS ^(come password.^)
echo   2^) Sul VPS: certbot certonly --webroot -w /var/www/certbot -d mail.colorsdev.tech
echo      ^(oppure: certbot --nginx -d mail.colorsdev.tech^)
echo   3^) Aggiorna compose AM con mount /root/mail-manager/web:/var/www/mail-manager-web
echo      poi: cd /root/app/backend ; docker compose up -d --force-recreate nginx
echo   4^) DEPLOY-ALL.BAT
exit /b 0
