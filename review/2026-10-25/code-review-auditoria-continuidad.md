# Revisión focal: continuidad de la auditoría

Fecha: 2026-10-25. Alcance: `lienzo/auditoria.py`, `tests/test_auditoria.py`, `tests/test_auditoria_envio.py` y configuración focal del runner. Revisión secuencial por la misma sesión, no independiente. Se integró por fast-forward el arreglo remoto `870b99c`, preservando artefactos locales y retirando sólo el parche duplicado de esta sesión.

## Hallazgo corregido

La auditoría emitía `sin_aviso: true` sin `from`. El contrato real `server.validar_send` rechaza ese cuerpo. Evidencia de producción: `~/.lienzo/lienzo.log`, 2026-10-25 13:39:12.663, `auditoria: ronda fallida (HTTPError: HTTP Error 400: Bad Request)`.

Se quitó `sin_aviso`: el aviso de auditoría no es un acuse originado por una sesión y no debe silenciar informes de la coordinadora. No se inventa una identidad emisora ni se cambia la validación del servidor. La prueba de ronda local ahora contrasta el cuerpo con `server.validar_send`, además de verificar agrupación, exclusión remota y deduplicación.

## Validación

- Primer intento focal: 18 errores de entorno por `PermissionError: [WinError 5]` en el temporal de pytest; no ejecutó los casos.
- Ejecución autorizada fuera del sandbox: 18 pruebas pasan.
- Runner agéntico final sobre versión integrada más corrección de avisos omitidos: caso `auditoria-contrato-envio`, código 0; 22 pruebas pasan, logs preservados en intento `2026-10-25T17-00-44.155Z-25740`. Runner sale 1 por baseline ausente.
- `ruff check` y `ruff format --check`: código 0.
- Compuerta: código 2, falta baseline. No se fijó ni aprobó referencia ni mutaciones.
- Ronda viva manual 13:52:18: código 0, un frente quieto de OpenSyync identificado (9.4 min), un aviso enviado al servidor sin HTTP 400. Esto acredita aceptación HTTP, no lectura por la coordinadora.

Sin hallazgos nuevos bloqueantes en el delta. La aceptación HTTP no demuestra que el agente recibió o actuó. No se afirma autonomía para reasignar ni se cierran sesiones por el arreglo.

## Hallazgo adicional corregido

`ronda_local` persistía las claves filtradas incluso para destinos trabados o ausentes. El arreglo integrado sólo retiraba claves de destinos con excepción HTTP. Se amplió la condición a todo destino que no figure en `enviados`: incluye fallidos, omitidos por bloqueo y ausentes. La regresión deja trabada la coordinadora, comprueba cero claves emitidas, la libera y verifica un aviso con sus cinco frentes en la ronda siguiente. Pasó en el runner final.

OpenSyync confirmó en su respuesta que llegó un aviso real y reasignó B/C/D; A pasó a esperar intervención y E conserva su informe de revisión. No se resuelven permisos ajenos ni se presenta quietud legítima como defecto. Se solicitó reinicio del servidor local mediante `/restart`, aceptado con `reinicia: true`, para cargar la implementación integrada.

Comprobación automática posterior al reinicio: ronda 14:02:08, log 14:02:10.636 `auditoria: 1 hallazgos, 1 avisados a 1 coordinadoras (3.49 ms)`. Se creó `~/.lienzo/auditoria.json` con la entrega de E marcada como avisada. `/health` responde `ok: true`, 8 sesiones, 0 pendientes. El último HTTP 400 previo fue 13:59:12.774. Se acredita una ronda automática real exitosa, no sólo la prueba manual.

Actualización posterior solicitada: integrado `1348bc5` por fast-forward sin perder el delta local de auditoría. Build de interfaz código 0 (primer intento bloqueado por `spawn EPERM`, ejecución autorizada posterior correcta). Integración focal: 37 pruebas pasan entre auditoría, estados de creencias y reclasificación. Reinicio local aceptado y `/health` 14:09:29 devuelve `ok: true`, 8 sesiones y 0 pendientes. No se ejecutó la reclasificación histórica. Delta adicional y evidencia conservados sin commit. El informe de la otra coordinadora declara su PC ya en `1348bc5`; no se reinició esa PC desde esta sesión.
