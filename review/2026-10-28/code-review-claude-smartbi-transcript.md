# Revisión: leer las conversaciones de Claude SmartBI

Alcance: cambios puntuales en `lienzo/agentes.py`, `lienzo/sessions.py` y `tests/test_apps_escritorio.py`. Revisión estática con el skill code-review; no modifica otros cambios de trabajo presentes.

## Causa y cambio

Los procesos 8068 y 19356 guardaban sus registros y conversaciones en `.claude-smartbi`. El barrido buscaba sólo `.claude/projects`. El registro permite identificar la sesión exacta por PID y FILETIME del proceso.

El lector ahora consulta las dos cuentas configuradas. Rechaza registros ambiguos, PID reciclado, identidad inválida y archivo ausente. El sessionId exige UUID antes de construir la ruta. No expone la ruta del pipe ni claves. Reutiliza el registro existente para lectura, sin modificar las configuraciones de Claude.

La adopción inicial y la tarjeta provisoria usan la misma identidad exacta. Se mantiene el comportamiento de tmux y la prioridad de los hooks. No se envió texto a las sesiones reales.

## Evidencia

- Primera corrida: 131 casos pasaron y 3 fallaron porque la normalización alteraba las mayúsculas de la ruta devuelta. Se corrigió el fuente para normalizar sólo la clave de deduplicación, conservando la ruta original.
- Segunda corrida: 134 pruebas pasaron en identidad, tarjetas ajenas, sesiones y runtime Claude. Ruff: `All checks passed!`.
- Después del reinicio solicitado, `/sessions` devuelve para el PID 8068 el id `11febda3-da4c-41a3-b727-a24a27779b41` y 3684428 bytes leídos; para 19356, `bd8bceed-cd64-4887-b1db-8ababe8f43c3` y 1555345 bytes. Ambas rutas están en `.claude-smartbi/projects` y tienen respuesta visible en la API.
- El proceso headless 2352 ya no estaba en la respuesta posterior. Su comando original usaba `--no-session-persistence`; este cambio no crea una conversación inexistente.

Sin hallazgos bloqueantes en el delta revisado. No se midió mutación nueva. La evidencia de integración y el veredicto del runner se registran en `pruebas-agenticas/resultados/tarjetas-ajenas-N/`.

## Integración ampliada

El runner ejecutó los dos casos vigentes: backend pasó (218 pruebas); E2E falló al esperar 120 s la eliminación de una tarjeta. El log sí confirma regla estacionada y herencia posterior correctas. El plazo coincide con `DEAD_KEEP_S = 120`, cuya eliminación exige superar ese valor. Se dejó pendiente revisar el contrato y margen del caso. No se modificó el E2E ni su baseline. La compuerta devolvió código 1 por ausencia de baseline; no hay PASS global.

Chromium real verificó ambas tarjetas por su sessionId exacto, con 132 y 1328 caracteres visibles. Captura revisada: `web/node_modules/.playwright-artifacts/claude-smartbi-real.png`. El servidor de prueba aislado terminó; el servidor principal permanece levantado.
