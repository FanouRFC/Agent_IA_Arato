@echo off
rem Serveur SMTP de test (affiche les e-mails dans la console) - necessite requirements-dev.txt
cd /d "%~dp0Backend_AgentIA"
call venv\Scripts\activate
python "%~dp0scripts\smtp_debug.py"
pause
