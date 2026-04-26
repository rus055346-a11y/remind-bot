@echo off
echo Starting Remind Bot...
start "Flask Panel" cmd /k "cd C:\remind_bot && python panel.py"
timeout /t 3 /nobreak
start "ngrok" cmd /k "cd C:\remind_bot && ngrok http --domain=latticed-versus-hamburger.ngrok-free.dev 5000"
echo Done! Panel: https://latticed-versus-hamburger.ngrok-free.dev
