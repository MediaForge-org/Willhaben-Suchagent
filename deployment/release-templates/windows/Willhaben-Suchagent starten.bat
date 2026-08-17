@echo off
rem Startet den Willhaben-Suchagenten (Release-Paket, Windows). Funktioniert
rem unabhaengig davon, wohin der Programmordner verschoben wurde. Dieses
rem Fenster gehoert zum Willhaben-Suchagenten und muss waehrend der Nutzung
rem offen bleiben.

set "SCRIPT_DIR=%~dp0"
set "AGENT_BIN=%SCRIPT_DIR%runtime\willhaben-suchagent.exe"

if not exist "%AGENT_BIN%" (
    echo Die Laufzeitumgebung wurde nicht gefunden.
    echo Bitte das Release-Paket erneut entpacken.
    pause
    exit /b 1
)

echo Willhaben-Suchagent wird gestartet...
echo Dieses Fenster gehoert zum Willhaben-Suchagenten - bitte offen lassen.
echo Zum Beenden: dieses Fenster schliessen oder Strg+C.
echo.

cd /d "%SCRIPT_DIR%"
"%AGENT_BIN%"
if errorlevel 1 (
    echo.
    echo Der Willhaben-Suchagent wurde mit einem Fehler beendet. Siehe Meldung oben.
    pause
    exit /b 1
)

echo.
echo Der Willhaben-Suchagent wurde beendet.
pause
