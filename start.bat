@echo off
cd /d "%~dp0"
echo Starting Masked Prompt Chat...
echo Browser will open automatically. If not, open http://localhost:8501
echo To stop: press Ctrl+C in this window, or close this window.
echo.
".\.venv\Scripts\python.exe" -m streamlit run app.py
pause
