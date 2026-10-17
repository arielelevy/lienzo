# Revisión de integración Codex / Claude

## Adenda de coordinación — ronda A–E, activada a las 19:43

Revisión de los cambios de esta ronda y su integración, conservando las revisiones históricas.
Se contrastaron los cinco informes con el árbol y la ejecución global, sin sumar suites solapadas.
Corregidos: identidad de cola desligada del PID; asignación por proximidad temporal; bloqueo del primer
prompt de una CLI nueva; pérdida de informes al retirar/reemplazar/purgar reglas o alcanzar el cupo;
memoria sin restaurar ante fallo de persistencia; regresión de `dedupe=false`; metadatos opcionales
ausentes emitidos como claves inventadas; dobles de transporte incompatibles con identidad comprobada.
El envío incierto del hilo anterior se conserva separado y no se reenvía al nuevo.

Los acuses nuevos son acciones explícitas del usuario PC/LAN y rechazan el túnel. El servidor resuelve
el destino: un UUID aportado por el cliente no autentica a un agente. Recibido e integrado permanecen
separados; una regla inactiva conserva y muestra sus informes. Las consultas externas agregadas no
exponen prosa, rutas ni transcripciones. La evidencia verificada de controles es una declaración con
persona/referencia, no una comprobación automática de identidad o calidad.

Verificación final: corrida `2026-10-17T22-32-46.991Z-37680`, estado `4fa8609f21cb945a`;
7/7 casos código 0, backend 2244 aprobadas/3 omitidas, UI 136 aprobadas; prueba UI adicional de
acuse explícito aprobada. Ruff focal, ESLint, build y pruebas Node correctos. Inventario de 32 fuentes
y pruebas sin diferencias durante la corrida. Compuerta 3, ESCALAR: `mutacion.json` pertenece a otro
estado. Sus 5/6 históricos no se cuentan como medición actual. No hubo --fijar ni --aceptar.

Activación: reinicio por wrapper, health OK, siete PID ajenos a esta ronda conservaron proceso y tarjeta;
PUT de coordinadora al chat Desktop devolvió true y GET lo confirmó, con codex_queue disponible.
Vista externa viva: nivel 3, 18 grupos, sólo nivel/proyecto/actividad. Un sondeo de identidad incompleto
se rechazó explícitamente; una lectura posterior comprobó la identidad sin enviar mensajes ni forzarla.

Límites abiertos: transición real /new y /clear, atomicidad consulta/cola, costo del sondeo, continuidad
formal con coordinadora ocupada/quieta, mutaciones vigentes, nuevas aceptaciones y calidad causal del
investigador. Sin auditoría global de dependencias ni métricas de complejidad no medidas. No se cierra
el backlog ni se declara PASS formal. Evidencia y roles en
`.temp/coordinacion/2026-10-17/backlog-codex/raiz/`; logs globales en `pruebas-agenticas/resultados/`.
Las adendas documentales se escriben después de medir; las fuentes de ejecución permanecen idénticas.

Cambios concurrentes de coordinación frontend observados: `nl.ts`, su test y comentario de SendBox
se editaron a las 19:37, antes de las etapas frontend de la corrida global; no se atribuyen al frente
A–E ni al inventario inicial de 32 archivos. Revisión focal separada en
`code-review-2026-10-17-codex-coordinadora.md`. Raíz ejecutó además los dos casos nuevos de Codex
CLI/Desktop con salida exclusiva `.playwright-raiz-coordinadora`: ambos pasan. La prueba nueva
`test_ronda4_a_continuidad.py`, creada después de la global, se verificó por separado: 5 pasan.
No se suman esas corridas ni las fallidas de la otra sesión al resultado global de raíz.

## Adenda R — permiso coordinadora Codex Desktop

Revisión focal autorizada por Ariel. lienzo/server.py permite el rol de coordinadora a una tarjeta Codex Desktop sólo si ses.puede_enviar confirma transporte; la revocación no necesita una cola disponible. Conserva validación del cuerpo, unicidad por repo y bloqueo de acciones de consola para externas. tests/test_codex_desktop_coordinator_R.py y regresiones existentes: 26 passed. Ampliada: 49 passed y 5 failed; las mismas cinco fallas de reserva de cola se reproducen con función anterior en memoria (25 passed, 5 failed). No se afirma verde global. Runner focal ejecuta código 0, salida 1 por baseline ausente; compuerta 2, no PASS. Sin nuevos hallazgos propios; activación coordinada pendiente. Evidencia y cinco roles en .temp/coordinacion/2026-10-17/coordinadora-desktop-R/informe.md.

Alcance: cambios del transporte Codex y publicación de capacidad/estado para este release. Revisión estática focal de la coordinadora; no es auditoría de todo el árbol compartido. Fecha: 2026-10-17.

## Hallazgos pendientes de corrección y verificación

1. Alta: reserva concurrente de envío. `codex_queue.enviar` guarda estado `pendiente` y libera `_lock` antes del subproceso, pero la deduplicación no incluye ese estado. Dos llamadas concurrentes pueden ejecutar la cola dos veces. Encargado a D: reserva atómica y caso con barrera que pruebe una sola invocación.
2. Alta: resultado incierto tras timeout. Un timeout no demuestra que Codex no haya encolado. El código actual clasifica todo código no cero como rechazado y permite otro intento. Encargado a D: conservar incertidumbre visible, confirmar contra rollout y no duplicar por reintento ciego.
3. Media: ventana de duplicados de 60 s menor al plazo de confirmación de 600 s. Un envío en curso puede repetirse antes de confirmar el primero. Encargado a D: separar envíos en curso de repetición intencional de entregados.
4. Media: publicación incompleta. La capacidad `envio` no llega por GET /sessions ni snapshots/eventos. Debe calcularla la PC dueña y conservarse en el espejo sin evaluar PID remoto como local.
5. Media: confirmación sin sondeo. `confirmar()` existe pero no se consulta periódicamente. Encolado no evoluciona por sí solo en la tarjeta. Encargado a D: sondeo acotado y publicación de cambios.
6. Media: estado de entrega ausente en UI. `envio_codex` existe en backend, pero no en tipos/tarjeta. La capacidad de enviar no equivale a confirmar el último envío. Encargado a D: estado y motivo accesibles, actualizados por eventos.
7. Alta para pruebas: falta guardia global que impida invocar codex.exe real desde tests ajenos al transporte. Encargado a D: fixture automática con reemplazo explícito en casos focales.
8. Alta: la UI impide usar el transporte. `names.ts:canWrite` exige consola y `SendBox.tsx` rechaza toda tarjeta external/no_console, aunque el servidor declare envío por cola. El toast dice Enviado incluso si sólo se encoló. Encargado a D: habilitar composición según capacidad sin habilitar kill/Esc/acciones de consola; estados de respuesta fieles y recorrido UI completo de envío.

## Evidencia recibida

- A: `.temp/coordinacion/2026-10-17/informe-A-codex-queue.md`, 2022 passed y 3 skipped reportados; cinco mutantes muertos y control vivo, prueba real quieto/ocupado/especiales/duplicados. No se repitió la suite por esta revisión. Runner 1 por baseline ausente, sin PASS certificado.
- C: `.temp/coordinacion/2026-10-17/informe-C-desktop.md`, UI y detección entregadas; integración backend real pendiente.
- Claude: autenticación de hijo documentada; entrega por pipe desde Lienzo todavía sin demostrar. Prueba aislada en curso, sin aprobar transporte productivo por observar sólo una conexión.

Actualización de evidencia Claude: `claude-pipe-prueba/verification.json`, `integration-result.json` e `integration-bootstrap-result.json` fueron leídos por la coordinadora. Acreditan mensaje peer y ACK exactos en sesión propia, rechazo HTTP 403 para credencial inválida, bootstrap con identidad Windows verificada y cierre del adaptador. No acreditan aún Desktop ni integración en Handler/launch. Desktop pidió autorización directa del usuario y no ejecutó el comando; listener de ese ensayo cerrado.

Revisión preliminar de módulos Claude: se pidió y se incorporó disponibilidad por heartbeat (Event de registro solo era insuficiente), proceso dueño fijado mediante handle/FILETIME, timeout/parcial como resultado incierto y validación de JSON objeto. El bootstrap revisado usa DACL del usuario, rechaza clientes remotos y valida PID cliente/ancestros/orden de creación contra registro de sesión antes de transferir la credencial de enlace. Falta comprobar el corte final, pruebas del consumidor productivo y registro Desktop autorizado.

No se ejecutan nuevas mutaciones ni se aprueban baselines en esta revisión. Los hallazgos se mantienen pendientes hasta contrastar corrección y evidencia. No se completan tareas de PENDIENTES.md.

## Indicador de release solicitado durante la integración

Delta focal revisado: ReleaseBadge.tsx, ReleaseBadge.css y dos líneas en App.tsx; versión importada de web/package.json (0.1.0), sin nuevo endpoint ni duplicar número. Texto con nombre accesible, contraste con variables existentes y sin eventos/entrada de usuario. Posición inferior izquierda, con separación de cuotas en ancho de 320 px. Captura móvil leída visualmente. No se encontraron problemas pendientes en este delta.

Pruebas agénticas secuenciales registradas en resultados/release-badge/roles.json. Un caso de versión/ubicación mide 1440 y 320 px; las dos pruebas Playwright terminaron en código 0. Config válida 0; ESLint focal 0. Runner y compuerta 1 por baseline ausente, sin referencia fijada ni PASS de aceptación. Primer error móvil conservado: helper abrirTablero esperaba la primera tarjeta, oculta en esa pestaña móvil; se sustituyó por preparación de fixtures y espera de los elementos que el caso verifica. Primer intento restringido: Error: spawn EPERM, seguido de ejecución escalada autorizada. Sin build/dist ni reinicio todavía.

## Adenda de coordinación — arranque y revisión general

La revisión de diseño de TODO Lienzo está en `.temp/coordinacion/2026-10-17/revision-diseno-simplificacion-release.md`: inventario de 327 archivos, con cobertura y límites detallados. B1 (degradación de entrega Claude), B2 (falsa confirmación en coordinar.enviar_seguro) y B3 (SSE expulsado que conserva pings) bloquean el corte hasta corrección y evidencia. F está aplicando correcciones tras el pedido directo de Ariel; no se acepta el release por recibir el informe ni por inspeccionar cambios en disco.

Durante la prueba autorizada, Claude Desktop pidió POST /restart al principal a las 13:13:08. El proceso no se relanzó. El arranque directo reprodujo `ModuleNotFoundError: No module named 'lienzo'` en claude_pipe_bootstrap.py. La coordinadora corrigió el import a `import procinfo` y el import del adaptador al módulo plano, conforme al entrypoint del proyecto. `py -3.14 lienzo/server.py --help` devolvió 0; luego se restauró el principal en 7321 con sesiones/reglas cargadas. Esto es recuperación operativa, no aceptación ni activación certificada del release.

Regresión nueva `tests/test_server_entrypoint.py`: subproceso desde carpeta temporal, sin PYTHONPATH, sólo --help; 1 passed, código 0. Runner bridge/bootstrap posterior al cambio: 8 + 6 passed, casos 0, corrida `2026-10-17T16-15-49.216Z-32416`; runner 1 sin baseline. Ruff sobre bootstrap, adaptador y test nuevo: 0. Un comando inicial de lint incluyó por error un archivo TypeScript en Ruff y produjo errores de sintaxis; se corrigió el comando sin cambiar producto por esos errores. ESLint del archivo TypeScript correcto: 0.

F1 de acciones.spec.ts: fixture de configuración cambia por fase explícita del escenario en lugar de cantidad de GET; montaje StrictMode no adelanta la configuración. Se conserva barra oculta→visible tras refresco→visible con GET 502 observado. Chromium 1 passed, caso 0, runner 1 sin baseline (`config-refresh`, corrida `2026-10-17T16-13-16.370Z-44452`); cinco roles registrados. Falta corte UI conjunto. No se modifica configuración real, permisos ni hooks.

Autorización Desktop verificada en transcript local: sesión `0e35e62f-b3cd-4c1c-9fef-40903126964d`, user origin.kind human, `2026-10-17T16:11:22.668Z`, Claude 2.1.299. La API la clasifica como batch aunque el registro vinculado al PID declara claude-desktop: D recibió diagnóstico y debe corregir la fuente/merge de clasificación; no debilitar _owner ni usar una tarjeta artificial como evidencia integrada.

Actualización verificada 13:31: clasificación ya publicada `claude-desktop` vía registro. Ariel ejecutó directamente en Desktop el bootstrap nuevo. GET /sessions confirmó capacidad claude_pipe; UNA llamada HTTP principal /send produjo un user peer con msg_id exacto y un ACK exacto, ambos contados 1. GET posterior publicó ese UUID como entregado, confirmacion_final=true. Fuente: `.temp/coordinacion/2026-10-17/verificacion-tablero-desktop.md` y `claude-pipe-prueba/desktop-tablero-real-result.json`. Es prueba integrada real de API/transporte/confirmación, no sólo self-test ni tarjeta artificial. No acredita click UI, compatibilidad futura o ausencia de restricciones de cuenta. Rechazos automáticos previos respetados; sin cambios de permisos ni reintentos del mismo mensaje.

## Corte 0.2.0 para publicación autorizada

Se contrastaron el delta y la evidencia final de F (`informe-F-correcciones-diseno.md`, 367 backend +13 UI) y D (68 focales): B1/B2/B3 corregidos, también P1-P5 y rechazo de enlaces existentes de P6. Se revisaron el helper común de merge, reservas bajo lock, cierre SSE, cleanup SQLite, restauración conservadora y preservación de UUID/incertidumbre; no se identificó otro bloqueante en esos cambios. El límite TOCTOU de copias queda explícito. Las afirmaciones históricas pendientes anteriores se conservan fechadas; esta adenda documenta su disposición final.

Build 0.2.0 y ESLint global: código 0. Los cinco archivos de pruebas Node terminaron 0; resumen del runner Node: 9 tests, 0 fallas, además de asserts propios impresos por scripts legacy. Vite conserva un aviso de chunk mayor de 500 kB, sin error. Diff --check 0. El escaneo de patrones de secretos sólo encontró fixtures de PRIVATE KEY deliberadamente falsos en tests, no claves privadas reales.

Por pedido posterior de Ariel de simplificar/omitir rondas agénticas y publicar, la corrida global `2026-10-17T16-37-12.339Z-45120` se interrumpió antes de obtener resultado completo. No se convierte esa corrida en verde ni se fijan baselines. El prototipo de auto-conexión iniciado por D se conservó íntegro en `.temp/coordinacion/2026-10-17/automatizacion-diferida`; el hook de producción coincide con HEAD y ese trabajo no entra en 0.2.0.

Revisión focal D posterior: external_of_row centraliza registro validado PID/FILETIME y sweep delega; merge permite reemplazar sólo fallback batch/comando sin runner, mismo proceso, por registro Desktop. Orquestadores y procesos distintos quedan protegidos. _owner intacto. Seis regresiones B1 mantienen entregado y prompt frente a respuesta tardía. 68 pruebas focales y Ruff0; recorrido de cinco roles en resultados/clasificacion-desktop-D/roles.json. Sin hallazgos nuevos dentro del delta. Falta corte conjunto y ensayo desde tablero: self-test Desktop separado pasó; segundo ensayo D fue bloqueado Auto-Mode Bypass, no se envió marcador ni se certifica endtoend con tarjeta construida.
