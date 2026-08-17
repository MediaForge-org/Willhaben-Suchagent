#!/usr/bin/env bash
# Manueller Start des Willhaben-Suchagenten (z. B. wenn kein systemd-Autostart
# eingerichtet wurde). Funktioniert unabhängig davon, wohin der Programmordner
# verschoben wurde, und benötigt kein vorheriges "source .venv/bin/activate".
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
AGENT_BIN="${SCRIPT_DIR}/.venv/bin/willhaben-suchagent"

if [[ ! -x "${AGENT_BIN}" ]]; then
  echo "Die Laufzeitumgebung ist noch nicht eingerichtet."
  echo "Führe zuerst 'Einrichtung.sh' aus."
  exit 1
fi

echo "Willhaben-Suchagent wird gestartet..."
echo "Dieses Fenster gehört zum Willhaben-Suchagenten – bitte offen lassen."
echo "Zum Beenden: Strg+C oder Fenster schließen."
echo

cd -- "${SCRIPT_DIR}"
exec "${AGENT_BIN}"
