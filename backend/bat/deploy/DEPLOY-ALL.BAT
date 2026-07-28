@echo off
rem Deploy completo Mail Manager: API Docker + web statico.
setlocal
call "%~dp0DEPLOY-API.BAT"
if errorlevel 1 exit /b 1
call "%~dp0DEPLOY-WEB.BAT"
exit /b %errorlevel%
