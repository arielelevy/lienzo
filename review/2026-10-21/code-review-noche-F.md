# Code review noche F (2026-10-21): limpieza de código muerto y escrituras atómicas

Alcance: delta propio, lotes 1 y 2 del inventario (`.temp/resultados/noche-F/inventario.md`).
Skill `code-review` nivel low, una pasada por lote, en un fork de sólo lectura.

## Lote 1: código muerto y constante del ping SSE

- `lienzo/rondas.py`: se borra `turnos_de`, sin llamadores en `lienzo/`, `web/`, `tests/`, `install.py`, `skills/`, `ops/` ni `docs/`.
- `lienzo/aprendizaje.py`: se borra `ESTADOS_LECCION`, sin usos.
- `lienzo/server.py`: `_stream_sse` usa `federation.SSE_PING_S` (15.0) en vez del `15` literal. La constante
  existía para eso (`SSE_READ_TIMEOUT_S = 35` depende de ella) y nadie la usaba.

Hallazgos: ninguno. El revisor no verificó tres cosas, y las verifiqué a mano:

- `server.py:52` hace `import federation`.
- `SSE_PING_S == 15.0`.
- Los dos nombres borrados no tienen llamadores.

## Lote 2: escrituras atómicas por `atomico.py`

- `server._guardar_config_pendiente`: el `.tmp` tenía un nombre fijo y no reintentaba. Ahora usa `state.atomic_write`.
- `agent_improvements.configure`: hacía `mkstemp` + `os.replace` a mano. Ahora usa `state.atomic_write`. Se quitan
  los imports `os` y `tempfile`, que quedaron sin uso.
- Pruebas de guardia nuevas, una por función. Dan rojo con HEAD y verde con el cambio.

Hallazgos: ninguno.

Diferencia revisada aparte: si la escritura misma del `.tmp` falla, `atomico` no lo borra (sí lo hace
si falla el reemplazo). Antes, en `agent_improvements`, un `finally` lo borraba siempre. Es el mismo
comportamiento que el resto de los llamadores de `atomico` y no se corrige acá.

## Ruff

`ruff check` y `ruff format --check` corrieron sobre las seis rutas del delta. Quedaron limpias, salvo los dos imports sin uso, que corrigió `--fix`.

## Límites

- Revisión de nivel low.
- Sin mutación ni suite global.
- El runner escala porque no hay baseline aprobado.
