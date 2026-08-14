#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_root="$(cd -- "${script_directory}/../.." && pwd -P)"

if [[ -x "${project_root}/.venv/bin/python" ]]; then
  python_executable="${project_root}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  python_executable="$(command -v python3)"
else
  echo "Fehler: Weder .venv/bin/python noch python3 wurde gefunden." >&2
  exit 1
fi

cd -- "${project_root}"
exec "${python_executable}" \
  -m agent.app.native_messaging.setup_linux \
  install \
  --project-root "${project_root}" \
  --python "${python_executable}"
