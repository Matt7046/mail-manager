@echo off
setlocal
call "%~dp0BUILD.BAT"
if errorlevel 1 exit /b %errorlevel%
call "%~dp0PUSH.BAT"
exit /b %errorlevel%
