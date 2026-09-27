#!/usr/bin/env bash
# lienzo new: arranca un agente ADENTRO de tmux, para que el board de lienzo lo vea y le pueda
# escribir. En Unix (Mac/Linux/WSL) un agente que corre suelto se puede leer pero no escribir (un
# PTY es de quien lo creo); tmux es lo que da ese acceso. Este helper esconde tmux en un comando.
#
#   ./lienzo-new.sh                 # claude, nombre de sesion automatico
#   ./lienzo-new.sh codex           # codex
#   ./lienzo-new.sh claude mirepo   # claude, sesion "mirepo"
#
# Para salir sin cerrarlo: Ctrl+b y despues d. Para volver: tmux attach -t <nombre>.
set -e

agent="${1:-claude}"
name="${2:-${agent}-$(date +%H%M%S)}"

if ! command -v tmux >/dev/null 2>&1; then
  echo "lienzo new: falta tmux (instalalo: apt install tmux / brew install tmux)" >&2
  exit 1
fi
if ! command -v "$agent" >/dev/null 2>&1; then
  echo "lienzo new: no encuentro '$agent' en el PATH" >&2
  exit 1
fi

# ya adentro de tmux: una ventana nueva (no se puede anidar una sesion)
if [ -n "$TMUX" ]; then
  exec tmux new-window -n "$name" "$agent"
fi
exec tmux new-session -s "$name" "$agent"
