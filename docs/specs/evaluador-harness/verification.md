# Frente B: entrega revisable

Registro histórico del 2026-10-12. Sus estados, importes y autorizaciones corresponden a esa ronda;
no son un estado operativo verificado hoy ni una autorización nueva.
Contrato actual: [Aprendizaje](../../APRENDIZAJE.md). Las specs intermedias citadas en el cuerpo
se retiraron al consolidar; sus versiones originales permanecen en Git.

Fecha: 2026-10-12. Sin add, commit, push, reinicio del servidor principal, aprobación de baseline ni tareas marcadas completadas.

## Cambios

- Caveman breve: perfil original inspirado en las reglas inspeccionadas, añadido al lanzamiento sin proxy ni compresión de archivos. Se conservan instrucciones de usuario/proyecto, idioma, comandos, errores y pruebas.
- RTK: 0.51.0 instalado en LIENZO_HOME/bin, ZIP oficial verificado con SHA-256 1623e9b45d28b15122d69e7314776e1123a804224885ce07e7182fb40080f05c. Uso explícito por ruta absoluta; sin hooks globales.
- Preferencias breve/RTK activadas en esta PC. UI para desactivar o volver a activar en nuevas sesiones.
- Jev: credencial de Chesstudia transferida a DPAPI del usuario. Cliente stdlib con modelo fijo, límite de entrada, timeout, sin redirecciones ni reintentos; enum y probabilidades validados, costo obligatorio.
- Panel «Mejoras»: muestra alcance, datos ausentes, errores/resultados, duración y consumo reportado. Las sugerencias locales citan turnos/herramientas. Jev recibe solo métricas/referencias visibles tras autorización de una consulta; una muestra cambiada se rechaza antes de pagar.
- Sesiones remotas: consulta a la PC dueña, error explícito si no responde. Resultados tardíos no cruzan entre tarjetas.

## Archivos propios

- Nuevos: lienzo/agent_improvements.py, agent_evaluation.py, agent_suggestions.py, jev.py, jev_credentials.py.
- Modificados: lienzo/launch.py y server.py; tests/conftest.py solo para aislar LIENZO_HOME real.
- UI: web/src/components/AgentImprovements.tsx nuevo; Board.tsx, Panel.tsx, Launch.tsx y styles.css.
- Ops: importar-jev.py, preparar-mejoras.py, probar-mejoras.py.
- Pruebas: ocho archivos Python nuevos y web/tests-ui/mejoras.spec.ts; config pruebas-agenticas/mejoras.json.
- README, spec y revisión. Los cambios de copycat/títulos del frente A en archivos compartidos se conservaron, no se desarrollaron en B.

## Evidencia medida

| Comprobación | Resultado |
|---|---|
| Backend completo | 1463 pasaron en 208.02 s; anterior a refinamientos finales, luego revalidada el área afectada |
| Runner focal final | 78 backend + 4 UI pasaron; código 1 por baseline ausente |
| UI existente | 135 pasaron; runner existente código 0 |
| Build, ESLint, Ruff, diff --check | Sin errores; Vite conserva aviso de bundle >500 kB |
| UI + API reales aisladas | Preferencia guardada y conservada al reabrir; sin rutas interceptadas, sin agentes ni Jev; captura inspeccionada |
| RTK real | Salidas sintéticas con códigos 0 y 7 conservados; proxy recupera stdout original y diagnóstico de fallo |
| cmd.exe real | Lector sintético recibe instrucciones como un único argumento literal; no se lanzó agente |
| Configuración Codex en vivo | Resueltas 6 rutas en WSL Ubuntu; config de usuario presente; argumentos nativos construidos sin mostrar instrucciones |
| Jev real | typesafe/jev-1.13-20260917; 540 tokens entrada, 75 salida; USD 0.00002268; datos_insuficientes |
| Servidor principal | GET /agent-improvements devolvió 404: código nuevo aún no cargado; no se reinició |

No se suman pruebas solapadas como si fueran casos adicionales. Evidencia: pruebas-agenticas/resultados/mejoras/, incluidos intentos fallidos conservados, roles.json, historial.db, rtk-real.json, jev-real.json y preferences-real.png.

## Veredicto y pendientes

Los casos ejecutados pasan. La compuerta nueva devuelve «No hay baseline.json»: no hay PASS certificado. Hay tres mutaciones propuestas, no aprobadas ni ejecutadas. Ningún baseline se fijó.

La coordinación debe integrar y decidir el reinicio del servidor principal. Los agentes abiertos no se modificaron. RTK en Windows no acredita instalación en WSL; si falta, el lanzamiento muestra aviso y conserva el agente. No se midió obediencia de agentes reales, ahorro económico ni mejora de calidad; Jev solo comprobó conectividad/contrato.

El primer pedido real Jev devolvió HTTP 400 por usar options en vez de criteria; se corrigió y se obtuvo el resultado informado. No hubo costo informado para el intento fallido, por lo que no se declara gratuito.
## Frente B: activación y scheduler, 2026-10-12 13:10

Actualización final 13:16: batería ampliada de integración: 241 pruebas pasaron en 45.99 s, incluyendo las 31 del área y las rutas existentes/server/peer/salud. Log resultados/scheduler/integration.log. UI: 5 pasaron; UI/Handler reales aislados inspeccionados. No sumarlos con los 30 previos como casos distintos. Code review corrigió también el bloqueo ante sesión de vida desconocida. Sin procesos de prueba ni escrituras pendientes; punto seguro para una activación coordinada. GET scheduler principal 404 medido a 13:13:49. B no hizo reinicios, git add/commit/push ni cambios en launch/títulos de A en esta extensión.

Activación realizada por coordinación, no por B. UI real observada a 13:00: brief/RTK checked, RTK disponible, pestaña de sesión Mejoras y Jev deshabilitado hasta consentimiento. GET health, agent-improvements y session/improvements: 200. Cero escrituras durante esa observación, cero llamadas pagas. Capturas: resultados/mejoras/activation-live.png y activation-session.png; respuestas activation-live.json. Conserva el checkpoint anterior 404 como histórico.

Scheduler implementado localmente: optimization_activity.py, optimization_queue.py, optimization_memory.py, optimization_scheduler.py; memoria existente, hipótesis decision/propuesta con vínculo motivada_por, contexto conocido/desconocido, vigencia y rollback, evidencia del análisis. Cola por proyecto de esta PC, 100 entradas máximo, hasta 30 fuentes, plazo cooperativo 30 s, consulta SQLite 1 s/espera 250 ms; no límite duro ante bloqueo del SO. Pausa al retornar usuario; desconocido, agentes ocupados y permisos pendientes bloquean. Nunca llama a Jev ni lanza agentes; no autoveredicto, autoaprobación ni bucle de reencolado. Cola inicialmente vacía, encolado explícito desde UI.

Integración compartida: server.py import/rutas GET+PUT scheduler/start; App.tsx hook de actividad, AgentImprovements.tsx panel hijo. Nuevos OptimizationScheduler.tsx y cuatro test_optimization_*.py; test_agent_improvements_api.py ampliado; mejoras.spec.ts ampliado. Archivos de A, títulos y launch se preservan. La pausa tras reinicio exige revisión; no reintento. Resultados vivientes en la base existente, no una segunda memoria.

Verificación final del área: 30 backend (log resultados/scheduler/backend.log), 5 UI (Playwright); ESLint, build y Ruff sin errores, aviso Vite de bundle >500 kB. UI/Handler/memoria reales aislados: encolar/persistir/pausar, cero servicios/CLI, captura resultados/scheduler/real-ui.png y JSON. No usar esta evidencia como experimento OFF/ON.

Recorrido agéntico secuencial: propuestas blueprint/requisitos/casos validan; config valida (aviso de mutaciones ausentes). Runner registra explícitamente NO EJECUTADO para aceptación nueva, compuerta ESCALAR. Falta aceptación humana de casos/baseline/mutaciones; no se aprobaron referencias. Un intento UI falló por mock incompleto de la nueva ruta; corregido el aislamiento, 5/5 posteriores, no etiquetado como inestabilidad medida. Primeros tests/build/Chromium bloqueados por sandbox; reejecución autorizada, sin confundir errores de entorno con defecto.

Requiere otra activación coordinada del backend para cargar scheduler: B no reinició ni cerró sesiones. El build de UI ya está generado; servidor principal aún no acredita la ruta scheduler. Pendiente: aceptación formal y prueba de carga/actividad real prolongada; experimentos OFF/ON, presupuesto efectivo y adaptador de costo máximo. Autorización USD 5 totales citada en budget-authorization.md, sin gasto nuevo hasta verificación por coordinación. Ninguna tarea se marcó completada.
## Presupuesto reducido y adaptadores, 2026-10-12 13:36

Ariel redujo el TOTAL de la ronda a USD 2 (transcripción original línea 1663, 16:24:04.979Z / 13:24:04). Incluye costos anteriores. Política en budget-policy.json y autorización en budget-authorization.md. Una autoridad PC 75727ff74069; otras PCs sin saldo ejecutable. Ledger operacional SQLite (no segunda memoria), transacciones/reservas/conciliación exactas, reducción persistida y sin restablecer USD 5 por cargar política vieja. Reservas pendientes bloquean nuevas llamadas; timeout/reinicio no devuelven saldo. Costo mayor que cota bloquea aunque entre en total. Histórico confirmado USD .00002268 y HTTP400 desconocido, no imputado cero.

Nuevos archivos de esta extensión: optimization_budget.py, optimization_cost.py, ops/verificar-cota.py, ops/comparar-rtk.py, test_optimization_budget.py, test_comparar_rtk.py, budget-policy.json. Modificados: jev.py (guardia única antes de credenciales/red y conciliación antes de validar semántica), agent_suggestions.py, optimization_scheduler.py, AgentImprovements.tsx, OptimizationScheduler.tsx, test_jev.py, mejoras.spec.ts y spec/review. Preservados títulos/launch de A; no git ni reinicios autónomos.

Checks finales: 51 backend en 2.91 s (budget-tests.log), 5 UI, UI+Handler+ledger real temporal con autoridad de prueba explícita (real-ui.json/png). RUFF/ESLint/build sin errores; Vite mantiene aviso >500 kB. Un check anterior falló por mock de clase Budget que reemplazó el constructor usado por el propio test; corregido aislamiento, no ocultar ni llamar estabilidad del mismo código. Tests prueban concurrencia, otra PC, timeout, baja de límite, respuesta semánticamente inválida con costo confirmado y no acceder a credencial/red si falta cota.

GET no pago /api/v1/key real: límite de clave compartida USD 50, restante 49.962581108, sin reset. No se modificó; no es autorización ni cota de esta ronda. Evidencia key-limits-readonly.json. Documentación primaria consultada: https://openrouter.ai/docs/api_reference/limits (cap de clave y estimación en vuelo no prueban máximo contractual de esta petición). Cota Jev .001 sigue siendo estimación; adaptador paga = bloqueado. No se lanzó ningún coding agent ni inferencia nueva.

OFF/ON local: script preparado sobre contratos pytest reales de memoria/actividad, hashes de fuentes congelados, comandos fijos y salida/tiempo/códigos; costo de servicios 0, tokens/calidad de agente desconocidos. Intento --run BLOQUEADO por sesiones/permisos reales; profiles=[] en off-on-local.json. No usarlo como ensayo realizado ni ahorro/beneficio/Caveman. Revisa estado real del servidor (no state vacío del script), dos muestras de recursos y actividad entre perfiles; subproc existente limita plazo y mata solo árbol propio de prueba en timeout. No está automatizado por el scheduler, no puede pausar CLI ajena.

Servidor principal: scheduler 200 activado por coordinación; nueva contabilidad todavía no cargada (budget_loaded=false medido). Requiere otra activación coordinada para la guardia Jev/ledger y panel. B está en punto seguro, sin comandos de prueba pendientes. Continúa automáticamente solo análisis de memoria encolada cuando libre. Optimización paga/CLI automática sigue deshabilitada. Pendientes: conciliación histórica documentada/cota proveedor verificable, ejecución OFF/ON bajo inactividad, aceptación humana de nuevos casos/baseline/mutaciones. No se marcó tarea completada.
## Cierre y punto seguro, 2026-10-12 14:05

Referencia final: handoff-B-final.md. Autoencolado oportunista implementado (ya no solo manual), deduplicación por snapshot de incidentes, cooldown120s, cola100, no bucle por hipótesis propias. Cancelación fresca después de sources/antes de propose/y luego de preservar la transacción. GET ledger/cola/peer sin inicialización ni reparación; start explícito.

Caso focal incorporado con autorización135958: 69 checks pasan en runner sin fijar referencia, evidencia de intento preservada. Tras refinamiento de lectura de identidad corrupta,2 checks afectados pasan. Build/lint/ruff y UI real temporal actualizados; no repetir backend de A1550 ni atribuirlo a B. Baselines intactos y mutaciones no ejecutadas. No PASS certificado ni ahorro declarado. Último OFF/ON bloqueado por actividad real. Máximo físico de latencia no medido: límites y campos de evidencia explicitados en handoff, no promesa de2s.
## Cierre de aceptación y permisos, 2026-10-12 14:18

Autorización explícita140806 aplicada después de corrida original completa preservada y revisión de muestra contra assertions/requisitos: baseline propio de scheduler.json con2casos; blueprint/requisitos/casos revisados aceptados con scripts oficiales. No otras referencias ni mutaciones ni umbrales modificados. acceptance-final.md documenta fuente/fecha, muestras y huecos.2casos tuvieron80tests cada uno, solapados; no sumarlos como160 casos distintos. Runner completo autorizado; resultado final conservado en actual.json/compuerta.md y roles de esta fase, no inferir PASS por código de salida.

Corrección operativa: pendientes de2026-09-13/10-06/10-07 verificados por GET real expirados. pending_active filtra por expires_at/zona y sesión, sin alterar registros. Vivo vigente o desconocido bloquea; vencido/muerto no.19tests de actividad pasan. mismo filtro en snapshot/cancellation y script de ensayo.

Encargo local integrado: nuevo optimization_experiment.py + cola kind off_on_local, API enqueue_off_on y botón UI. POST de encolado no reemplaza análisis activo, metadata guardada atómicamente. Solo tests fijos de memoria/actividad de esta carpeta; hashes de fuentes,10s por proceso mediante subproc existente (limpieza árbol propio), chequeo previo de actividad y pausa entre perfiles. Code failure/manifest change → revisión. JSON de resultados en improvements y nodo evidencia en conocimiento.sqlite, sin confirmar aprendizaje ni agentes. Petición lista en off-on-local-job.json; aún no encolada en backend viejo hasta activación coordinada. Calidad/ahorro/obediencia de agentes no medidos, paid/new_agents siguen false.

UI5casos pasan, lint/build/ruff sin errores (aviso bundle conocido). Comp puertas sin permisos elevados pueden no ver Git por spawn sandbox; no reportar ausencia real de Git (HEAD leído16d78cef84cb9b9dc5c97a0c3e79a367bb6d1b76). La comprobación fuera de sandbox detectó cambios de documentación posteriores a corrida; se termina toda escritura fuente antes de validación final. El límite de mutaciones es real: ninguna revisada/aprobada, árbol compartido activo no se muta; no inventar PASS general. Validación final y códigos reales quedan en artefactos, sin cambiar fuentes después de ella.
