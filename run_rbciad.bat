@echo off
setlocal ENABLEDELAYEDEXPANSION

set "APP=rbciad"
rem Change version by setting RB_VERSION env var before launching (optional)
if "%RB_VERSION%"=="" ( set "VERSION=1.10.0" ) else ( set "VERSION=%RB_VERSION%" )

set "HERE=%~dp0"
set "VENV=%HERE%.venv"

echo [RBciAD] Using version: %VERSION%

if not exist "%VENV%\Scripts\python.exe" (
  echo [RBciAD] Creating virtual environment in .venv ...
  py -3 -m venv "%VENV%" || ( echo [RBciAD][ERROR] Failed to create venv & exit /b 1 )
)

call "%VENV%\Scripts\activate.bat"

echo [RBciAD] Upgrading pip...
python -m pip install --upgrade pip >nul

echo [RBciAD] Installing %APP%==%VERSION% from TestPyPI...
python -m pip install -i https://test.pypi.org/simple --extra-index-url https://pypi.org/simple %APP%==%VERSION% || (
  echo [RBciAD][ERROR] Install failed & exit /b 1
)

where %APP% >nul 2>&1
if %ERRORLEVEL%==0 (
  echo [RBciAD] Launching: %APP% %*
  %APP% %*
) else (
  echo [RBciAD] Launching via module: python -m %APP% %*
  python -m %APP% %*
)

endlocal
