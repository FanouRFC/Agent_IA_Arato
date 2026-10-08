@echo off
rem CRM (port 8001) - Swagger : http://localhost:8001/docs - utilise le MEME venv que le backend
cd /d "%~dp0CRM_AgentIA"
call "%~dp0Backend_AgentIA\venv\Scripts\activate"
python -m uvicorn app.main:app --port 8001 --reload
pause
