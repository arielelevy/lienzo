# Z2 — sin_enviar y estado de Codex

Alcance: `lienzo/hooks_eventos.py`, confirmación y actualización desde transcripción en `lienzo/sessions.py`, `tests/test_sin_enviar_z2.py` y `tests/test_stale_send_notice.py`. Revisión con el skill code-review, en la misma sesión. T10 y T6 quedan fuera de esta entrega para la release.

## Causa comprobada

Se leyeron `GET /sessions`, los rollouts originales y `~/.lienzo/lienzo.log`. No se enviaron mensajes a OpenSyync ni se alteraron sus sesiones.

- AB (`01a16604-075a-75b1-af97-0aa9edf14110`): el mensaje del último envío aparece en el rollout con el hash SHA256 exacto a las 21:02:09.905. El turno empezó a las 20:49:09.221 y terminó a las 21:11:59.532. El log generó «el agente no confirmo el encargo en 25 s» a las 21:12:26.794. Los horarios son de Buenos Aires.
- E (`01a16557-13ec-7bc2-a69c-cd78c03cfe81`): el envío fue a las 20:50:16.474 y el mensaje está en el rollout con el hash exacto a las 20:50:17.979. El parser presenta un turno iniciado a las 20:48:06.584, `prompt_ts` 20:50:17.992 y cierre 20:55:36.148. El aviso falso se creó a las 20:56:08.127.
- R0 (`01a16557-9e43-7541-b994-a816ad6c0a49`): el último envío también tiene una coincidencia exacta de hash en su rollout. `casos-vivos.json` conserva la sesión, recibo y fechas del turno leídos.

La hipótesis del mensaje recibido mientras Codex trabaja queda confirmada. No fue necesario suponer que el transporte cambió el texto: el mensaje individual tiene el hash correcto. El parser junta varios pedidos en un solo turno; la confirmación anterior exigía comparar el texto combinado y que `ts_start` fuese posterior al envío. Ambas condiciones podían fallar aunque `prompt_ts` mostrara la recepción posterior. Además, el aviso se emitía después del cierre del turno; no había un pedido posterior al aviso que lo retirara. Ocultarlo sólo en frontend dejaba `needs` y la columna del backend intactos.

## Corrección

- Confirma consumo de un pedido de Codex por `prompt_ts` posterior o igual al envío, usando `ts_start` sólo si falta ese campo. No confunde consumo con finalización. Conserva el identificador y hash originales del recibo. Rechaza fechas inválidas, booleanos, infinitos, mensajes de sistema y recibos posteriores al pedido observado.
- El timeout no registra un fallo si ya existe un pedido observado posterior. Se limpian las marcas pendientes sin reenviar texto.
- Retira exclusivamente `sin_enviar` ante pedido posterior, entrega comprobada, cierre posterior o 180 segundos. El estado se reconstruye desde el turno existente. Permisos, preguntas y denegaciones no caducan por este arreglo.
- La liveness existente fuerza una nueva lectura al detectar el aviso vencido, aunque el archivo no haya crecido. `REFRESH_KEYS` incluye los campos del recibo para publicar también una corrección que sólo cambie la entrega.

## Revisión y evidencia

Sin hallazgos P1/P2 abiertos en este delta. Se revisaron estado muerto, ausencia de transcripción, permisos pendientes, relectura de turnos antiguos, fechas inválidas, correlación de recibos y preservación del origen de captura. La confirmación se aplica después de capturar el pedido, para no borrar antes `sent_mark` y perder su origen.

Rojo previo en `test_sin_enviar_z2.py`: **10 fallos y 3 verdes**. Fallaban recepción dentro del mismo turno, texto combinado, timeout después de recepción, cierre/TTL y reparación sin crecimiento del rollout. Después se agregaron bordes y publicación del recibo.

Verde final mediante el runner agéntico: **81/81** entre `tests/test_sin_enviar_z2.py` y `tests/test_stale_send_notice.py`. Verificación adicional del envío tradicional: **8/8** en `test_envio_confirmado.py`. Ruff check y ruff format --check: código 0, sólo en los cuatro archivos del alcance.

Explorer → Analyser → Designer → Executor → Detective se trabajaron secuencialmente; evidencia en `.temp/resultados/2026-10-22-Z2/`. La corrida y el log completo se conservan bajo `intentos/`, con su ruta en `actual-Z2-backend.json`. El runner devuelve 1 por falta de baseline aprobada, aunque el caso pytest devuelve 0; no se declara PASS de compuerta ni se fija baseline.

Uso real leído y simulación local: se aplicó el código nuevo a **copias** de E y R0 con sus transcripciones originales. Ambas pasaron de `te_necesita` a `termino`, con `needs=None` y recibo `entregado`. Esto no es una verificación después de desplegar: el servidor en uso no fue reiniciado ni modificado.

Límites: no hubo suite global, navegador, WSL ni refresh en este cierre. Sin transcripción disponible no se inventa la fase del agente. La validación tras desplegar corresponde a la coordinadora. Los cambios frontend de T10/T6 permanecen separados y no deben entrar en este commit.

## Archivos exactos para commit

1. `lienzo/hooks_eventos.py`
2. `lienzo/sessions.py`
3. `tests/test_sin_enviar_z2.py`
4. `tests/test_stale_send_notice.py`
5. `review/2026-10-22/code-review-Z2-sin-enviar.md`

ESTADO: listo para commit
