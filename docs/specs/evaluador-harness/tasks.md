# Tareas: mejoras de agentes CLI

Diseño y plan aprobados por Ariel el 2026-10-12. Ejecución secuencial en Codex; todas las casillas permanecen pendientes salvo pedido explícito de Ariel.

- [ ] 1. Preferencias locales y disponibilidad de herramientas
  - Implementar estado sin secretos y persistencia atómica de Caveman breve y RTK. Distinguir instalado de habilitado, y Windows de WSL.
  - _Requisitos: 3.4, 7.3, Selección 1, Selección 3, Selección 5, Selección 7_
  - _Archivos: lienzo/agent_improvements.py, tests/test_agent_improvements.py_
  - _Leer: design.md §lienzo/agent_improvements.py; lienzo/state.py: LIENZO; lienzo/tmux.py: en_distro_

- [ ] 2. Credencial privada y traslado de la clave autorizada
  - Implementar DPAPI por usuario en Windows y archivo 0600 en POSIX; preparar importación solo de CHESSTUDIA_OPENROUTER_API_KEY desde WSL sin mostrarla. Verificar integridad y permisos; ningún secreto entra a Git, API o logs.
  - _Requisitos: 7.6, Selección 3, Jev adaptación_
  - _Archivos: lienzo/jev_credentials.py, ops/importar-jev.py, tests/test_jev_credentials.py_
  - _Leer: design.md §lienzo/jev.py; D:/Apps/chess/docs/jev.md: Configuración_

- [ ] 3. Cliente Jev y validación del contrato
  - Cliente stdlib con timeout, sin reintentos, respuestas tipadas y costo obligatorio. Probar distribución inválida, opción fuera de contrato, timeout, errores HTTP y respuesta incompleta sin filtrar secretos.
  - _Depende de: 2_
  - _Requisitos: 3.2, 3.3, 4.1, 7.6, Jev adaptación_
  - _Archivos: lienzo/jev.py, tests/test_jev.py_
  - _Leer: design.md §lienzo/jev.py; D:/Apps/chess/apps/api/tutor/jev.py: cuerpo_del_pedido y validación de respuesta; documentación OpenRouter Decisions vigente_

- [ ] 4. Métricas de sesiones y evidencia acotada
  - Leer turnos con alcance, modelo y cobertura; separar resultados conocidos, ausentes, errores, duración y uso acumulado. No inferir costo ni calidad, ni sumar contadores incompatibles.
  - _Requisitos: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 4.1, 4.2, 4.3_
  - _Archivos: lienzo/agent_evaluation.py, tests/test_agent_evaluation.py_
  - _Leer: design.md §Datos observados; lienzo/transcripts.py: turns y estructura tool/result; lienzo/server.py: session_view_response_

- [ ] 5. Sugerencias verificables y juicio opcional
  - Producir candidatos con referencias a turnos/herramientas y límites. Jev elige entre candidatos, ninguna o datos insuficientes; no aplica cambios. Guardar decisión/uso sin transcript completo ni entorno.
  - _Depende de: 1, 3, 4_
  - _Requisitos: 3.1, 3.2, 3.3, 3.4, 7.1, 7.2, 7.3, 7.4, 7.6, Selección 2, Selección 6_
  - _Archivos: lienzo/agent_suggestions.py, tests/test_agent_suggestions.py_
  - _Leer: design.md §Datos observados y §lienzo/jev.py; lienzo/agent_evaluation.py; lienzo/jev.py_

- [ ] 6. Instrucciones por agente y argumentos seguros
  - Agregar estilo breve y RTK explícito al lanzamiento con opciones compatibles verificadas; preservar instrucciones, reanudación y modelos. Probar quoting Windows, argv POSIX y soporte real de Codex; sin CLAUDE.md ni hooks globales.
  - _Depende de: 1_
  - _Requisitos: Selección 3, Selección 4, Selección 5, Selección 6_
  - _Archivos: lienzo/launch.py, lienzo/agent_improvements.py, tests/test_launch_improvements.py_
  - _Leer: design.md §Lanzamiento; lienzo/launch.py: launch y _launch_cmd y _launch_tmux; ayuda local de cada CLI_

- [ ] 7. API autenticada y propiedad de sesiones
  - Agregar estado/preferencias y evaluación bajo rutas aprobadas. Mantener CSRF, límites, identificación de PC dueña y error remoto explícito; impedir que parámetros de UI se vuelvan comandos.
  - _Depende de: 1, 5_
  - _Requisitos: 1.1, 3.4, 5.1, 5.3, Selección 1, Selección 3, Selección 7_
  - _Archivos: lienzo/server.py, tests/test_agent_improvements_api.py_
  - _Leer: design.md §API y UI; lienzo/server.py: _prepare y _session_view y PeerHandler; lienzo/agent_suggestions.py_

- [ ] 8. Vista de preferencias y evaluación
  - Componente React para disponibilidad, activar/desactivar, muestra local y Consultar Jev con costo visible. Ignorar respuestas tardías y conservar sesión/PC correcta. Sin llamadas pagas automáticas.
  - _Depende de: 7_
  - _Requisitos: 3.1, 3.3, 3.4, 5.1, 5.2, 5.3, 7.3, Selección 1, Selección 3_
  - _Archivos: web/src/components/AgentImprovements.tsx, web/src/styles.css, web/tests-ui/mejoras.spec.ts_
  - _Leer: design.md §Experiencia y §API y UI; web/src/api.ts: api; web/tests-ui/tablero-fijo.ts: bloquearEscrituras_

- [ ] 9. Entradas desde tablero y panel de sesión
  - Conectar la vista a Mejoras de agentes en menú contextual y Mejoras en el panel. No perder la selección de sesión ni cerrar formularios por actualizaciones SSE.
  - _Depende de: 8_
  - _Requisitos: 5.1, 5.2, Selección 1, Selección 3_
  - _Archivos: web/src/components/Board.tsx, web/src/components/Panel.tsx, web/tests-ui/mejoras.spec.ts_
  - _Leer: design.md §Experiencia; web/src/components/Board.tsx: context; web/src/components/Panel.tsx: tabs; web/src/components/AgentImprovements.tsx_

- [ ] 10. Instalación acotada y comprobación real de RTK
  - Preparar instalación de versión fija oficial con integridad comprobada; ejecutar solo tras aprobación requerida por el sandbox. Contrastar código de salida y recuperación de un comando exitoso y fallido propios; informar soporte WSL separado.
  - _Depende de: 1, 6_
  - _Requisitos: 7.1, 7.4, 7.5, Selección 5, Selección 6_
  - _Archivos: ops/preparar-mejoras.py, tests/test_preparar_mejoras.py, README.md_
  - _Leer: design.md §RTK y Caveman; D:/Apps/tools/rtk/README.md: instalación y recuperación; lienzo/agent_improvements.py_

- [ ] 11. Evidencia agéntica y checks de integración
  - Recorrer los cinco roles secuencialmente, reutilizar casos autorizados y dejar nuevos casos para revisión sin aprobar baselines. Verificar interfaz, API y errores, además de pruebas de contrato. Una llamada Jev real acotada solo con costo informado/autorizado; no certificar calidad del clasificador por conectividad.
  - _Depende de: 2, 3, 5, 6, 7, 9, 10_
  - _Requisitos: 6.1, 6.2, 6.3, 7.5, Selección 6_
  - _Archivos: pruebas-agenticas/pruebas-agenticas.json, pruebas-agenticas/resultados/roles.json, web/tests-ui/mejoras.spec.ts_
  - _Leer: design.md §Verificación; skill pruebas-agenticas: roles-portables y runner; config/baselines actuales_

- [ ] 12. Revisión final y batería completa
  - Code review del cambio, corregir hallazgos autorizados, ejecutar batería y compuerta; reportar veredicto real y limitaciones. No hacer commits ni marcar tareas completadas sin pedido.
  - _Depende de: 11_
  - _Requisitos: 6.1, 6.2, 6.3, 7.5_
  - _Archivos: ninguno_
  - _Leer: diff de cambios propios; skill code-review; design.md §Verificación; evidencia actual de pruebas_
- [ ] 13. Señales de actividad y recursos; pruebas de bloqueo seguro
  - _Requisitos: 8.1, 8.2_
  - _Archivos: lienzo/optimization_activity.py, tests/test_optimization_activity.py_
  - _Leer: design.md §Aprendizaje oportunista; health.py: _memoria y _cpu_pct_
- [ ] 14. Cola persistente local, pausa y recuperación sin reintentos
  - _Requisitos: 8.2, 8.3_
  - _Archivos: lienzo/optimization_queue.py, tests/test_optimization_queue.py_
  - _Leer: design.md §Aprendizaje oportunista; atomico.py: atomic_write_
- [ ] 15. Hipótesis propuestas sobre memoria existente, contexto y vigencia
  - _Requisitos: 8.4, 8.7_
  - _Archivos: lienzo/optimization_memory.py, tests/test_optimization_memory.py_
  - _Leer: conocimiento.py: crear_nodo, vincular, _abrir; design.md §Aprendizaje oportunista_
- [ ] 16. Scheduler acotado y API local integrada
  - _Depende de: 13, 14, 15_
  - _Requisitos: 8.1, 8.2, 8.3, 8.5_
  - _Archivos: lienzo/optimization_scheduler.py, lienzo/server.py, tests/test_optimization_scheduler.py_
  - _Leer: server.py: main, Handler; design.md §Aprendizaje oportunista_
- [ ] 17. Panel de cola, pausa y propuestas sin autoveredicto
  - _Depende de: 16_
  - _Requisitos: 8.6, 8.5_
  - _Archivos: web/src/components/OptimizationScheduler.tsx, web/src/components/AgentImprovements.tsx, web/tests-ui/mejoras.spec.ts_
  - _Leer: AgentImprovements.tsx; design.md §Aprendizaje oportunista_
- [ ] 18. Recorrido agéntico, code-review y evidencia de activación
  - _Depende de: 17_
  - _Requisitos: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_
  - _Archivos: docs/specs/evaluador-harness/verification.md, code-review-2026-10-12.md, pruebas-agenticas/scheduler.json_
  - _Leer: evidencia del runner; skills pruebas-agenticas y code-review_
- [ ] 19. Ledger único, históricos, reservas y conciliación
  - _Requisitos: 9.1, 9.2, 9.3_
  - _Archivos: lienzo/optimization_budget.py, tests/test_optimization_budget.py, docs/specs/evaluador-harness/budget-policy.json_
  - _Leer: design.md §Contabilidad; budget-authorization.md; jev-real.json_
- [ ] 20. Adaptadores de costo y guardia en transporte Jev
  - _Depende de: 19_
  - _Requisitos: 9.2, 9.3, 9.4_
  - _Archivos: lienzo/optimization_cost.py, lienzo/jev.py, tests/test_jev.py_
  - _Leer: design.md §Contabilidad; jev.py: decide_
- [ ] 21. Estado de presupuesto y controles UI
  - _Depende de: 20_
  - _Requisitos: 9.1, 9.2, 9.4_
  - _Archivos: lienzo/optimization_scheduler.py, lienzo/agent_suggestions.py, web/src/components/OptimizationScheduler.tsx_
  - _Leer: design.md §Contabilidad; componentes existentes_
- [ ] 22. OFF/ON local, recorrido y revisión
  - _Depende de: 21_
  - _Requisitos: 9.1, 9.2, 9.3, 9.4_
  - _Archivos: ops/comparar-rtk.py, docs/specs/evaluador-harness/verification.md, code-review-2026-10-12.md_
  - _Leer: benchmark.md; pruebas-agenticas/scheduler.json_
