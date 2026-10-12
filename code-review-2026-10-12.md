# Revisión: mover búsqueda de sesiones al menú contextual

Alcance: web/src/App.tsx, web/src/components/Header.tsx y web/src/components/Board.tsx.

Pedido: ubicar la acción de buscar procesos debajo de Lanzar CLI en el clic derecho del tablero y quitarla del menú lateral.

El callback rescan conserva el POST /rescan y su manejo de errores en App. Header deja de recibir la prop y Board la recibe obligatoriamente. El nuevo botón cierra el menú antes de invocar la acción. Se amplió el margen de posicionamiento para alojar dos filas. Se agregaron estilos propios en web/src/styles.css para un menú vertical con fondo, borde, sombra y selección; se agregó navegación ArrowUp/ArrowDown/Home/End, cierre con Tab y prevención del menú del navegador dentro del menú. Enter usa la activación nativa del botón y Esc conserva el listener existente. No hay cambios de backend ni dependencias.

Revisión estática del diff: sin hallazgos pendientes dentro del alcance. Build y lint ejecutados con el runner agéntico: código 0. Comprobación Chromium sobre el build nuevo: orden de opciones, ausencia en el menú lateral, posición dentro del borde inferior derecho, cierre y aviso; un POST interceptado, sin barrer procesos reales. Un intento previo observó el build anterior porque la compilación del runner aún no había terminado; no se alteró el script para obtener el resultado posterior.

El recorrido agéntico reutiliza los casos frontend vigentes. No se aprobaron baselines ni mutaciones. La compuerta no acredita PASS global: la evidencia de mutación existente corresponde a otro estado. La prueba puntual utiliza interfaz y servicios reales con /rescan interceptado; la batería existente utiliza fixtures, no acredita interacción con procesos reales.

## Frente B: Caveman breve / RTK / Jev

Revisión focal del código nuevo agent_*, jev*, sus operaciones y pruebas; de los hunks propios de launch.py, server.py, conftest.py, Board.tsx, Panel.tsx, Launch.tsx, AgentImprovements.tsx y styles.css. Los cambios de títulos/copycat de A se conservan sin atribuir su revisión a B.

Hallazgos propios corregidos: contrato Jev criteria (no options); bloqueo de redirecciones para no reenviar Authorization; validación finita de respuestas/costo y rechazo de clave malformada; datos ausentes como desconocidos; consulta sobre snapshot revisado; protección contra doble envío y respuesta tardía; costo visible si falla persistencia tras cobrar; configuración Codex propia de WSL en vez de Windows; argumentos cmd literales, sin metacaracteres, sin pérdida silenciosa por cp1252 ni longitud excesiva; timeout de configuración no bloquea el lanzamiento y muestra aviso. La revisión visual corrigió el color del título de dialog y la disposición de checkboxes.

Sin hallazgos propios abiertos dentro de este alcance. Validación: 1463 backend completos antes de refinamientos, 78 focales finales, 135 UI existentes, 4 UI nuevos; persistencia con UI/Handler reales aislados; cmd.exe sintético real; RTK conserva códigos 0/7 y salida original; Jev real USD 0.00002268. Build, ESLint y Ruff sin errores; diff sin errores. Evidencia y límites en docs/specs/evaluador-harness/verification.md.

Pendientes reales: integración/reinicio por coordinación; baseline y mutaciones humanas (sin PASS global); no medir ahorro/obediencia/calidad sin sesiones comparables. WSL no recibe automáticamente el RTK de Windows. La respuesta Jev es hipótesis, no aprobación ni validación del código. No se añadieron dependencias Python ni hooks globales.
## Frente B: scheduler y memoria (2026-10-12)

Verificación final ampliada: 241 pruebas backend/server/peer/salud pasaron en 45.99 s (incluye 31 del área); 5 UI. Ruff/diff sin errores. Se corrigió una condición adicional: una sesión sin alive/state conocidos también bloquea el análisis. Evidencia integration.log. No equivale a PASS de aceptación: ESCALAR permanece.

Alcance autorizado focal: optimization_activity/queue/memory/scheduler.py, OptimizationScheduler.tsx y sus pruebas; hunks propios de server.py, App.tsx, AgentImprovements.tsx y test_agent_improvements_api.py. Revisión de datos, SQL, auth/CSRF, exclusión concurrente, persistencia, pausas, estados desconocidos y respuestas UI tardías. Sin dependencias nuevas ni cambios de títulos/launch/A.

Hallazgos corregidos: cierre explícito de conexión SQLite; espera/progreso SQL acotados; foreign_keys activos; restaurar estado en memoria si falla persistencia; singleton y tick exclusivos; dos muestras de recursos; ejecuciones interrumpidas requieren revisión; plazo de pared por trabajo, con muestra parcial sin reintento; UI invalida lecturas tardías ante escritura/cierre; contexto de PC/modelo desde sesión citada sin copiar prompts. Consultas parametrizadas, archivo operacional fijo, proyecto validado, escritura local+CSRF y actividad remota autenticada; sin ruta de comandos/pagos. Datos corruptos/fallas se muestran o detienen el scheduler con log.

Checks: 30 backend del área, 5 UI, UI/Handler/memoria reales temporales, Ruff/ESLint/build y diff. No auditoría de dependencias global ni afirmación de PASS agéntico: compuerta ESCALAR por aceptación pendiente. No mutaciones sobre árbol compartido.

Pendientes de diseño/alcance explícitos: análisis oportunista inicial requiere encolado manual y propone RTK/CodeGraph desde incidentes, no aprende causalidad ni ejecuta experimentos. Señales desconocidas bloquean (incluye OS sin adaptador de inactividad); no límite duro si se cuelga el SO. CLI/Jev automáticos deshabilitados; USD 5 autorizados pero sin ledger/adaptador que imponga costo máximo, esperar verificación por coordinación. Otra activación coordinada para backend; comparar calidad/consumo OFF/ON antes de recomendar perfiles. No se marcan tareas/baselines completados.
## Frente B: ledger y adaptadores, presupuesto USD 2

Revisión focal de optimization_budget/cost.py, ops/comparar-rtk.py/verificar-cota.py y hunks propios de jev.py, agent_suggestions.py, scheduler y UI. SQL parametrizado, Decimal finito, autoridad única, transacción exclusiva, reducción persistida, historial idempotente, errores/estados inválidos bloquean, sin saldo réplica ni ejecución remota. La guardia está en decide, incluye el script de prueba; no modificar clave compartida ni tomar estimación .001 como límite. No nuevas dependencias.

Hallazgos corregidos en revisión: conciliar costo confirmado antes de rechazar respuesta semánticamente inválida; retener reserva y bloquear siguiente envío ante timeout/fallo de conciliación; exceder cota bloquea proveedor aun debajo de total; no incrementar saldo con política vieja; leer sesiones/permisos reales en script OFF/ON (state del proceso estaba vacío); usar subproc existente para evitar nietos huérfanos tras timeout. Se excluye cualquier CLI sin cota/pausa segura y no se presenta ensayo de shell como obediencia/calidad del coding agent.

Evidencia: 51 backend, 5 UI y ledger/Handler/UI temporal real. Prueba --run local registra bloqueo por agentes/permisos; cero inferencias pagas. GET límites real sin secretos mostró cap compartida50, no2. RUFF/ESLint/build pasan; compuerta no certifica PASS sin aceptación. Pendientes reales: activar ledger mediante coordinación, histórico HTTP400 sin monto confirmado, cota contractual/proveedor y ensayo en quietud. Total autorizado reducido a2 en transcripción línea1663. No reinicios, git ni tareas/baselines completados.
## Cierre frente B: observaciones de integración A corregidas

Revisión de review-integracion-AB.md de A y cambios propios: se separó status del ledger transaccional; GET usa mode=ro sin CREATE/INSERT, Queue no guarda desde constructor, Budget no repara ni aparta peer corrupto. Inicialización/recuperación solo en start. Caso focal y2 checks posteriores prueban bytes/mtime y ausencia de archivos nuevos. auth.py no tocado.

Se cerró ventana sources→propose con revalidación de actividad/pausa; se conserva cursor/resultado confirmado si vuelve usuario durante transacción. Autoencolado local circular por proyecto/versión, solo incidentes (no decisiones generadas), cooldown120s y máximo100; pago/agentes siempre bloqueados sin cota. UI muestra origen y fuentes. SQL parametrizado y sin nuevos comandos arbitrarios/dependencias. Verificación69 focal,2 casos afectados finales, UI real temporal, lint/build/ruff. No afirmar máximo físico de pausa: el host no estuvo apto para medirlo; no ahorro/experimento de agente. Baseline intacto, no mutaciones concurrentes. Detalle y pendientes reales en handoff-B-final.md.
## Última aceptación: permisos vigentes y OFF/ON diferido

Se corrigió bool(state.pending) que bloqueaba por3registros expirados reales. Filtro puro por expiry/session:19casos de actividad, sin decisiones/historia alteradas. Se añadió encargo integrado a cola, no automatización externa: opcode fijo, proyecto local validado, no reemplaza análisis activo, creación de metadata atómica, comandos pytest fijos/argv sin shell, manifiesto congelado, procesos propios limitados por subproc, pausa por frontera, evidencia local/memoria y revisión ante fallo. No CLI/modelos/cargos. Tope2 y proveedor sin cota quedan bloqueados.

Muestras/oráculos revisados y aprobación140806 aplicada a baseline propio2casos/propuestas; ambas baterías80tests código0, solapadas, runner completo; UI5, lint/build/ruff. Modulos añadidos/cambiados: optimization_activity, optimization_experiment (nuevo), optimization_memory/scheduler/queue, ops/comparar-rtk, OptimizationScheduler.tsx y tests activity/experiment nuevos. Fuente de veredicto final: resultados/scheduler/compuerta.md. No suponer PASS: mutaciones no aprobadas, host no quieto para ensayo de agentes/latencia real. Se distinguió Git bloqueado por sandbox de Git real y se evita cambiar fuente tras validación final. Sin auth/títulos de A, git escritura ni restart de B.

## Revisión de coordinación para publicación

Se contrastaron los informes con fuentes y logs locales. Auth elimina autorización desde caché por timestamp: la reproducción pasó de nueve fallas a los mismos trece casos aprobados; focal 68 y backend 1550 aprobados, sin relajar el oráculo ni modificar el baseline previo. El costo explícito es releer el archivo de sesiones en cada comprobación. Review detallado de A conservado en resultados/coordinacion-A/auth-fix-review.md.

Los títulos ya no ejecutan el helper sobre la misma firma de SID/PID/tarea: el intento se registra antes de llamar, los fallos permanecen visibles y no generan un bucle de reintentos. La revisión verificó argumentos como lista, validación del agente por PID y ausencia de inyección de teclas en el cambio de título. Launch incluye overrides separados de título y notificaciones para Codex en Windows/WSL y resume. A reportó 147 focales aprobadas para este refinamiento. La pausa temporal de diagnóstico fue retirada.

Coordinación verificó health y carga del scheduler/presupuesto; tres GET conservaron bytes/mtime de ledger y peers. Permisos vencidos se filtran sin decisiones nuevas. El trabajo OFF/ON usa comandos locales fijos, huellas de fuentes, timeout de procesos propios y evidencia explícita; no representa un benchmark de agentes ni ahorro de tokens. La referencia propia del scheduler y sus artefactos aceptados se versionan; no se incluyen logs, credenciales ni el análisis previo .rea-review.

La regresión de resume mantenía una tarjeta viva como muerta cuando SessionStart reutilizaba su ID. A corrigió esa transición preservando estados activos y controles de eventos viejos, con cuatro regresiones y 151 focales aprobados. El bloqueo real «otra app» del primer relevo se recuperó mediante R y se devolvió el encargo pendiente. No se usa cierre de turno como prueba de que todas las tareas terminaron; se detuvieron los restantes relevos.

Límite de aceptación: compuerta ESCALAR por mutaciones no medidas. No se cambian umbrales ni se declara PASS general para publicar. Los modelos pagos permanecen bloqueados por falta de cota y un cargo histórico desconocido. No se afirma que todas las sesiones antiguas ya se hayan retomado.

## Corrección tras ensayo manual RTK

La prueba real detectó ON=124 y OFF=0. Se verificó la ayuda del binario y se sustituyó el argv incompatible de rtk pytest por ejecución del intérprete fijado seguida de rtk pipe --filter pytest. No hay shell ni comandos recibidos del usuario; ambos perfiles usan los mismos tests. stdout original se conserva y el código del comando tiene prioridad sobre el filtro, que también puede hacer fallar el caso. Timeout y eliminación se limitan al árbol propio del subprocess.

La renovación de una tarea pendiente exige una solicitud explícita, estado queued y cursor cero: no se cambian las fuentes de un ensayo iniciado/pausado. Se revisaron esas condiciones y sus regresiones. 23 tests aprobados, Ruff aprobado y runner completo igual al baseline. Ensayo real posterior: ambos códigos cero, 533→26 caracteres, fuentes intactas y USD0 servicios. No se deduce ahorro de tokens/calidad de un agente. Sin hallazgos bloqueantes en estos hunks; no se oculta el timeout previo ni se actualizó baseline para taparlo.
