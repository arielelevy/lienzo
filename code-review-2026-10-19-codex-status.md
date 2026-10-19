# Revisión de /status de Codex

Alcance: `lienzo/codex_status.py`, `lienzo/server.py`, `tests/test_codex_status.py`, `tests/test_console_titles.py`.

La consulta automática se repetía tras 10 segundos al fallar y 60 al funcionar. Ahora hay un intento por encarnación del proceso; Buscar sesiones permite otro sin duplicar una consulta en curso. La prueba de identidad sigue venciendo a los 60 segundos: no se convierte en autorización de envío ni conserva una identidad vieja indefinidamente.

Revisión: bloqueo compartido, PID reciclado, fallo, tiempo transcurrido, consulta concurrente y conexión del botón revisados. Sin hallazgos bloqueantes en el delta. Las guardias de borrador y terminal ocupada siguen vigentes. La memoria conserva una entrada pequeña por encarnación observada hasta el reinicio o la búsqueda manual; otra encarnación del mismo PID retira la anterior.

Validación: 44 pruebas focales pasaron; Ruff focal sin hallazgos. El runner agéntico existente `codex-queue.json` ejecutó 73 pruebas (código del caso 0), pero terminó con código 1 porque falta baseline. La compuerta también terminó con código 1 por falta de baseline. No se aprobó ni regeneró ninguna referencia. No hay PASS certificado de aceptación ni prueba de uso sobre las terminales reales del usuario.

El cambio requiere reiniciar el servidor para cargarlo. No se reinició durante esta revisión: también aloja sesiones administradas.
