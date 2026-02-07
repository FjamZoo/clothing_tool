@echo off
cd /d "%~dp0gui"

:: Install deps if needed
if not exist "node_modules" (
    echo Installing dependencies...
    call npm install
)

:: Build if needed
if not exist "dist\index.html" (
    echo Building UI...
    call npx vite build
)

:: Launch
start "" npx electron .
