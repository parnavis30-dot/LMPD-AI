@echo off
title LMPD AI
cd /d "%~dp0"
echo ==========================================
echo          LMPD AI - SETUP
echo ==========================================
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher not found. Install Python 3.11 first.
  pause
  exit /b 1
)
if not exist .venv (
  echo Creating Python 3.11 environment...
  py -3.11 -m venv .venv
  if errorlevel 1 (
    echo Could not create environment. Confirm Python 3.11 is installed.
    pause
    exit /b 1
  )
)
call .venv\Scripts\activate.bat
echo Installing / checking required packages...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Dependency installation failed. Check internet connection and try again.
  pause
  exit /b 1
)
echo Starting LMPD AI...
python -m streamlit run app.py
pause
