@echo off
echo ========================================
echo   Panda Quant Platform - Start Backend
echo ========================================
cd /d "%~dp0backend"
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)
call venv\Scripts\activate
py -3.11 -m pip install -r requirements.txt -q
if not exist .env copy .env.example .env
if not exist data mkdir data
if not exist state mkdir state
if not exist logs mkdir logs
echo Starting backend on port 8000 + webhook on 6010...
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
