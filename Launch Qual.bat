@echo off
cd /d "%~dp0"
if exist "dist\2.3\Qual\Qual.exe" (
  start "" "dist\2.3\Qual\Qual.exe"
  exit /b
)
if exist "dist\2.2\Qual\Qual.exe" (
  start "" "dist\2.2\Qual\Qual.exe"
  exit /b
)
if exist "dist\2.1\Qual\Qual.exe" (
  start "" "dist\2.1\Qual\Qual.exe"
  exit /b
)
if exist "dist\Qual\Qual.exe" (
  start "" "dist\Qual\Qual.exe"
  exit /b
)
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "app.py"
  exit /b
)
echo Run the setup instructions in README.md first.
pause
