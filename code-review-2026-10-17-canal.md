# Revisión del canal Desktop y comandos de salida

Alcance: delta de `lienzo/claude_pipe_adapter.py`, `lienzo/codex_identity.py`, `lienzo/agentes.py`, `lienzo/sessions.py`, `web/src/components/ClaudeConnection.tsx` y sus cuatro archivos de pruebas. Revisión focal autorizada por el encargo y por las instrucciones de Ariel; no auditoría global de dependencias. Se aplicó el skill `code-review` (nombre del catálogo: `code-audit`). No existe `AGENTS.md` en la raíz; se aplicaron las instrucciones de usuario recibidas en la sesión.

## Hallazgo reproducido y corrección

El padre del adaptador devolvía éxito después de `Popen` y descartaba stderr del hijo. Un hijo que no puede conectarse deja el bootstrap con código 0 y ningún canal vivo. `.temp/coordinacion/2026-10-17/repro-adapter-startup.py` ejecutó el original de HEAD y la corrección con un entorno sintético sin canal: original 0 sin salida; corregido 2 con `claude_pipe_adapter_failed`. Es una reproducción aislada del falso éxito, no evidencia de cuál fue la excepción exacta en la conversación de Ariel.

El hijo ahora confirma por stdout únicamente su primer poll autenticado. El padre espera esa confirmación con tiempo acotado. Ante EOF, respuesta inválida o timeout falla y recoge su propio proceso hijo. Se conserva la política de no reintentar entregas inciertas. La comprobación previa de las dos variables del canal evita consumir un bootstrap desde una consola que no las heredó y explica cómo ejecutarlo en la conversación receptora.

Se revisaron la reserva de credenciales, la no exposición de tokens, los límites de lectura, los cierres de stdin/stdout, el manejo de CRLF y el alcance del proceso que se termina. Las pruebas usan procesos hijos reales con datos sintéticos y dobles explícitos para el canal Claude. No escriben a las sesiones de Ariel.

`send_to_session` rechaza `/exit` y `/quit` exactos, sin distinguir mayúsculas y con espacios exteriores, para Codex y Pi. Devuelve 400 y explica que se debe cerrar mediante el tablero o la terminal. No envía un prompt que pueda contestar falsamente que el proceso terminó. Los pedidos de otra PC conservan el reenvío al dueño antes de aplicar la guarda local.

La interfaz explica la sintaxis PowerShell sin otro `!` cuando la caja ya está en modo bash. También hace explícito que el enlace en memoria necesita una conexión nueva después de reiniciar el server.

## Validación medida

- Focal Desktop: 108 pruebas aprobadas, antes de agregar la guarda de salida.
- Navegador: 6 pruebas aprobadas (`desktop-lifecycle.spec.ts` y `envio-claude.spec.ts`), con tablero fijo y escrituras reales bloqueadas.
- Build, TypeScript, ESLint focal y Ruff de adaptador/pruebas: código 0. Vite conserva el aviso de chunk superior a 500 kB.
- La primera ejecución de pytest fue bloqueada por `PermissionError: [WinError 5] Access is denied` en el directorio temporal. El primer build fue bloqueado por `spawn EPERM`. Se conservan ambos resultados en las herramientas; las ejecuciones autorizadas posteriores pasaron.
- Primera suite backend del runner: 2337 aprobadas, 3 omitidas y una fallida. La fallida fue `test_adapter_bootstrap_entrypoint_uses_flat_import_without_starting_child`: su doble de `Popen` no implementaba stdout ni confirmación de inicio y su entorno carecía de las dos variables del canal. Se actualizó ese doble con valores sintéticos y el handshake. Las 59 regresiones focales siguientes aprobaron. Se conserva el fallo original en `pruebas-agenticas/resultados/intentos/2026-10-18T00-38-32.582Z-44840/salidas/backend-pytest.intento-1.log`.

No se aceptaron baselines, casos ni mutaciones. Los cinco roles se trabajaron secuencialmente en esta sesión, con registro retrospectivo y limitaciones en `.temp/coordinacion/2026-10-17/bug-canal-evidencia/roles.json`. Delta y certificación devolvieron 1 por falta de aceptación humana. Trazabilidad registró huecos del diseño focal. No hay PASS certificado de aceptación de esta misión.

## Pendientes reales

La identidad visible Codex sigue sin solución. `codex_identity.probe` rechaza deliberadamente incluso un rollout estable: existe reproducción previa de `/new` conservando un handle del hilo anterior y ejecutando un turno oculto. No se quitó esta protección ni se modificó configuración de seguridad. Los errores de snapshot incompleto no se trataron como evidencia positiva para enviar. La asociación de transcripciones para lectura se corrigió como se detalla abajo; el envío sigue bloqueado.

El enlace Claude sólo existe en memoria del proceso servidor y su adaptador termina ante un fallo de poll. No se implementó persistencia de credenciales ni reconexión automática. No se reinició el server, que continuó con PID 26868. No se ejecutó un bootstrap ni un envío en la conversación real de Ariel. La verificación de ese recorrido queda pendiente de una prueba coordinada con la conversación receptora. No se marcaron tareas completadas.

Consulta en vivo posterior: `GET /sessions` publicó para la sesión Claude Desktop `0bedd7fa-2d5f-4f2a-a7a8-0f084d0f13c4`, PID 22884, `alive: true`, `envio.puede: true`, `motivo: null`, `transporte: claude_pipe`. El canal estaba conectado en ese instante. No se atribuye ese estado al parche: el server no recargó los módulos. La captura real `canal-tablero-real.png` se obtuvo con Chromium sin clicks ni escrituras.

## Ampliación solicitada: transcripción Codex ausente

Ariel pidió arreglar también que mi conversación no aparecía. La tarjeta `pid-12328` tenía `transcript_path: null` y el error de snapshot incompleto. El inventario estricto de handles descartaba todo el resultado cuando un handle ajeno al rollout no se podía duplicar. Además, la falta de prueba del hilo visible para enviar bloqueaba la lectura de transcripciones.

Se agregó `codex_identity.transcript_identity` como contrato de descubrimiento de lectura. Puede observar un único rollout efectivamente abierto por el PID aunque otros handles fallen. Exige origen TUI, UUID canónico y dos observaciones con idéntico FILETIME y conjunto de rollouts. Cero, múltiples o cambios entre observaciones se rechazan. Un resultado observado tiene `verified: false`; no habilita `codex_queue` ni guarda `codex_process_start` como prueba para enviar. `agentes.Codex.identity`, el barrido y `attach_transcript` consumen este contrato de lectura. No se elige por carpeta ni por archivo más reciente. La asociación conserva la guarda que impide quitarle un hilo a otro proceso vivo.

Medición real de sólo lectura, con la nueva función cargada en un proceso aparte:

| PID | Hilo observado |
| --- | --- |
| 12328 | 01a14c6f-f6af-7593-a0c3-63e77928b4ae |
| 12860 | 01a14c71-9e2c-76c1-8ede-a0e29e867e82 |
| 7952 | 01a14bf5-c9c0-7b32-9570-a8b5acf7b08d |

Los tres devolvieron `observed: true` y `verified: false`. El server activo sigue con los módulos anteriores; esta medición no afirma que ya cambió la tarjeta. Las 66 pruebas focales posteriores aprobaron, incluyendo dos Codex en la misma carpeta, PID reciclado, cambio de rollout, archivos `codex_exec`, rechazo de envíos con identidad sólo observada y preservación de una tarjeta de otro proceso vivo. Ruff y `git diff --check` aprobaron. Se inició otra suite backend completa; su resultado final se registra debajo.

Esta ampliación corrige la asociación para lectura. La observación de un archivo no acredita que sea el hilo actualmente visible después de `/new`; por eso se conserva el bloqueo de envío. Queda pendiente el recorrido real después de cargar los módulos.

## Resultado de la segunda global y diagnóstico posterior

Corrida `2026-10-18T00-47-03.822Z-5552`: 2343 aprobadas, 3 omitidas y 2 fallidas; runner con código 1. Se conservan las salidas completas en `pruebas-agenticas/resultados/intentos/2026-10-18T00-47-03.822Z-5552/salidas/backend-pytest.intento-1.log`.

Una falla fue una regresión del nuevo contrato de lectura: cuando tampoco podía observar un rollout, reemplazaba el motivo original de la prueba estricta. `transcript_identity` ahora conserva la prueba original ante una observación fallida. La batería posterior incluyó `test_cinco_root_identity.py`: esa regresión aprobó.

La otra fue `test_espejo_lista_antes_y_borra_solo_con_confirmacion`, con `dump/partida.dat bloque 4: ruta relativa con enlace o fuera del destino físico`. No se modificó `xfer.py`. En la batería focal posterior el caso de espejo aprobó, pero falló `test_sin_espejo_nunca_borra`; resultado de esa batería: 85 aprobadas y 1 fallida en 45,52 segundos. Es evidencia de un fallo intermitente de transferencias en código sin modificar, cuya causa todavía no está confirmada; no se elimina del veredicto por una repetición verde.

La instrumentación de sólo observación en `.temp/coordinacion/2026-10-17/diagnosticar-xfer.py` registra excepciones y rechazos de `_dentro_sin_enlaces`, sin cambiar el valor devuelto. Los dos casos aprobaron su primera ejecución instrumentada (11,07 segundos). Se conserva la medición repetida por intento en `xfer-diagnostico-*.log`. No se relajaron las guardas de confinamiento ni se cambiaron configuraciones de seguridad.

Las cinco repeticiones instrumentadas terminaron con código 0: dos pruebas aprobadas en cada intento, en 13,61; 11,22; 10,31; 10,57 y 10,40 segundos. No se capturó el rechazo bajo instrumentación. Esto no identifica la causa ni convierte los fallos anteriores en PASS.

El release no está certificado: faltan resolver o aislar con evidencia el fallo de transferencia, cargar los módulos en el backend y verificar el canal real. No se afirma una suite global verde del estado final.

La compuerta general devolvió `VEREDICTO: FAIL`, código 1, porque `actual.json` y `mutacion.json` pertenecen a otro estado del código. Sus conteos históricos de siete casos y seis mutaciones no se atribuyen a este parche. Las dos ejecuciones focales del runner guardaron sus logs de intento por separado; ninguna sustituye esa evidencia global. La primera invocación de la compuerta bajo sandbox no pudo consultar Git y devolvió ESCALAR; la invocación autorizada confirmó el FAIL. La comprobación final de Ruff y `git diff --check` pasó.

Se pidió a Ariel confirmación para cargar el parche mediante un reinicio del backend y verificar la tarjeta real. Hasta recibirla, el server permanece intacto. No se publicó un release ni se aprobó ninguna referencia.

## Carga autorizada y verificación real

Ariel autorizó el reinicio y el push. `POST /restart` devolvió `{"ok":true,"reinicia":true}`. Después, la raíz respondió HTTP 200 y `GET /sessions` publicó para PID 12328 el hilo `01a14c6f-f6af-7593-a0c3-63e77928b4ae`, `alive: true`, el rollout correcto y `transcript_bytes: 2051718`. Antes del reinicio la tarjeta era `pid-12328` y no tenía transcripción. La corrección de asociación para lectura quedó verificada en el backend real. El motivo continúa aclarando que el hilo visible de la TUI no está verificado para enviar. No se enviaron mensajes a otras sesiones ni se modificaron permisos.

El reinicio y el push autorizados no constituyen aceptación de baselines ni certificación del release. El fallo intermitente de transferencia y la comprobación de un bootstrap real en Claude continúan pendientes.
