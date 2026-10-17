# Revisión del cambio: coordinadora Codex

Alcance: web/src/nl.ts, web/src/nl.test.ts, comentario de SendBox.tsx y web/tests-ui/codex-coordinadora.spec.ts. No se revisaron como propios los cambios concurrentes de backend.

La selección implícita de «avisame» exigía Claude aunque el catálogo declaraba coordinables Codex, Pi, CODA y Kiro. Ahora usa el catálogo compartido. Una coordinadora marcada conserva prioridad; se mantiene el filtro de repo y la exclusión del origen. App.tsx entrega únicamente destinos escribibles y con PC disponible.

Revisión estática focal: sin hallazgos pendientes en el delta. Sin nuevas dependencias, entradas ejecutables, escrituras reales en los casos de navegador ni cambios de permisos. La importación JSON funciona con Node 24 y el build TypeScript/Vite del repo.

Validación: frontend-unit coincide con baseline; lint y build con código 0. Dos pruebas de navegador con fixtures pasan para Codex CLI y Desktop: menú de coordinadora y creación de regla on_stop con destino correcto y {respuesta}. Lint del nuevo archivo: 0. Config del plugin válida, 0 errores y 0 avisos.

Límites: API y SSE simulados en navegador; no se acredita entrega real entre procesos. No se aprobaron baselines ni mutaciones. La compuerta y la batería general deben informarse con su resultado real, sin inferir PASS del resultado focal.

Primera batería general: 134/136; dos fallos de entorno al cerrar el contexto con ENOENT en trazas. El caso focal se lanzó en paralelo con la misma carpeta de artefactos; se preservó el log en pruebas-agenticas/resultados/intentos/2026-10-17T22-37-49.536Z-45420/salidas/frontend-playwright.intento-1.log. Repetición autorizada con salida exclusiva web/node_modules/.playwright-coordinadora.

Compuerta compartida: FAIL (código 1). Leyó backend-pytest fallido y evidencia de mutación de otro estado; no constituye un veredicto focal del delta. Los resultados compartidos están siendo escritos por otra sesión. No se atribuye a este cambio la mutación 5/6 ni el resumen 6/7 de esa evidencia.

Resultado final de la repetición aislada: 136/138 pasaron, código 1, 2.0 min. Pasaron nuevamente Codex CLI y Desktop. Los dos fallos fueron flechas.spec.ts a 960 px, antes de sus aserciones geométricas: page.waitForSelector('.card') agotó 30000 ms en tablero-fijo.ts:419. Se conservaron contexto y trazas en web/node_modules/.playwright-coordinadora. Causa raíz pendiente; sin PASS global. No se modifican pruebas ni tiempos para ocultarlos.
