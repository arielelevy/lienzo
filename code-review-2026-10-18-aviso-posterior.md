# Revisión del aviso antiguo tras pedidos posteriores

Alcance autorizado: reporte de Ariel del 2026-10-18, posterior a v0.4.0. Revisión focal de `sessions.py`, `transcripts.py` y `test_stale_send_notice.py`, siguiendo code-review. No se alteran el tag publicado ni la validación de entrega exacta.

## Hallazgos y correcciones

- En la tarjeta real de la coordinadora persistía `sin_enviar` de las 12:35, aun leyendo pedidos humanos posteriores. El recibo más reciente seguía encolado porque Codex acumuló varios mensajes en un turno y el texto completo no coincidía. El arreglo anterior solo retiraba avisos con una entrega posterior confirmada.
- Se conserva el timestamp de la última entrada humana de Codex, tanto para `UserMessage` como para `user_message`. Las herramientas, respuestas y recordatorios de sistema no adelantan ese timestamp. Un pedido real posterior retira únicamente el aviso antiguo; no convierte el recibo en entregado.
- Liveness evaluaba el timeout antes de releer la transcripción, pudiendo generar otro aviso falso. Ahora aplica primero la actividad nueva. Un recibo que no pudo correlacionarse queda sin confirmación al vencer, sin volver a pedir Enter si ya hubo un pedido posterior. Los permisos y preguntas reales no se sustituyen por el timeout.
- `needs` y `prompt_ts` forman parte de los campos comparados para publicar y persistir cambios, incluso si la tarjeta ya figura corriendo.

## Recorrido de pruebas

Los cinco roles se trabajan secuencialmente en la coordinadora, reutilizando el recorrido y los contratos del plugin pruebas-agenticas. Explorer verificó la tarjeta real; Analyser separó aviso obsoleto de entrega incierta; Designer agregó límites temporales, entradas acumuladas, recordatorios y permisos; Executor ejecutó los casos reproducibles; Detective contrastó resultados y conserva la limitación de no certificar entrega por coincidencias parciales. Evidencia local en `.temp/coordinacion/2026-10-18/aviso-posterior-roles.json` y `focal-aviso-posterior-final.log`.

Focal final: **199 passed, 3 skipped in 6.28s**, exit 0. Incluye transcripciones, recibos, consola Codex, guards, sucesión y regresiones de diseño. Las tres omisiones corresponden a rollouts de muestra inexistentes. No se reejecuta ni se presenta como nueva la global de 0.4.0. Los fixtures prohíben reenvíos y verifican que no se invente confirmación final.

Ruff final: código 0. Tras el reinicio avisado, la tarjeta real pasó a `corriendo`, con `needs: null` y `envio_pendiente: null`. El recibo se conservó como `sin_confirmacion`, sin afirmar entrega. La UI instalada se verificó en Chromium de solo lectura: **0 bloques `.needs.terminal`** en la tarjeta propia, tres tarjetas y una caja de envío. Se bloqueó el PUT automático del scheduler; no se escribió en el tablero desde el navegador. Captura `release-aviso-posterior.png` revisada; el texto del aviso pegado por Ariel permanece como mensaje histórico, no como aviso activo.

Sin otros bloqueos concretos detectados en este delta. El baseline aprobado por Ariel se conserva en el commit separado `8054a4c`; no se aceptan propuestas ni mutaciones adicionales.
