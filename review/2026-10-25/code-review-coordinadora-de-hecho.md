# Revisión focal: coordinadora de hecho

Fecha: 2026-10-25. Revisión secuencial por Codex `01a173c8-4826-7d83-bce0-5dd684c7647a`, no independiente.

## Alcance

Elección compartida en huerfanos.py, guardia en sessions.set_coordinator, integración servidor/auditoría, tarjeta de propuestas y pruebas de backend/navegador. No cambia creencias ni reclasificación. Casillas de PENDIENTES.md conservadas.

## Revisión y correcciones

- Distingue frentes distintos vivos de reglas/envíos duplicados. Reglas apagadas, estacionadas y archivadas no acreditan coordinación actual. Conteo indexado en una pasada por relaciones.
- Reutiliza la elección y revalidación existentes. Una candidata única se marca; varias sólo reciben propuesta visible. Una coordinadora viva bloquea la inferencia y la sucesión huérfana.
- El título actual se conserva. La propuesta muestra evidencia numérica, elección de rol, aceptación de título y descarte. Los errores HTTP son visibles; botones con nombre accesible y deshabilitados durante solicitudes. Leer la tarjeta no escribe.
- El descarte y la retirada manual del rol persisten y bloquean la inferencia y el camino alternativo de huérfanos. Una guardia bajo state.lock impide que una promoción reservada pise una retirada posterior. Sin lock distribuido ni red bajo state.lock.
- La auditoría limpia propuestas ambiguas obsoletas y excluye tarjetas de PCs caídas también del enrutamiento de avisos, no sólo de la elección.
- La primera ampliación produjo 6 fallos de fixture de escritorio (74 pasaron): el controlador invocaba un alias de touch que el fixture no interceptaba y trataba de escribir en un directorio temporal inexistente. Se conserva el seam ses.touch usado por set_coordinator y se evita persistir dos veces cuando ya lo hizo la operación de rol. Después pasaron las 80 focales de ese conjunto.

## Evidencia

Build y ESLint focal: código 0. Ruff y formato focal: código 0. Primera integración del runner: 209 pruebas backend y 7 recorridos Chromium pasan. Los recorridos usan UI real y API/SSE fixture: marcar una candidata, conservar/aceptar título y error de descarte, más CLI/Desktop existentes. Backend incluye handler HTTP aislado y sucesión.

Tras los hallazgos adicionales de enrutamiento stale y prioridad manual, se repite el mismo runner y se conservan logs finales en `pruebas-agenticas/resultados/coordinadora-de-hecho/`. Sin baseline ni mutaciones aprobadas: runner devuelve 1 por referencia ausente y compuerta devuelve 2; no es PASS certificado.

Corrida final `2026-10-25T17-40-11.684Z-25008`: 212 pruebas backend y 7 recorridos Chromium pasan. Ambos casos del runner código 0; runner código 1 por baseline ausente. La evaluación de sólo lectura de la API real (6 sesiones) devuelve cero planes: no propone desplazar coordinadoras vivas actuales.

## Límites

La federación mantiene su límite ante partición de LAN; no se implementa consenso global. La evidencia de coordinación se limita a frentes vivos presentes en el snapshot. El descarte de propuesta persiste hasta una nueva marca manual explícita. No se provocan caídas ni muertes de sesiones productivas para probar. Antes de reiniciar, avisar a la coordinadora.
