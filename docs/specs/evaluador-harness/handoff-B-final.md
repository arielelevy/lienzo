# Frente B — punto seguro para activación final

Actualización final14:18: aprobación140806 habilitó aceptar baseline propio2casos y propuestas revisadas, luego de muestra/corrida preservada; baselines generales intactos. Filtro de permisos vencidos/muertos corregido (historia intacta). Nuevo encargo OFF/ON local integrado: payload preparado en off-on-local-job.json, botón «Comparar RTK cuando esté libre». Aún no medido/encolado en backend viejo; coordinación activa y envía PUT indicado. Diferir por señales reales, no falsificar inactividad. Sin pagos/agentes. Archivos adicionales: optimization_experiment.py, test_optimization_experiment.py; modificaciones activity/queue/scheduler/memory/script/UI y acceptance-final.md.2baterías80tests cada una (solapadas), UI5. Referencia actual de veredicto y últimas corridas: compuerta.md/actual.json bajo resultados/scheduler; limitación mutaciones sin revisar, no PASS inventado. La sección anterior conserva historia del checkpoint con baseline intacto anterior a nueva aprobación.

2026-10-12. Sin git, reinicios, cierres ni gastos nuevos. auth.py pertenece a A y no fue editado por B. Fuente de presupuesto vigente USD2 TOTAL: transcripción línea1663, 16:24:04.979Z; conserva costo previo .00002268 y HTTP400 desconocido. No inferir cero ni inventar cota de proveedor.

## Archivos de esta última corrección

- Backend: optimization_budget.py (GET lectura/activación explícita), optimization_queue.py (recuperación en start + versiones/cooldown), optimization_activity.py (cancelación fresca), optimization_memory.py (snapshot versionado solo incidentes), optimization_scheduler.py (autoencolado circular/pausa por fronteras/start).
- UI: OptimizationScheduler.tsx (origen, fuentes/versiones y propuestas visibles).
- Pruebas: test_optimization_budget.py, test_optimization_scheduler.py, test_optimization_memory.py, test_agent_improvements_api.py; pruebas-agenticas/scheduler.json agrega scheduler-focal con aprobación de coordinación135958. Oráculo conservado como metadata y en spec: sin escrituras GET, sin propuesta tras retorno de actividad, solo una versión de evidencia, reducción/reservas sin pagos sin cota.
- Spec/review: requirements/design/tasks/verification, este handoff, code-review-2026-10-12.md. Scripts/ledger anteriores listados en verification.md. Excluir .rea-review de integración.

## Evidencia revisada

Runner sin --fijar: scheduler-focal69 passed, 3.44s, código del caso0; runner1 por baseline ausente. Log preservado: resultados/scheduler/intentos/2026-10-12T17-00-38.913Z-32340/salidas/scheduler-focal.intento-1.log. Revisión de muestra: test_activity_during_sources_prevents_proposal_and_preserves_cursor impide escritura; test_activity_during_proposal_keeps_transaction_result_then_pauses conserva transacción; test_auto_enqueue_new_memory_once_without_own_hypothesis_loop observa deduplicación/cooldown; test_source_version_ignores_generated_hypotheses_and_changes_for_new_incident usa memoria SQLite real temporal; test_scheduler_get_does_not_create_ledger_or_peer compara bytes/mtime.

Último refinamiento de GET evita reparación de peer corrupto. Solo2 tests afectados reejecutados, ambos pasan; no repetir backend completo. A informó1550 backend, baseline intacto (evidencia de A, no corrida atribuida a B). RUFF/ESLint/build pasan; aviso bundle>500kB existente. UI/Handler/ledger reales temporales actualizados14:04, screenshot real-ui.png inspeccionado y real-ui.json preservado. No confundir fixtures de inactividad con OS quieto real.

OFF/ON real local intentado de nuevo: bloqueado por agentes/permisos reales; profiles=[] en off-on-local-final.json. Sin ahorro, obediencia, calidad Caveman o beneficio de RTK medidos. No se fijó baseline ni ejecutaron mutaciones en árbol compartido con A. Aprobación de incorporar caso != PASS de compuerta. El actual.json viejo corresponde a NO EJECUTADO anterior; el caso actual está en actual.parcial.json y su intento preservado, no usar el veredicto viejo como si midiera este código.

## Operación después de activar

Coordinación hace restart y verifica GET scheduler (budget2, pagos/CLIsfalse), que GET repetidos no cambian archivos del ledger/cola/peer y motivo real de bloqueo. Cuando haya180s de inactividad, dos muestras CPU<=35%, memoria>=1.5GB y sin sesiones ocupadas/permisos: autoencola incidente nuevo, una ejecución local, hipótesis propuestas y evidencia en conocimiento.sqlite. No modelo/CLI automático ni autoveredicto. Versión idéntica y evidencia generada por la misma tarea no crean bucle.

Latencia: pause se revalida entre operaciones y luego de confirmar transacción; polling2s, esperas SQLite250ms/consulta progress1s y FS pueden sumar tiempo. No se midió máximo de reacción real en host quieto, no garantizar2s absoluto. Pendientes reales: activación operativa por coordinación, observación de autoencolado/inactividad productiva, conciliación histórica/cota proveedor, ensayos OFF/ON y mutaciones revisadas. Ninguna tarea se marcó completada por cuenta propia.
