@echo off
REM Run the app using the project venv (Windows).
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    py -m venv .venv
  )
)

echo Upgrading pip...
.venv\Scripts\python.exe -m pip install --upgrade pip

echo Installing dependencies from requirements.txt...
.venv\Scripts\pip.exe install -r requirements.txt

echo.
echo Starting app...
.venv\Scripts\python.exe app.py
