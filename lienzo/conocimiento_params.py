"""Parámetros compartidos por las APIs de conocimiento, aprendizaje y veredictos."""

from conocimiento import Rechazo


def _q(query: dict, nombre: str, defecto=None):
    value = query.get(nombre)
    if isinstance(value, list):
        value = value[0] if value else None
    return value if value not in (None, "") else defecto


def _entero(value, nombre: str, defecto: int) -> int:
    if value is None:
        return defecto
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise Rechazo(f"{nombre} debe ser un entero") from error
