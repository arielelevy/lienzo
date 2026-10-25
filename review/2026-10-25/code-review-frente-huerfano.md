# Revisión focal: frente huérfano

Fecha: 2026-10-25. Actor: sesión Codex `01a173c8-4826-7d83-bce0-5dd684c7647a`. Revisión estática secuencial por el implementador; no se presenta como revisión independiente.

## Alcance

`lienzo/huerfanos.py`, integración de `auditoria.py` y `server.py`, pruebas focales, configuración del runner y diseño. Sin cambios en creencias ni reclasificación. Se mantiene pendiente la casilla en PENDIENTES.md.

## Resultado y hallazgos corregidos

- La elección se revalida dentro del servidor, serializada entre traspasos automáticos locales. Se bloquea si hay coordinadora viva del repo o si falta el snapshot inicial de un peer que no está confirmado caído.
- La PC caída invalida las tarjetas stale. Sin parentesco explícito no se promueve; una regla de informe tiene prioridad sobre envíos históricos y sólo el último remitente sirve de respaldo si no existe regla.
- El recableado filtra por repo y tipo `on_stop`, conserva reglas apagadas y evita informes a sí misma. No escribe una sucesión global de la sesión anterior: el lanzador puede pertenecer a otro repo y no debe ser suplantado allí.
- Los fallos de red conservan `orphaned_pending`. Los fallos del aviso conservan `orphaned_notice_pending`. Ambos se reintentan por la auditoría sin repetir un aviso aceptado.
- Se preservan los identificadores anteriores para recablear una regla que aparezca al restaurar un frente más tarde.
- La auditoría relee las sesiones tras una promoción aceptada para no evaluar la ronda contra el snapshot anterior.
- Se dividieron selección, reserva y aviso para reducir la complejidad del controlador. I/O de red fuera de `state.lock`; el lock específico sólo serializa traspasos automáticos.

## Evidencia

Primer conjunto de 54 focales pasó. Con aviso diferido, restauración tardía, escritorios y exclusiones se ejecutaron 85 focales. Runner integrado con ruta HTTP real en puerto efímero: 98 pruebas pasan, logs bajo `pruebas-agenticas/resultados/frente-huerfano/`. Auth, sesiones, transporte de consolas y peers son fixtures declaradas; el socket y el handler HTTP son reales. No se mató ninguna sesión productiva.

Hubo un comando con ruta inexistente `tests/test_sucesion_guardrails.py`: código 1, ninguna prueba ejecutada. Se corrigió la lista a archivos existentes antes de medir; no se cuenta como fallo funcional.

Ruff y formato focal pasan. Runner sin baseline: código 1; compuerta código 2. No se aceptaron baselines ni mutaciones. Los cinco roles se registran en `resultados/frente-huerfano/roles.json`.

## Límites

La elección usa la vista disponible de la federación. No implementa consenso distribuido ni garantiza exclusión global ante partición de red con vistas distintas. Una PC no disponible deja recableado pendiente hasta que vuelva. El aviso aceptado por el transporte no acredita lectura humana o del agente. Las pruebas de caída son fixtures, no cortes reales de LAN.

No se reinicia ningún servidor como parte de las pruebas. La entrega requiere aviso previo a la coordinadora antes de activar el cambio.
