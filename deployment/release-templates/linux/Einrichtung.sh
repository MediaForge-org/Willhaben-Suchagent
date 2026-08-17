#!/usr/bin/env bash
# Einmalige Einrichtung des Willhaben-Suchagenten (Release-Paket, Linux).
# Benoetigt kein Python, kein pip und kein venv - die Laufzeitumgebung liegt
# bereits fertig gebaut in runtime/. Kann von einem beliebigen Ort aus
# ausgefuehrt werden (auch nach Verschieben des kompletten Programmordners)
# und darf beliebig oft erneut gestartet werden, ohne bestehende Daten,
# Suchen, Vorlagen oder Einstellungen zu ueberschreiben.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SETUP_BIN="${SCRIPT_DIR}/runtime/willhaben-suchagent-setup"

echo "Willhaben-Suchagent - Einrichtung"
echo "Programmordner: ${SCRIPT_DIR}"
echo

if [[ ! -x "${SETUP_BIN}" ]]; then
  echo "Fehler: ${SETUP_BIN} wurde nicht gefunden." >&2
  echo "Bitte das Release-Paket erneut entpacken." >&2
  exit 1
fi

echo "Richte Firefox Native Messaging und den automatischen Start ein..."
"${SETUP_BIN}" install-linux --project-root "${SCRIPT_DIR}"

echo
echo "Einrichtung abgeschlossen."
echo "Naechste Schritte:"
echo "  1. Firefox oeffnen und die Erweiterung aus extension/willhaben-suchagent.xpi installieren"
echo "     (siehe USER_GUIDE.md)."
echo "  2. Erweiterungssymbol anklicken und eine Suche einrichten."
