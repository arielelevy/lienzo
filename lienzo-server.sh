#!/usr/bin/env bash
# Arranca lienzo-server en 127.0.0.1:7321. Mac / Linux / WSL — el equivalente Unix de
# lienzo-server.cmd (que queda para Windows). Solo stdlib: no hace falta instalar nada, ni venv.
# El comando portable, sin este atajo, es:  python3 lienzo/server.py
set -e
export PYTHONIOENCODING=utf-8
cd "$(dirname "$0")"
exec python3 lienzo/server.py "$@"
