# Notas del frente C (fuera de mis archivos)

Registro histórico de esta ronda. Los resultados corresponden al código revisado en ese momento.

- `tests/test_server.py::test_coordinadora_una_por_repo` fallo en mi ultima corrida completa
  (`python -m pytest tests -q`), comparando `session_id` en un orden que no coincidio. Es del area
  de `sessions.py`/`rules.py` (frente B, que sigue trabajando en el mismo arbol). No lo toque ni
  lo arregle.
- (Resuelto, sin accion) `tests/test_home.py` del frente A fallaba 7/7 en mi primera corrida con
  `OSError: [WinError 50]`; en la corrida posterior a los ajustes de verificacion ya pasa entero.
- (Aclarado por la coordinadora, sin accion) `lienzo/auth.py` usa `except OSError, ValueError:`
  (sin parentesis): es sintaxis valida desde Python 3.14, PEP 758. No es un bug.
