@echo off
rem Backend de l'application (port 8000) - Swagger : http://localhost:8000/docs
cd /d "%~dp0Backend_AgentIA"
call venv\Scripts\activate
python -m uvicorn app.main:app --port 8000 --reload
pause
