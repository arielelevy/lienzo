# Revisión focal: procesos internos de Claude

Alcance: `lienzo/procinfo.py` y `tests/test_claude_internal.py`. Pedido: corregir las tarjetas auxiliares detectadas en Claude Code 2.1.310. Revisión secuencial por la misma sesión, sin agentes independientes.

## Resultado

Sin hallazgos pendientes en el delta revisado. El filtro usa únicamente el primer argumento y los dos comandos internos observados (`daemon`, `--bg-pty-host`). Conserva conversaciones hijas, modo batch, valores de opciones, texto de prompts y la política previa cuando el comando de Claude no se puede leer. Se aplica tanto al barrido como a liveness y a la validación del destino de tecleo. También cubre binarios renombrados por el actualizador.

No se cierran procesos, no se alteran transcripciones y no se agregan dependencias ni comandos de shell. Se revisaron las rutas paralelas `agent_of`, `process_agent`, `sweep`, `agent_alive` e `is_tui` contra la checklist del skill code-review.

## Verificación

- 72 pruebas focales pasaron en 5.41 s: clasificación, procesos, apps de escritorio y ejecuciones externas.
- El primer comando de pruebas incluyó por error `tests/test_external.py`, inexistente; no ejecutó casos. El siguiente encontró `PermissionError: [WinError 5]` en temporales del sandbox; la ejecución fuera del sandbox terminó con código 0.
- Ruff check, format --check y git diff --check sin errores después del formato.
- Recorrido agéntico secuencial y propuestas: `.temp/claude-internal/roles.json`, blueprint, requisitos, casos y mutaciones. No se aceptaron propuestas ni se fijaron baselines. Las pruebas focales no se presentan como PASS de la compuerta de aceptación.

Límite: se filtran las dos formas de comandos internos medidas en vivo; una futura forma diferente necesitará evidencia y su regresión correspondiente. No se declara una auditoría global del repositorio.
