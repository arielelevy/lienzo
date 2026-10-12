# Integración de Lienzo — evidencia de coordinación

Fecha: 2026-10-12. Alcance: títulos `proyecto | tarea`, mejoras de CLI y análisis de memoria durante inactividad. Autorización de Ariel: integrar, reiniciar, aprobar la ronda y terminar. Presupuesto vigente: USD 2 totales.

## Activación verificada

El servidor se reinició por `POST /restart` después de que A y B entregaran puntos seguros. A las 14:06:54, `/health` devolvió `ok: true`; `/agent-improvements/scheduler` devolvió `enabled: true`, autoencolado por versión, cooldown de 120 segundos y máximo de 100 trabajos. El presupuesto cargado fue USD 2, costo confirmado USD 0.00002268, una imputación histórica desconocida y pagos bloqueados.

Tres GET consecutivos del scheduler conservaron hash y fecha de modificación de `optimization-budget.sqlite` y `peers.json`. La cola no existía antes de esa comprobación; no se afirma haber comparado su hash.

## Pruebas y revisión

- A: reproducción de autenticación, 9 fallas y 4 aprobados antes; los mismos 13 casos aprobados después. Focal ampliada: 68 aprobados. Runner backend: 1550 aprobados, código 0, baseline anterior intacto. Revisión en `pruebas-agenticas/resultados/coordinacion-A/auth-fix-review.md`.
- B: runner scheduler focal, 69 aprobados; refinamiento posterior de GET, dos casos afectados aprobados. Build, lint y revisión; UI y Handler aislados. Entrega en `handoff-B-final.md`.
- Los conteos solapados no se suman. Una corrida seleccionada de backend no certifica la compuerta general. La evidencia vieja de aceptación no ejecutada no acredita el código actual.

## Pendientes detectados durante cierre

El análisis de inactividad contaba permisos vencidos de sesiones antiguas. B corrigió el filtro de vigencia/estado conservando el historial: 19 casos de actividad aprobados; referencia propia del alcance aprobada, dos casos del runner coinciden y cinco UI pasan. La compuerta escala solo por falta de medición de mutación. Los cambios ya fueron cargados durante el reinicio diagnóstico de las 14:23.

El override de Codex se aplica al lanzar. A realizó un primer relevo: PID 20516 pasó a 11272 con el mismo ID y título. El nuevo cliente mostró «This conversation is open in another app» y Lienzo conservó erróneamente el estado muerta pese a alive=true. Se corrigió SessionStart para una tarjeta retomada, manteniendo los controles de eventos viejos; cuatro regresiones nuevas y 151 focales aprobados. Coordinación cargó el arreglo y usó una sola vez R en el diálogo: el aviso desapareció y se recuperó el cuadro de entrada del mismo ID. Se devolvió el encargo pendiente de Mi estudio.

Ariel aclaró que esa sesión tenía tareas pendientes. Un estado termino significa cierre de turno, no encargo terminado; no debe usarse por sí solo como autorización operativa de relevo. Se detuvieron todos los demás relevos. No se afirma que todos los Codex antiguos se hayan retomado ni se cierran procesos activos para aplicar preferencias.

Ariel pidió quitar sonidos. Se guardó `notifications=false` en la configuración de Codex con respaldo y se añadió el override a lanzamientos/resumes. Marcas de sonido coincidieron con permisos, pero no se capturó directamente el emisor de audio. La sincronización de títulos se pausó temporalmente para diagnóstico y los sonidos continuaron. El arreglo final sustituye las reescrituras repetidas por una aplicación ante cambio de PID/título; la pausa diagnóstica no forma parte del producto final.

## Límites medidos

El OFF/ON local conservó `profiles: []` y estado bloqueado por agentes/permisos reales. Se integró un encargo diferido para ejecutar los dos perfiles de contratos locales durante inactividad real. No hay ahorro, calidad de agentes ni obediencia de Caveman medidos. La pausa es cooperativa y no se midió un máximo real de reacción. El scheduler analiza incidentes y propone hipótesis en la memoria existente; no ejecuta modelos ni CLI pagos automáticamente. No se concilia un cargo desconocido como cero ni se supone una cota de proveedor.

Este registro conserva evidencia y pendientes; no declara PASS general ni tareas terminadas.
