@echo off
setlocal enabledelayedexpansion
rem Einmalige Einrichtung des Willhaben-Suchagenten (Release-Paket, Windows).
rem Benoetigt kein Python - die Laufzeitumgebung liegt bereits fertig
rem gebaut in runtime\. Kann von einem beliebigen Ort aus ausgefuehrt werden
rem (auch nach Verschieben des kompletten Programmordners) und darf beliebig
rem oft erneut gestartet werden, ohne bestehende Daten zu ueberschreiben.

set "SCRIPT_DIR=%~dp0"
set "SETUP_BIN=%SCRIPT_DIR%runtime\willhaben-suchagent-setup.exe"

echo Willhaben-Suchagent - Einrichtung
echo Programmordner: %SCRIPT_DIR%
echo.

if not exist "%SETUP_BIN%" (
    echo Fehler: %SETUP_BIN% wurde nicht gefunden.
    echo Bitte das Release-Paket erneut entpacken.
    pause
    exit /b 1
)

echo Richte Firefox Native Messaging ein...
"%SETUP_BIN%" install-windows --project-root "%SCRIPT_DIR%"
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
echo Installiere danach die Erweiterung aus extension\willhaben-suchagent.xpi (siehe USER_GUIDE.md)
echo und oeffne Firefox, um loszulegen.
pause
