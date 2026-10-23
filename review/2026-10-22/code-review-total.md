# Revisión total de código — V

2026-10-22. Sesión `pid-41040`. **11 hallazgos: 2 altos, 8 medios y 1 bajo.** No se modificó código ni se ejecutaron builds, suite global, servidores o proveedores de IA. Única escritura de esta entrega: este informe.

Antes de 0.6.14 recomiendo corregir T1 y T2. También T3 y T9 si se integran AA/AB, y T4–T8 por pérdida de evidencia, persistencia o estado visible. T10 afecta borradores de respuestas en el agrupado ya integrado. T11 debe reforzarse antes de presentar la prueba como garantía de seguridad. Son recomendaciones de revisión, no aprobación de release ni tareas marcadas como completadas.

## Alcance y estado observado

Inventario y barrido estático de las cinco raíces completas; lectura manual dirigida por flujos y riesgo. Esto no equivale a una lectura manual exhaustiva de cada una de las 127.042 líneas ni a certificar ausencia de otros defectos.

| Raíz | Archivos de código inventariados | Líneas |
|---|---:|---:|
| `lienzo/` | 135 | 50.840 |
| `web/src/` | 79 | 16.993 |
| `ops/` | 8 | 479 |
| `tests/` | 214 | 50.402 |
| `web/tests-ui/` | 61 | 8.328 |
| Total inicial | 497 | 127.042 |

Incluye Python, TS/TSX, JS/MJS, CSS, HTML y scripts. El inventario inicial precede a algunos archivos nuevos del WIP. HEAD inicial `75d005e03f45f81c2e16ea6607f15a3056c7b5ff`; al cerrar, `595f056aaa457b88c523956913f42bd25dfa9c70`, que integra el agrupado Z. El trabajo de terceros continuó durante la revisión.

Se revisaron entradas HTTP y comprobaciones `X-Lienzo`, firmas de peers, resolución de rutas y raíces de lanzamiento, envío y cola Codex, hooks y persistencia, restauración, rondas, transferencias, procesos, retención, investigación/creencias, Prolog, SSE y consumidores React. No se identificó otro bypass concreto de autenticación o rutas con evidencia suficiente para reportarlo. Eso no certifica dichos mecanismos ni sustituye pruebas de penetración.

Dueños del WIP observado:

- **Z:** agrupado en `Board.tsx`, estilos y pruebas de clusters; avisos en `Card.tsx`, `CardNeeds.tsx`, `types.ts`, `card-notices.ts` y pruebas. Integrado en `595f056` durante esta revisión.
- **AA:** `prolog_programa.py`, `prolog_servicio.py`, pruebas Prolog y hook de formalización en `creencias.py`; integración poscommit en conocimiento. El ciclo continuo seguía en desarrollo. No se reporta su ausencia como defecto de una entrega terminada.
- **AB:** `creencias_revision_ia.py`, `metadatos_creencias.py`, API, `LearningReviewIA.tsx`, integración en `Learning.tsx`, pruebas y script de revisión real. Comparte `creencias.py` con AA. Su informe propio ya estaba disponible al cierre; los riesgos T2 y T9 no quedan cubiertos por las verificaciones allí descritas.

Los hallazgos V1–V5 del informe anterior no se vuelven a contar: existen correcciones en `7ba286d` y `9141a50`.

## Hallazgos altos

### T1. El diario Codex falla abierto y permite repetir un envío incierto

**Referencia:** `lienzo/codex_queue.py:141`, `_load`; consumidor `enviar`. **Dueño:** núcleo de envíos/coordinadora.

`_load` convierte `OSError`, JSON inválido y contenido que no es diccionario en un diario vacío. Si una lectura falla por permisos/antivirus y la siguiente escritura funciona, `enviar` pierde la reserva anterior y vuelve a ejecutar el mismo mensaje, incluso cuando el primer envío terminó `sin_confirmacion`. Puede sobrescribir la única evidencia que impedía duplicarlo.

**Confirmación aislada:** funciones reales extraídas mediante AST, almacenamiento y CLI simulados. `read_text` lanzó `PermissionError`; dos llamadas iguales devolvieron `sin_confirmacion`, con el mismo identificador, pero ejecutaron dos veces el runner: `COLA: estados= sin_confirmacion sin_confirmacion llamadas= 2 mismo_envio= True`. Código 0 de la reproducción. No se llamó Codex real.

**Arreglo:** distinguir primera creación (`FileNotFoundError`) de diario ilegible/corrupto. Ante los últimos, rechazar el envío y conservar el archivo; recuperación explícita, sin guardar encima. Añadir caso con reserva incierta y error de lectura que compruebe cero nuevos envíos y cero sobrescrituras. `tests/test_envio_publicacion.py:250` cubre incertidumbre, pero no este fallo de lectura.

### T2. AB entrega a la IA secretos presentes en los datos sin redactarlos

**Referencia:** `lienzo/creencias_revision_ia.py:383`, construcción del prompt. **Dueño:** AB, WIP.

Se serializan directamente propuestas, fuentes y candidatos. Si una evidencia contiene un token, cabecera Authorization o URL con credenciales, se incorpora al texto enviado al proveedor. Deshabilitar herramientas o quitar variables de entorno del hijo no elimina secretos que ya están en ese texto. El circuito de investigación existente dispone de redacción recursiva en `optimization_research.py:241` y siguientes.

**Confirmación aislada:** `consultar` y su parser reales, runner y directorio temporal simulados. Una fuente con `Authorization: Bearer V_41040_SENTINEL_NO_ES_SECRETO` llegó intacta a `stdin_text`: `AB: token sintetico presente en stdin_text= True`. Código 0. No se usó un secreto real ni hubo llamada de red.

**Arreglo:** reutilizar la redacción recursiva antes de enviar los tres conjuntos; redactar también texto/motivos devueltos antes de persistirlos. Mantener la evidencia original privada y declarar lo omitido. Probar cabeceras, claves, URLs, candidatos y eco de la respuesta.

## Hallazgos medios

### T3. El timeout de AA empieza después de una escritura potencialmente bloqueante

**Referencia:** `lienzo/prolog_servicio.py:69–71`. **Dueño:** AA, WIP.

`stdin.write` y `flush` ocurren antes de establecer el plazo. Si SWI/WSL deja de consumir una petición mayor que el pipe, se bloquea manteniendo el lock. Ni el timeout ni la cancelación se comprueban durante esa escritura; cerrar el servicio también necesita el lock.

**Confirmación aislada:** clase real con proceso simulado cuyo `write` demora 0,2 s. Con plazo de 0,05 s respondió correctamente después de 0,201 s: `SERVICIO: plazo=.05; duracion= 0.201 ok= True`. Código 0. No se lanzó SWI/WSL. El test vigente de timeout utiliza un mensaje pequeño y un hijo que sí lee stdin; no reproduce el pipe lleno.

**Arreglo:** un único deadline desde antes de iniciar/enviar, incluyendo escritura y flush; transporte con escritura acotada y cancelación efectiva que termine sólo el árbol propio. Probar hijo que no lee, payload mayor que el pipe y cancelación durante el envío.

### T4. Sin cursor se borra crudo que el investigador nunca leyó

**Referencia:** `lienzo/registro_niveles.py:119–132`; filtro de marcas en `research_creencias.py:177`. **Dueño:** I/S y coordinadora, política de retención.

La condición `proyecto NOT IN (...)` permite depurar capturas de más de 30 días cuando no hay cursor. Un proyecto cuyo investigador nunca arrancó por cuota o memoria puede perderlas antes de su primera lectura.

**Confirmación aislada:** función real sobre SQLite `:memory:` y resguardo vacío. Una fila antigua y otra nueva dejaron sólo la nueva: `RETENCION: sin cursor; filas borradas= 1 restantes= [(50,)]`. Código 0; sin base real.

**Matiz de contrato:** no es un desvío accidental de implementación: `.temp/resultados/2026-10-22-S/registro_niveles.propuesta.md` propone explícitamente «sin cursor, el corte de siempre», y `tests/test_encargo_u.py:22` lo espera. Sin embargo, contradice el pedido de Ariel citado en esa misma propuesta: no borrar crudo que todavía no se leyó o resumió. Debe resolverse esa discrepancia de política, no limitarse a cambiar el test.

**Arreglo:** proteger por defecto proyectos sin cursor, o documentar una excepción expresamente autorizada con una adopción inicial verificable. Comprobar primera ejecución y pausa prolongada. La ventana de investigación de 72 h tampoco prueba que todo lo anterior al cursor haya sido resumido; esa limitación ya está reconocida en la propuesta S.

### T5. La depuración del log puede perder escrituras concurrentes

**Referencia:** `lienzo/registro_niveles.py:184–192`; escritor `lienzo/state.py:203`. **Dueño:** I/núcleo.

El depurador copia hasta EOF y luego reemplaza el archivo. Un aviso agregado al original entre esos pasos no está en la copia y desaparece. El escritor no comparte un lock con esta rotación. Una ventana breve sigue siendo una carrera; el propio comentario del depurador la reconoce.

**Confirmación aislada:** función real con archivos virtuales `BytesIO`; se inyectó un append justo antes de `os.replace`. Resultado: `LOG: aviso agregado antes de replace conservado= False`. Código 0. No se rotó el log real.

**Arreglo:** protocolo de rotación y escritura con exclusión compartida, o escritor único que efectúe la rotación. Prueba determinista con barrera entre EOF y replace que conserve el aviso concurrente.

### T6. Respuestas HTTP tardías pisan consultas y turnos más nuevos de SSE

**Referencia:** `web/src/hooks/useLienzoData.ts:47–49`, manejadores SSE de consultas/rondas. **Dueño:** frontend/núcleo; Z consume ese estado para los avisos.

`loadConsultas` y `loadRondas` sólo comprueban `disposed`. Un GET iniciado al conectar puede resolverse después de un evento SSE más nuevo y reemplazar el estado actualizado. Por ejemplo, SSE libera A y concede B, y luego el GET antiguo restaura A en pantalla. Una consulta cerrada puede reaparecer abierta. La guarda de revisión del cargador principal no protege estas dos cargas.

**Evidencia:** orden de operaciones y setters en código; no se ejecutó navegador para este caso.

**Arreglo:** secuencia/revisión por dominio para descartar respuestas anteriores al último evento o petición aplicados. Probar GET diferido → evento SSE → resolución del GET, conservando el estado del evento.

### T7. El consumidor descarta eventos aunque aplicarlos falle transitoriamente

**Referencia:** `lienzo/hooks_eventos.py:723–729`. **Dueño:** núcleo de sesiones/coordinadora.

Después de capturar una excepción de `apply_event`, se llama igualmente a `_borrar_evento`. Si guardar una sesión falla por disco lleno o bloqueo transitorio, el evento válido desaparece y no se recupera al reiniciar. Se registra traceback, pero no queda el evento para recuperación; puede haber efectos parciales en memoria.

**Confirmación aislada:** consumidor real, filesystem y `apply_event` simulados; este último lanzó `OSError("disco lleno sintetico")`. Resultado: `HOOKS: apply_event falla; evento borrado= True`. Código 0; sin hooks reales.

**Arreglo:** conservar o poner en cuarentena el evento fallido y distinguir inválidos permanentes de errores transitorios. Reintentos con idempotencia, sin repetir ciegamente efectos parciales. Probar fallo de persistencia y recuperación con aplicación única.

### T8. Se devuelve éxito aunque falle la persistencia de turnos/restauración

**Referencia:** `lienzo/rondas.py:56–65`, concesión/liberación de turnos; `lienzo/restore.py:119–125`, `_store` y `forget`. **Dueño:** núcleo/coordinadora.

Ambos escritores capturan `OSError` y sólo lo registran. Los llamadores continúan como si hubieran guardado. En rondas se concede en memoria y se responde 200; tras reiniciar vuelve un dueño anterior o ningún dueño. En restauración, olvidar puede informar éxito aunque la entrada siga en disco y reaparezca al reiniciar.

**Confirmación aislada de rondas:** funciones reales, `atomic_write` simulado con `OSError`: `TURNOS: persistencia falla; HTTP= 200 otorgado= True error_en_respuesta= None`. Código 0. El caso restore se comprobó estáticamente, sin restaurar sesiones reales.

**Arreglo:** propagar el error y revertir la mutación, o mantener un estado explícito de persistencia pendiente que no afirme una concesión/olvido durable. Probar disco lleno, ausencia de notificación de éxito y recarga consistente.

### T9. AB puede emitir veredictos sin recibir el contenido de la evidencia adjunta

**Referencia:** `lienzo/creencias_revision_ia.py:53`, `_fuentes`, y `:383`, `consultar`; `lienzo/conocimiento.py`, `recibir_evidencia`. **Dueño:** AB, WIP.

Las fuentes enviadas son nodos. Una evidencia subida puede tener como texto sólo su nombre/caption, y en datos la referencia, hash y tamaño; el cuerpo vive en un archivo. La revisión no carga ese cuerpo. Con herramientas deshabilitadas, el modelo recibe `medicion.md` y metadatos, pero no las mediciones, aunque deba aceptar/rechazar según evidencia. Puede rechazar por falta de respaldo o aceptar sin haber visto el respaldo real.

**Evidencia:** recorrido estático desde recepción de adjunto hasta construcción del prompt. No se atribuye una respuesta concreta a un modelo. El recolector de investigación existente sí contempla lectura acotada de artefactos.

**Arreglo:** adjuntar contenido acotado, verificado y redactado de las fuentes pertinentes; registrar qué se leyó, hash y truncamientos. Si falta una fuente indispensable, resultado no evaluable en lugar de aceptación automática. Probar un cuerpo con información distinta del caption y comprobar su inclusión segura en el prompt.

### T10. Cambiar la identidad de un grupo remonta tarjetas y borra borradores

**Referencia:** `web/src/components/Board.tsx:1055`; claves en `web/src/components/ProjectStrip.tsx:137`; estado local de respuestas Ask. **Dueño:** Z, integrado en `595f056`.

Las tarjetas agrupadas cuelgan de `<section key={group.key}>`. La clave del grupo depende del mínimo de las identidades de sus miembros. Si entra otro miembro del mismo proyecto con una identidad menor, cambia la clave del padre: React desmonta todas sus tarjetas aunque sus session_id sigan iguales. Se pierde la selección/texto local de una pregunta pendiente. También cambiar el modo de agrupación cambia la estructura de padres.

**Escenario:** una tarjeta con borrador está sola en un grupo; se incorpora una sesión del mismo nombre de proyecto con otra identidad de repo que ordena antes. La clave cambia y el borrador se reinicia sin haber enviado la respuesta.

**Evidencia:** identidad de grupos, estructura React y estado local; sin ejecución de navegador. Las pruebas de layout/conteo no prueban conservación del borrador.

**Arreglo:** conservar identidad y ubicación React de las tarjetas o elevar el estado del borrador por sesión/pregunta fuera del grupo. Probar incorporación y retiro de miembros, resolución de repo_key y cambio de modo con respuesta sin enviar.

## Hallazgo bajo

### T11. Una prueba de rechazo de directivas sólo busca cadenas en el código

**Referencia:** `tests/test_prolog_motor_persistente.py:49`. **Dueño:** AA, WIP.

`test_servidor_no_acepta_directivas_en_archivo` comprueba que existe `read_term(` y no aparece `consult(`. No envía una directiva ni ejecuta el servicio. Una regresión que lea el término y lo ejecute mediante otro helper conservaría esas cadenas y el test seguiría verde.

**Arreglo:** prueba de comportamiento con archivo que contenga una directiva y efecto inocuo detectable en un temporal; comprobar rechazo y ausencia de efecto. Esto denuncia debilidad de la prueba, no demuestra que el motor externo ejecute directivas. No se modificó `motor-logico` ni se atribuye un fallo a ese proyecto.

## Mantenibilidad y hallazgos descartados

Se midieron módulos muy grandes: `server.py` 3.498 líneas, `sessions.py` 3.400, `conocimiento.py` 3.033, `xfer.py` 1.754, `browser_window.py` 1.575; UI: `RemoteBrowser.tsx` 1.187, geometría de flechas 1.106, `Board.tsx` aproximadamente 1.100 y `Card.tsx` 974. Estos tamaños encarecen revisión y aislamiento de efectos, pero no son un bug por sí solos y no suman hallazgos. Conviene extraer contratos de persistencia/transporte al corregir los casos concretos, sin una reescritura general para esta release.

El barrido AST de funciones Python de al menos 12 líneas, normalizadas y sin docstrings, encontró **0 grupos exactamente duplicados**. No mide duplicación semántica. No se declara código muerto sólo por falta de llamadas textuales: hay rutas dinámicas, hooks y extensiones.

Se descartaron sospechas al verificar protecciones existentes: handler HTTP con timeout de 30 s; comprobación de identidad de sesión antes de actualizar envíos; apertura de conexión en la recursión de propuestas. No se reportan la política LAN autorizada ni decisiones explícitas de producto como vulnerabilidades.

## Pruebas agénticas y revisión de esta entrega

Recorrido secuencial en esta sesión, con los skills `pruebas-agenticas` y `code-review`, sin subagentes:

1. **Explorer:** inventario de las cinco raíces, estado Git y dueños del WIP; lectura de encargos, contratos y revisiones previas.
2. **Analyser:** flujos de autorización, rutas, procesos, persistencia, retención, eventos y revisión delegada; separación de defectos respecto de políticas explícitas y trabajo incompleto.
3. **Designer:** escenarios adversos concretos y consulta de casos vigentes. Sin crear/aprobar baseline, requisitos o configuración ajena al alcance de sólo lectura.
4. **Executor:** barrido AST de Python sin errores de sintaxis; parser TypeScript instalado sobre **134 archivos TS/TSX/JS/MJS**, `syntaxErrors: []`, salida 0. Siete reproducciones aisladas mediante extracción AST de funciones reales: T1, T2, T3, T4, T5, T7 y T8. Todas devolvieron 0 porque sus assertions confirmaron el comportamiento defectuoso descrito, **no porque el producto haya pasado aceptación**. Dependencias y efectos externos se simularon; SQLite fue en memoria. T6, T9, T10 y T11 tienen evidencia estática, no ejecución integral.
5. **Detective:** contrastó reproducciones con pruebas existentes, revisiones AA/AB/Z y correcciones V anteriores; eliminó sospechas no sostenidas y separó el desacuerdo de política T4. Revisión final del único delta propio: documentación, sin cambios de código.

No hubo pytest focal, suite global, build, benchmark de memoria, mutación, ejecución de navegador, evaluación real de IA ni verificación de uso real del tablero en esta revisión. No se solicitó turno de build/suite/navegador porque no se utilizaron. No se aprueba release ni se afirma PASS de las compuertas agénticas. El veredicto es **riesgos concretos pendientes**, con dos de severidad alta.

Comprobación documental final: `git diff --check` devolvió 0 para los cambios versionados presentes; el informe nuevo fue leído para comprobar su escritura. Durante el cierre HEAD avanzó a `0505235b3d44c5878a6c5e937b49ad9b36f2c851` y AB dejó de figurar como WIP. Los hallazgos AB describen el contenido inspeccionado durante esta revisión; no se certifican otros cambios concurrentes posteriores.

ESTADO: revisión lista.
