#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'LANGKAS benötigt Python 3.11 oder neuer. Python fehlt im PATH.' >&2; exit 1
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else "Python 3.11 oder neuer erforderlich.")'
PORT="${LANGKAS_PORT:-8877}"
python3 -m langcas doctor
echo
echo 'Lokaler Zugangsschlüssel – nur in deinem Browser auf diesem Rechner verwenden:'
python3 -m langcas token
echo
exec python3 -m langcas serve --port "$PORT" --open
