@echo off
REM Vinyl Catalog v3 - start script (Windows)
setlocal
cd /d "%~dp0"
set PY=python
if not exist .venv (
  %PY% -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo Launching Vinyl Catalog on http://127.0.0.1:8501 (LAN: http://^<host-ip^>:8501) ...
python -m app.api.server
endlocal
