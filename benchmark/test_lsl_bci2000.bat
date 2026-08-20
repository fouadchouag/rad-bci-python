@echo off
REM ============================================================
REM test_lsl_bci2000.bat
REM Launch BCI2000 with LSLSource + DummySignalProcessing + DummyApplication
REM For cross-platform benchmark W1 (Reader -> Display)
REM ============================================================

REM --- ADJUST THIS PATH TO YOUR INSTALLATION ---
set BCI2000_DIR=C:\BCI2000\BCI2000 v3.6.beta.R7385\BCI2000.x64.extensions.bundled\prog
REM ---------------------------------------------

echo.
echo ===== BCI2000 LSL Test Launcher =====
echo Installation directory: %BCI2000_DIR%
echo.

REM Verify directory exists
if not exist "%BCI2000_DIR%" (
    echo [ERROR] Directory not found: %BCI2000_DIR%
    echo Please edit this .bat file and set BCI2000_DIR to your actual install path.
    pause
    exit /b 1
)

REM Verify required .exe files are present
set MISSING=0
for %%F in (Operator.exe LSLSource.exe DummySignalProcessing.exe DummyApplication.exe) do (
    if not exist "%BCI2000_DIR%\%%F" (
        echo [ERROR] Missing file: %BCI2000_DIR%\%%F
        set MISSING=1
    )
)
if %MISSING%==1 (
    echo.
    echo One or more required BCI2000 modules are missing.
    echo Did you install BCI2000Contrib.exe (not the base installer)?
    pause
    exit /b 1
)

echo All required files found. Starting BCI2000 modules...
echo.

REM Move into the BCI2000 prog directory so relative paths work
cd /d "%BCI2000_DIR%"

REM --- Launch Operator first (the orchestrator) ---
echo [1/4] Launching Operator.exe...
start "" Operator.exe

REM Give Operator 3 seconds to bind its TCP port
timeout /t 3 /nobreak > nul

REM --- Launch the three modules, pointing them to localhost Operator ---
echo [2/4] Launching LSLSource.exe...
start "" LSLSource.exe --Operator=127.0.0.1

timeout /t 1 /nobreak > nul

echo [3/4] Launching DummySignalProcessing.exe...
start "" DummySignalProcessing.exe --Operator=127.0.0.1

timeout /t 1 /nobreak > nul

echo [4/4] Launching DummyApplication.exe...
start "" DummyApplication.exe --Operator=127.0.0.1

echo.
echo All modules launched. Check the Operator window:
echo   - The three module indicators should turn GREEN
echo   - Then click "Config" -- "SetConfig" -- "Start"
echo.
echo To stop: close the Operator window (it will close the others too).
echo.
pause
