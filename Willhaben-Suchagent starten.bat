@echo off
rem Startet den Willhaben-Suchagenten unter Windows. Funktioniert unabhaengig
rem davon, wohin der Programmordner verschoben wurde. Dieses Fenster gehoert
rem zum Willhaben-Suchagenten und muss waehrend der Nutzung offen bleiben.

set "SCRIPT_DIR=%~dp0"
set "AGENT_BIN=%SCRIPT_DIR%.venv\Scripts\willhaben-suchagent.exe"

if not exist "%AGENT_BIN%" (
    echo Die Laufzeitumgebung ist noch nicht eingerichtet.
    echo Fuehre zuerst "Einrichtung.bat" aus.
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

rem Der Agent kann sich auch ohne Fehlercode sofort wieder beenden, z. B. wenn
rem bereits eine Instanz laeuft (siehe Meldung oben). Fenster offen halten,
rem damit diese Meldung nicht sofort wieder verschwindet.
echo.
echo Der Willhaben-Suchagent wurde beendet.
pause
