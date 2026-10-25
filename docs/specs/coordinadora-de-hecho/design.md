# Coordinadora de hecho

Fuente: PENDIENTES.md, «Sugerir la marca de coordinadora»; encargo de Ariel por la coordinadora, 2026-10-25.

La auditoría reconoce una sesión viva sin marca que recibe reglas `on_stop` activas de al menos dos frentes vivos distintos y originó envíos a al menos dos frentes vivos distintos del mismo repo. Reglas duplicadas y envíos repetidos cuentan una sola vez por frente. No cuentan autorreglas, tarjetas detenidas, PC caída, procesos externos, reglas estacionadas o archivadas, ni identidades provisionales.

La decisión vive en `huerfanos.planes`, compartida con la sucesión: una coordinadora viva bloquea ambas promociones. Una candidata de hecho tiene prioridad frente al reemplazo huérfano arbitrado por ID. Si hay varias candidatas de hecho se publican propuestas para cada una, sin marcar ninguna. Antes de aplicar, el servidor vuelve a evaluar los datos actuales y la disponibilidad de snapshots.

Una candidata única se marca sin despertar modelos ni pisar su título. La tarjeta muestra evidencia numérica y un título propuesto, aceptable por botón. En caso ambiguo, una persona puede elegir «Marcar coordinadora» usando la acción existente. «Descartar propuesta» o quitar manualmente el rol persiste una negativa que bloquea nuevas promociones automáticas, también por el camino de huérfanos. Una marca manual explícita vuelve a habilitarla. Renombrar elimina la propuesta de título. Si cambia la evidencia o aparece otra coordinadora, la auditoría retira propuestas de rol obsoletas.

La interfaz conserva errores HTTP visibles y deshabilita botones mientras hay solicitud. Una propuesta no se ejecuta al leerla. No se cambian creencias ni se ejecuta reclasificación.

Verificación: conteo distinto 1/2, duplicados, repo ajeno, regla apagada, coordinadora viva, ambigüedad, título conservado, rechazo persistente; ruta HTTP y sucesión reutilizadas. Chromium con API/SSE fixture prueba marcar, aceptar título y error de descarte. No se alteran sesiones reales durante pruebas.

La exclusión global mantiene el límite ya documentado de la federación: no es un protocolo de consenso ante particiones de red.

- [ ] Implementación y revisión focal.
- [ ] Runner con logs; no fijar baseline ni aprobar mutaciones.
- [ ] Commit y push; aviso previo antes de reiniciar.
