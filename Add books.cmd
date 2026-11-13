@echo off
rem Shelve whatever is in inbox\ and rebuild the Shelf.
cd /d "%~dp0"
python tools\shelve.py
echo.
pause
