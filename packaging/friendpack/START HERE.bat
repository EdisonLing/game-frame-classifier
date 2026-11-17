@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist "runtime\python.exe" (
  echo This folder is incomplete. Right-click the zip, choose "Extract All", then run START HERE.bat from the extracted folder.
  pause
  exit /b 1
)
"runtime\python.exe" -B -X utf8 "app\gfc_friendpack.py" %*
echo.
pause
