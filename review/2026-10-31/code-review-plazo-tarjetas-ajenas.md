# Revisión del plazo del E2E de tarjetas ajenas

Fecha: 2026-10-31. Alcance: diff de `pruebas-agenticas/tarjetas_ajenas_e2e.py`.
Revisión secuencial en la sesión principal con el skill code-review.

## Cambio y revisión

El caso esperaba 120 s desde que escribía SessionEnd, pero `lienzo/state.py:58`
define DEAD_KEEP_S = 120 y `lienzo/sessions.py:2336` exige edad > DEAD_KEEP_S.
El consumidor del evento y el ciclo de liveness (2 s) agregan demora.
El plazo pasa a 180 s, dentro de los 300000 ms del caso configurado.
Se conserva el oráculo: tarjeta ausente, regla estacionada, ninguna herencia por
carpeta y herencia al renombrar con el título del frente.

Sin hallazgos nuevos en el diff: no cambia producción, permisos, procesos,
dependencias, entradas, manejo de errores ni condiciones de aprobación.
Se corrigió también la descripción antigua que decía 60 s.
Ruff check del archivo y git diff --check salieron con código 0.

## Límites

No es una auditoría completa del arnés ni de sus dependencias.
El plazo queda explícito: si cambia el contrato de retención hay que revisarlo.
No se agregaron casos ni mutaciones y no se modificó el baseline.
La evidencia del runner queda en `pruebas-agenticas/resultados/tarjetas-ajenas-N/`.

## Resultado observado

Corrida parcial `2026-10-31T13-38-22.178Z-30512`: 1 de 1 casos seleccionados con
código 0, 127110 ms. El log completo muestra borrado a los 121 s, estacionamiento,
rechazo de herencia por carpeta y herencia por título correctos.
Evidencia: `intentos/2026-10-31T13-38-22.178Z-30512/salidas/tarjetas-ajenas-e2e.intento-1.log`
y `actual.parcial.json` dentro del directorio de resultados.
El runner y la compuerta salieron con código 1: falta baseline.json.
Tendencia salió con código 0: registra la corrida anterior con fallo y la nueva
parcial con éxito; no hay medición de mutaciones. No se afirma PASS global.
La primera invocación del runner no pudo crear el hijo: Error: spawn EPERM.
Se ejecutó fuera del sandbox tras esa restricción; el servidor usado fue aislado.
El primer fallo de 120 s quedó copiado en `salidas/plazo-primer-fallo-20261029.log`.

No hizo falta ficha FDD por ser una corrección puntual de un caso existente.
Los roles reutilizados y sus límites se agregaron a roles.json sin borrar el acta anterior.
