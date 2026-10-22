# Code review — noche D (2026-10-22)

Delta revisado: `lienzo/codex_observation.py` (+2 líneas: `_footer` pasa `env={"PYTHONIOENCODING": "utf-8"}`)
y `tests/test_codex_new_clear.py` (nuevo, 7 pruebas). Skill `code-review`, nivel low.

## Hallazgos

Ninguno confirmado.

- Duda del revisor: si `subproc.correr` pasara `env` tal cual, el hijo perdería PATH/SYSTEMROOT.
  Descartada: `lienzo/subproc.py:125` arma `{**os.environ, **(env or {})}`. Medido en vivo
  (`.temp/resultados/noche-D/footer-utf8-vivo.txt`): sin el env, `screen.py` sale 1 con
  `UnicodeEncodeError`; con el env, 0 y `ok: true`.

## Verificación

- Rojo: `test_footer_reader_forces_utf8_output` falla contra `codex_observation.py` de HEAD.
- Verde: 128 passed (Codex y plugins) en copia de HEAD con los archivos de D.
- `ruff format` / `ruff check` sólo sobre las dos rutas: sin cambios, sin avisos.

## Ronda 2 (2026-10-22 00:22)

Delta: `lienzo/titulo_lanzado.py` (nuevo), `lienzo/launch.py` (guarda el título junto al `.cmd`),
`lienzo/codex_status.py` (permiso de `/status` por rollout nuevo), `tests/test_titulo_lanzado.py`,
`tests/test_codex_status_rehilo.py` y el diff propuesto `.temp/resultados/noche-D/titulo-lanzado-arbol-F.diff`
(sessions.py y hooks_eventos.py, sin aplicar). Skill `code-review`, nivel low: sin hallazgos.

Verificación: rojo/verde en copia de HEAD; verde en copia del árbol de F con el diff; en vivo con
CLI propia (PID 6916): título recuperado del cmd.exe padre; `/status` tecleado 3 veces (lanzamiento,
hilo A, hilo B tras `/new`) y ninguna en siete consultas sin rollout nuevo.

## Ronda 3 (2026-10-22): limpieza de ~/.lienzo/launch/

Delta: `lienzo/launch.py` (`_limpiar_viejos`, llamada en `_launch_cmd` antes de escribir el nuevo
`.cmd`) y `tests/test_launch_limpieza.py` (3 pruebas). Skill `code-review`, nivel low: sin hallazgos.
Rojo sin la llamada (1 de 3); verde 48 passed con test_launch*. En seco sobre la carpeta real:
290 archivos, todos con el patrón; 176 con más de 7 días; ninguno usado por un cmd.exe vivo.
