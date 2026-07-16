@echo off
cd /d "%~dp0"
echo Starting Meeting Transcriber...
echo Open http://localhost:8756 in your browser (opening automatically in 4s)
start "" /min cmd /c "timeout /t 4 >nul & start http://localhost:8756"
".venv\Scripts\python.exe" server.py
pause
