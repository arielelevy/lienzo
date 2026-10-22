"""Formato único proyecto | tarea, sin duplicar prefijos anteriores."""

from __future__ import annotations

import re

from tarjeta_texto import strip_control

_SEPARATOR = re.compile(r"\s+(?:\||-)\s+")
_ROLE = re.compile(r"^(?:encargo\b|coordinador[ae]?\b)", re.IGNORECASE)
# un nombre de carpeta largo se corta al medio con «…» (pedido de Ariel, 2026-10-22): el principio y
# el final son lo que distingue «cliente-proyecto-…-2026» de su vecino
MAX_PROYECTO = 24


def corto_medio(texto: str, maximo: int = MAX_PROYECTO) -> str:
    if len(texto) <= maximo:
        return texto
    cabeza = (maximo - 1) // 2
    return texto[:cabeza] + "…" + texto[-(maximo - 1 - cabeza) :]


def project_title(card: dict) -> str:
    title = strip_control(str(card.get("title") or "")).strip()
    project = strip_control(str(card.get("repo") or "")).strip()
    if not project:
        return title
    label = project
    task = title
    # Reconocer primero el proyecto: tareas como "encargo A - UI" no son prefijos.
    while task:
        parts = _SEPARATOR.split(task, maxsplit=1)
        if len(parts) == 2 and parts[0].casefold() in (project.casefold(), corto_medio(project).casefold()):
            label, task = parts
            continue
        if len(parts) == 2 and not _ROLE.match(parts[0]) and _ROLE.match(parts[1]):
            label, task = parts  # alias explícito: chesstudia aunque la carpeta sea chess
        break
    # Admitir el formato invertido previo "tarea | proyecto".
    backwards = task.rsplit(" | ", 1)
    if len(backwards) == 2 and backwards[1].casefold() == project.casefold():
        task = backwards[0]
    if task.casefold() == project.casefold():
        task = ""
    return f"{corto_medio(label).lower()} | {task or 'sesión'}"
