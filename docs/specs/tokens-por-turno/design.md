# Tokens por turno en capturas

Fuente: PENDIENTES.md «Tokens por turno en la memoria» y encargo 2026-10-25 de la coordinadora. Referencia suministrada desde `bench-clis/2026-10-25/analisis_logs.py`, función tokens_turno.

## Contrato

Cada captura nueva de clase `respuesta` lleva `origen.usage`: objeto con `input`, `output`, `cache_read`, `cache_write`, `reasoning`, o `null` si no se pudo medir. Cada campo ausente es `null`, no cero. `origen.usage_turno` conserva la identidad usada. El campo `input` de Claude y Codex representa input no cacheado; reasoning de Codex es un subconjunto reportado de output, no una cantidad para sumar de nuevo. No se calcula costo ni se estima desde texto.

La tarjeta guarda el ID del último turno leído del transcript antes de aplicar su cierre. Un nuevo pedido real por hook borra esa referencia anterior. La captura encola una copia de fuente, IDs y cierre; el hilo de SQLite lee el consumo, fuera del lock de sesiones. Las rutas de transcript son internas a la cola: no van en `origen` ni viajan por réplica. Un snapshot que ya volvió a `corriendo` no acredita un cierre.

Se congela el tamaño del archivo al abrirlo y se lee en streaming desde el comienzo, para no depender de la cola de UI de 2 MB. El cierre admite la ventana de 5 s de la referencia para contadores emitidos tarde, pero se corta al siguiente pedido/turno identificado para no mezclar respuestas. Sin identidad suficiente, formato reconocido o contadores válidos, queda `null`. Corrupción o lectura fallida se registra por tipo de error sin volcar texto ni rutas privadas; la respuesta se conserva.

## Agentes

- Claude: límite por promptId/uuid; una llamada por message.id (uuid si no está). Une contadores publicados en bloques del mismo mensaje, tomando el último valor emitido por campo, y suma llamadas distintas. Incluye usage de entradas assistant presentes en el transcript raíz, incluso sidechain; no recorre archivos de agentes hijos. Un contador ausente en una llamada no acredita un total completo para ese campo. Reasoning separado no observado: null.
- Codex: último `total_token_usage` del turno cerrado menos el anterior al task_started. Cache leído se resta de input_tokens para obtener input no cacheado. Cache escrito no observado: null. Si un turno anterior no tiene muestra base o el contador baja, ese dato queda desconocido. El primer turno completo del archivo empieza con acumulador cero, como en la referencia. Se requiere task_complete o turn_aborted y no se usan last_token_usage como sustituto.
- Pi: recorre ancestros de la hoja capturada hasta el usuario del turno; suma los usages assistant de esa rama, con campos input/output/cacheRead/cacheWrite y reasoning sólo si existe. No mezcla otras ramas ni un pedido posterior.
- coda: SQLite en modo lectura; suma las columnas publicadas en usage de la sesión entre su pedido identificado por created_at y el cierre (+5 s), acotado por el siguiente pedido real. Ignora mensajes de sistema como límites. No usa cost_micro ni agent_runs/workflow_runs como sustitutos.
- Kiro: el formato observado publica créditos/contexto, no tokens por turno. Usage null; no lee auth_kv ni state.

## Persistencia y límites

No cambia el esquema: origen ya es JSON y la réplica copia íntegro ese campo. Las capturas existentes son inmutables y no se rellenan retrospectivamente. Si faltan datos al capturar, no se sustituye por otro turno ni se modifica la captura más tarde.

Prueba viva de sólo lectura: un turno cerrado real de Codex coincide con una resta independiente; rollout 3.578.639 bytes, lector 17,72 ms en esa condición. No es un presupuesto general de rendimiento.

- [ ] Lectores y enlace de identidad al cierre.
- [ ] Captura y réplica con nulls conservados.
- [ ] Cinco roles, revisión, pruebas, commit y push; aviso previo a reinicio.
