@echo off
rem Serveur SMTP de test (affiche les e-mails dans la console) - aucun paquet supplementaire a installer
cd /d "%~dp0Backend_AgentIA"
call venv\Scripts\activate
python "%~dp0scripts\smtp_debug.py"
pause
