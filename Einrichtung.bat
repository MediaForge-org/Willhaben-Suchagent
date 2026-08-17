@echo off
setlocal enabledelayedexpansion
rem Einmalige Einrichtung des Willhaben-Suchagenten unter Windows.
rem Kann von einem beliebigen Ort aus ausgefuehrt werden (auch nach
rem Verschieben des kompletten Programmordners) und darf beliebig oft
rem erneut gestartet werden, ohne bestehende Daten zu ueberschreiben.

set "SCRIPT_DIR=%~dp0"

echo Willhaben-Suchagent - Einrichtung
echo Programmordner: %SCRIPT_DIR%
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    set "SYSTEM_PYTHON=py -3"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "SYSTEM_PYTHON=python"
    ) else (
        echo Fehler: Es wurde kein Python gefunden.
        echo Bitte installiere Python 3.12 oder neuer von https://python.org und starte die Einrichtung erneut.
        pause
        exit /b 1
    )
)

echo Bereite die Laufzeitumgebung vor...
%SYSTEM_PYTHON% "%SCRIPT_DIR%deployment\bootstrap.py"
if errorlevel 1 (
    echo.
    echo Die Einrichtung ist fehlgeschlagen. Siehe Meldung oben.
    pause
    exit /b 1
)

set "VENV_PYTHON=%SCRIPT_DIR%.venv\Scripts\python.exe"

echo.
echo Richte Firefox Native Messaging ein...
"%VENV_PYTHON%" -m agent.app.native_messaging.setup_windows install --project-root "%SCRIPT_DIR%" --python "%VENV_PYTHON%"
if errorlevel 1 (
    echo.
    echo Native Messaging konnte nicht eingerichtet werden. Siehe Meldung oben.
    pause
    exit /b 1
)

echo.
echo Einrichtung abgeschlossen.
echo Starte den Willhaben-Suchagenten ab jetzt ueber "Willhaben-Suchagent starten.bat".
echo Der Agent laeuft dann in einem Fenster, das waehrend der Nutzung offen bleiben muss.
echo Oeffne danach Firefox und die Erweiterung, um loszulegen.
pause
