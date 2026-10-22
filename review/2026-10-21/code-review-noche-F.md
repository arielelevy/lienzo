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

## Lote 4: funciones sin uso en producción, con sus pruebas (OK de la coordinadora)

- Se borran `tmux.list_panes_todas`, `tmux.find_agent_panes`, `aprendizaje.por_cuestionar` y `consulta.de_tarjeta`. Antes se buscaron llamadores en `lienzo/`, `web/`, `tests/`, `skills/`, `ops/`, `docs/` e `install.py`: sólo los usaban sus propias pruebas.
- Pruebas que se ajustan:
  - Se borran las 4 de `list_panes_todas` en `test_tmux_distros.py`.
  - Se quita una línea de `test_consulta.py`.
  - En `test_aprendizaje.py` sale la medición de `por_cuestionar`; quedan `cuestionar`, `recurrencia` y `parecidos`.
  - `test_cinco_D_memoria.py` prueba ahora la reutilización de `_grupo` con `cuestionar` (2 llamadas) y la relectura tras retirar un vínculo con `reglas_cuestionadas` (1 llamada, 2 recurrencias).
  - En `tmux_smoke.py`, el pane se descubre con `display-message` + `list_panes`.
- Se corrige el comentario de `backend._tmux_sweep`, que nombraba `list_panes_todas`.

Hallazgos:
1. En `test_cinco_D_memoria.py`, `all(...)` sobre una lista vacía pasaba sin mirar nada. **Corregido**: ahora pide también `len(releidas) == 3`.
2. Posibles imports `threading`/`logging` sin uso en `tmux.py`. **No aplica**: se siguen usando (líneas 81, 107 y 145) y ruff da limpio.

Verificación:
- Focales: 127 verdes antes y 123 después (las 4 de diferencia son las borradas).
- Ruff limpio en las 9 rutas.
- `tmux_smoke.py` sólo se compiló. No se corrió porque no hay distro WSL corriendo y despertar una tiene su costo.

## Lote 5 (paso 0): guardias de la partición

Archivos: `tests/guardia_monkeypatch.py` (nuevo), `tests/test_guardia_monkeypatch.py` (nuevo), `tests/conftest.py`, `tests/test_integration_guards.py`, `tests/test_ola1_seguridad.py`, `tests/test_server.py`.

Hubo tres pasadas de `code-review` medium. Todos los hallazgos se corrigieron y cada uno tiene su caso en `test_guardia_monkeypatch.py`:

- **Falsos positivos** (rompían pruebas válidas):
  - paquetes con `__init__`;
  - import dentro de una función (`import x` y `from x import y`). Es el caso de D en `codex_identity.py:179-182` y el de 5 pruebas del repo: `claude_pipe_cableado`, `desktop_interaction`, `console_titles` y `release_recovery`;
  - imports relativos de varios niveles;
  - `alias.attr += 1`;
  - comprensiones que tapaban un alias;
  - reexportación por nombre (`from otro import m`);
  - cadenas de atributos resueltas con el mapa de imports de cada módulo;
  - el módulo que se lee por `globals()` (`transcripts`).
- **Falsos negativos** (dejaban pasar parches sin efecto):
  - nombres en defaults y decoradores;
  - stores contados como lecturas;
  - `global` sin lectura;
  - locales que tapaban globales;
  - textos sueltos de cualquier archivo, como la clave `s["compacting"]`. Ahora un texto solo cuenta en un archivo con un `getattr` dinámico real; el `__getattr__` de reexportación no cuenta;
  - `self.state.lock`.
- **Robustez:**
  - un archivo a medio escribir deja pasar y no queda recordado (antes apagaba la guardia toda la sesión);
  - la forma de texto `setattr("mod.attr", v)` también se revisa;
  - el detector de `import server` cubre `import_module`, `__import__` e imports relativos, y no marca un `server.py` de un subpaquete.

Lo que la guardia encontró en el código de hoy (corregido):
- `ses.guess_pi` → `agentes.guess_pi`.
- `server.find_enabled` → `rules_api.find_enabled`: la demora que ensancha la carrera no se aplicaba.
- `state.ADJUNTOS`: parche redundante, borrado.

Verificación:
- Rojo de la guardia con HEAD sin la línea de `conftest`: `lote5-guardia-rojo.log`.
- Suite global con la guardia final (`suite-4.log`): ningún «no tiene efecto».
- Las correcciones de la tercera pasada están cubiertas por 32 casos y por la suite global, pero no tuvieron una cuarta revisión.

## Lote 6 (paso 2): hooks_eventos.py

Archivos:
- código: `lienzo/hooks_eventos.py` (nuevo), `lienzo/sessions.py`, `lienzo/rules.py`;
- prueba nueva: `tests/test_particion_sessions.py`;
- pruebas migradas: `tests/test_apps_escritorio.py`, `test_backend_tmux.py`, `test_captura.py`, `test_coda.py`, `test_coda_aprobar.py`, `test_denegado_autorizado.py`, `test_ejecuciones_externas.py`, `test_envio_confirmado.py`, `test_integration_guards.py`, `test_ola1_sesiones.py`, `test_pc_fields.py`, `test_pendientes_tanda3.py`, `test_pregunta.py`, `test_red_resiliente.py`, `test_reinicio_explicito.py`, `test_restore.py`, `test_server.py` y `test_stale_send_notice.py`.

`code-review` medium. No encontró cambio de comportamiento:
- cada definición es idéntica a HEAD salvo los prefijos;
- no hay estado duplicado;
- el ciclo de imports se resuelve en los dos órdenes;
- los parches migrados alcanzan al código.

Hallazgos corregidos:
1. Las pruebas usaban lo movido vía `sessions`. Ahora apuntan a `hooks_eventos`.
2. La compatibilidad tenía 30 nombres. Ahora `__getattr__` solo atiende `consume_events` y `coda_vivo_en_turno`, que todavía importa `server.py`. Se va en el lote de `server.py`.
3. El orden de import era frágil. Ahora `test_particion_sessions.py` cubre:
   - 4 órdenes en un intérprete limpio;
   - ningún uso de `hooks_eventos` al importar `sessions`, ni `from hooks_eventos import` arriba de todo;
   - ningún nombre ni estado definido en los dos módulos.

Integrado a pedido de la coordinadora: el diff de D `titulo-lanzado-arbol-F.diff`. Agrega `titulo_lanzado.aplicar` en `adopt_process` (`sessions.py`) y en `claim_pid` (`hooks_eventos.py`). `tests/test_titulo_lanzado.py` estaba en rojo en `suite-4.log` y queda en verde.

Verificación:
- 492 focales antes y después del movimiento.
- Conjunto final: 748 verdes (`paso2-final.log`).
- Ruff limpio en todas las rutas.
