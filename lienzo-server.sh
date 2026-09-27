#!/usr/bin/env bash
# Arranca lienzo-server en 127.0.0.1:7321. Mac / Linux / WSL — el equivalente Unix de
# lienzo-server.cmd (que queda para Windows). Solo stdlib: no hace falta instalar nada, ni venv.
# El comando portable, sin este atajo, es:  python3 lienzo/server.py
set -e
export PYTHONIOENCODING=utf-8
cd "$(dirname "$0")"
# lienzo pide Python 3.14 (usa su sintaxis): se prefiere python3.14, y con un python3 mas viejo se
# avisa claro en vez de morir con un SyntaxError
py="$(command -v python3.14 || command -v python3 || true)"
if [ -z "$py" ] || ! "$py" -c 'import sys; sys.exit(sys.version_info < (3, 14))'; then
  echo "lienzo-server: hace falta Python 3.14 o mas nuevo (${py:-ninguno}: $("${py:-false}" --version 2>&1))" >&2
  exit 1
fi
exec "$py" lienzo/server.py "$@"
