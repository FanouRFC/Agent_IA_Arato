@echo off
rem Jeu de donnees de test du CRM (reexecutable : reinitialise les donnees du CRM)
cd /d "%~dp0CRM_AgentIA"
call "%~dp0Backend_AgentIA\venv\Scripts\activate"
python -m app.seed
pause
