# Verificación entre dos PCs y asociación automática de Codex

Medición del 18 de octubre de 2026. PCs emparejadas: `ar-it33940` (`dee050ccab4f`) y `ariel` (`75727ff74069`). Ambas tenían `0d6fd72` al comenzar. El cambio de asociación se activó después en la PC local; las mediciones de red no acreditan que el código nuevo estuviera instalado en la remota.

## Federación real

Nueve comprobaciones aprobadas por HTTP real contra las dos PCs: ambas vivas; salud firmada; snapshot firmado; coincidencia del inventario remoto con el espejo; solicitud firmada válida; rechazo de replay; rechazo de firma alterada; rechazo sin firma; consulta Git de lectura enrutada a la otra PC.

La segunda medición incluyó una tarjeta Codex real en la PC remota, lanzada por Lienzo. El snapshot remoto y el espejo publicaron su mismo identificador. Cinco lecturas de salud tardaron 263,94; 6,21; 6,44; 7,63 y 7,37 ms, mediana 7,37 ms. Es una muestra bajo carga de pruebas, no una medición de transferencia sostenida.

El `/status` de la Codex remota devolvió su UUID en la consola. La prueba no ejecutó el descubridor nuevo dentro del servidor remoto. La sesión descartable se cerró con `/kill` y respuesta `ok: true`.

Evidencia local: `.temp/two-pcs-2026-10-18.json`. La batería focal de federación, espejo, reglas, resiliencia y confirmaciones dio **148 passed in 38.94s**.

## Incidente de Codex

La terminal PID 14632 mantenía cero rollouts abiertos y utilizaba un daemon compartido. Lienzo mostraba una tarjeta provisional con PID y aviso `sin_enviar`, y otra tarjeta de hooks con la transcripción pero sin PID. No se asoció por carpeta ni por cercanía temporal.

El descubridor ahora consulta `/status` únicamente ante un editor vacío y una terminal libre. Comprueba dos pantallas estables, fija PID y fecha de creación para escribir el comando local y lee el UUID del bloque de estado. Busca un único archivo con ese UUID y valida su cabecera. No habilita `queue`. La ausencia de archivo antes del primer mensaje conserva la identidad sin resolver.

La unión con una tarjeta existente conserva el cableado, el recibo incierto y los permisos reales. Una tarjeta que ya pertenece a otro proceso vivo no se reasigna. Sin transcripción, el aviso público explica que no se pudo confirmar la recepción y deja de afirmar que falta Enter.

Prueba real del descubridor aislado: PID 33444, UUID `01a15040-d076-7940-a6dc-a366e441eb9d`, archivo exacto y resultado `observed: true`, `verified: false`.

Prueba posterior contra el servidor local actualizado: PID 23928, UUID `01a15046-c982-7571-b3ad-6800b1ff9305`, una sola tarjeta para el PID, transcripción no vacía, respuesta exacta `LIENZO_STATUS_API_OK`, estado `termino` y transporte `tecleo`. Este recorrido tuvo hooks activos; no sustituye la prueba aislada del descubridor. El proceso descartable se cerró al terminar. Evidencia: `.temp/smoke-status-api.json`.

La sesión de trabajo que motivó el incidente seguía ocupada durante estas mediciones. Su consulta automática espera a que quede libre; no se tecleó `/status` en ella durante el turno.

## Pruebas y presentación de cuotas

La focal final de identidad, descubrimiento, consola, recibos y traspasos dio **119 passed in 9.47s**. Incluye dos terminales en una carpeta, rechazo de borradores y cambios de pantalla, PID reciclado, archivos ambiguos, origen headless y unión con un permiso pendiente.

Frontend: ESLint y build con código 0; nueve pruebas Chromium de cuotas y recuperación aprobadas. Captura de cuotas inspeccionada. El indicador ahora dice explícitamente «usado semanal» y «usado 5 h»; no invierte el porcentaje de la API. El build conserva el aviso existente de chunk mayor a 500 kB.

La primera corrida global dejó de producir salida antes de un resumen final; no se contabiliza como aprobada. La corrida final se registra en `.temp/backend-final.log` y `.temp/backend-final.xml`.

## Alcance conservado

Estas pruebas no cierran todos los pendientes históricos multi-PC: no se ejercitaron permisos remotos reales, retorno automático de informes con dos frentes, caída de red, firewall ni transferencia sostenida. No se cambiaron baselines ni se marcaron casillas de esos pendientes.
