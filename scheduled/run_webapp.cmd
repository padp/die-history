@echo off
rem Serve the Die History web UI. Pass 0.0.0.0 to reach it from other
rem machines on the plant network; defaults to this machine only.
set HOST=%1
if "%HOST%"=="" set HOST=127.0.0.1
cd /d "%~dp0..\api"
python app.py --host %HOST% --port 5058
