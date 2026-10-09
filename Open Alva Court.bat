@echo off
rem Double-click: serves the scenes on http://127.0.0.1:7432 and opens the browser.
rem Close this window to stop the server.
cd /d "%~dp0"
node serve.mjs --open
if errorlevel 1 pause
