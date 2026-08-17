#!/usr/bin/env bash
# Manueller Start des Willhaben-Suchagenten (Release-Paket, Linux).
# Nur noetig, wenn kein Autostart eingerichtet wurde oder der Agent gerade
# nicht laeuft. Funktioniert unabhaengig davon, wohin der Programmordner
# verschoben wurde.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
AGENT_BIN="${SCRIPT_DIR}/runtime/willhaben-suchagent"

if [[ ! -x "${AGENT_BIN}" ]]; then
  echo "Die Laufzeitumgebung wurde nicht gefunden."
  echo "Bitte das Release-Paket erneut entpacken."
  exit 1
fi

echo "Willhaben-Suchagent wird gestartet..."
echo "Dieses Fenster gehoert zum Willhaben-Suchagenten - bitte offen lassen."
echo "Zum Beenden: Strg+C oder Fenster schliessen."
echo

cd -- "${SCRIPT_DIR}"
exec "${AGENT_BIN}"
