#!/usr/bin/env bash
# Einmalige Einrichtung des Willhaben-Suchagenten unter Linux.
# Kann von einem beliebigen Ort aus ausgeführt werden (auch nach Verschieben
# des kompletten Programmordners) und darf beliebig oft erneut gestartet
# werden, ohne bestehende Daten, Suchen, Vorlagen oder Einstellungen zu
# überschreiben.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

echo "Willhaben-Suchagent – Einrichtung"
echo "Programmordner: ${SCRIPT_DIR}"
echo

if command -v python3 >/dev/null 2>&1; then
  SYSTEM_PYTHON="$(command -v python3)"
else
  echo "Fehler: Es wurde kein 'python3' gefunden." >&2
  echo "Bitte installiere Python 3.12 oder neuer und starte die Einrichtung erneut." >&2
  exit 1
fi

echo "Bereite die Laufzeitumgebung vor..."
"${SYSTEM_PYTHON}" "${SCRIPT_DIR}/deployment/bootstrap.py"

VENV_PYTHON="${SCRIPT_DIR}/.venv/bin/python"

echo
echo "Richte Firefox Native Messaging ein..."
"${SCRIPT_DIR}/deployment/native-messaging/install-firefox-linux.sh"

echo
echo "Richte den automatischen Start beim Anmelden ein (systemd --user, kein sudo)..."
"${VENV_PYTHON}" -m agent.app.deployment.linux_setup install \
  --project-root "${SCRIPT_DIR}" \
  --python "${VENV_PYTHON}"

echo
echo "Einrichtung abgeschlossen."
echo "Der Willhaben-Suchagent läuft ab jetzt automatisch im Hintergrund,"
echo "auch nachdem Firefox geschlossen wurde, und startet nach einem Neustart"
echo "automatisch neu. Öffne Firefox und die Erweiterung, um loszulegen."
