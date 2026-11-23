@echo off
rem Reinitialise la base de l APPLICATION (tables + trigger). A lancer apres une mise a jour du modele de donnees.
cd /d "%~dp0Backend_AgentIA"
call venv\Scripts\activate
python -m app.reset
pause
