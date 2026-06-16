@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE="

where python >nul 2>nul
if %ERRORLEVEL%==0 set PYTHON_EXE=python

if not defined PYTHON_EXE (
  where py >nul 2>nul
  if %ERRORLEVEL%==0 set PYTHON_EXE=py
)

if not defined PYTHON_EXE (
  if exist "C:\Users\n.duman\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
    set "PYTHON_EXE=C:\Users\n.duman\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
  )
)

if not defined PYTHON_EXE (
  echo Python bulunamadi.
  echo Python'u kurarken "Add python.exe to PATH" secenegini isaretleyin.
  pause
  exit /b 1
)

echo Paketler kontrol ediliyor...
%PYTHON_EXE% -m ensurepip --upgrade
%PYTHON_EXE% -m pip install --upgrade pip
%PYTHON_EXE% -m pip install -r requirements.txt

start "" http://127.0.0.1:7860
echo Web arayuzu aciliyor: http://127.0.0.1:7860
%PYTHON_EXE% app.py
pause
