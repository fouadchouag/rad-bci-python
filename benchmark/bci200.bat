@echo off
cd /d C:\BCI2000\BCI2000 v3.6.beta.R7385\BCI2000.x64.extensions.bundled\prog

start "" Operator.exe
timeout /t 2 /nobreak > nul

start "" LSLSource.exe --Operator=127.0.0.1
start "" DummySignalProcessing.exe --Operator=127.0.0.1
start "" DummyApplication.exe --Operator=127.0.0.1