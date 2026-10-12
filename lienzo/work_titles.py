"""Formato único proyecto | tarea, sin duplicar prefijos anteriores."""

from __future__ import annotations

import re

from tarjeta_texto import strip_control

_SEPARATOR = re.compile(r"\s+(?:\||-)\s+")
_ROLE = re.compile(r"^(?:encargo\b|coordinador[ae]?\b)", re.IGNORECASE)


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
        if len(parts) == 2 and parts[0].casefold() == project.casefold():
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
    return f"{label.lower()} | {task or 'sesión'}"
