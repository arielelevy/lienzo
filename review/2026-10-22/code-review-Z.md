# Revisión Z — columnas, controles y avisos

Alcance autorizado: delta de `Board.tsx`, estilos del agrupado, `Card.tsx`, `CardNeeds.tsx`, `types.ts`, `card-notices.ts` y sus pruebas. Misma sesión, revisión estática con el skill code-review. Sin revisión global de dependencias ni de cambios de otros frentes.

## Resultado de la revisión

Sin hallazgos P1/P2 abiertos en el delta revisado. La evidencia del runner conserva 35/35 pruebas UI, 5/5 unitarias y ESLint con código 0. TypeScript se interrumpió por la segunda pausa (3221225794) y se ejecutó después por separado con código 0. No se declara aprobación de baselines ni PASS de compuerta.

Se revisaron rutas usual/agrupada, clasificación de sesiones huérfanas y muertas, colapso, filtro móvil, render de Chrome, persistencia, posición manual y recálculo de flechas. Se conservó un único render de columnas. Los grupos se calculan después de clasificar por estado. La coordinadora queda al final de cada grupo con separación vertical.

Los avisos se filtran únicamente en presentación. No se inventa una confirmación del envío, no se borra historial y no se cambia el estado operativo de la sesión. Los permisos y preguntas activos no caducan por este cambio. `prompt_ts` ya llega en la sesión pública del servidor; sólo se agrega su tipado frontend. No se editaron `sessions.py` ni `hooks_eventos.py`.

El aviso de turno consulta `useRondas`: exige dueño coincidente, vencimiento futuro y antigüedad menor a tres minutos. Auto-aprobado y sin-enviar usan el reloj existente de Card, actualizado cada diez segundos. Una confirmación de entrega sólo retira sin-enviar si es final y su fecha no es anterior al aviso. Un pedido posterior también lo retira.

## Hallazgo corregido durante la revisión

La primera implementación había puesto la clase `.ordenar` en el contenedor permanente de modos. Rompía el contrato existente de `mover.spec.ts:67`: el control de devolver tarjetas sólo existe cuando hay posiciones manuales. Se movió la clase al botón habitual y se condicionó a posiciones manuales. La reejecución focal pasó, conservando los dos íconos pequeños en la posición original.

## Validación medida antes de la segunda pausa

- Rojo de agrupado: se esperaban tres columnas y el modo anterior devolvía cuatro proyectos.
- Rojo independiente de los tres avisos: auto-aprobado viejo, sin-enviar viejo y turno liberado seguían visibles.
- Primera regresión ampliada: 33/34, con el fallo de Ordenar indicado arriba.
- Tras corregirlo: 16/16 Playwright (proyectos-cluster y mover), incluyendo 1440 y 390 px, persistencia, vuelta al habitual, filtro sin grupos vacíos y caducidad por reloj sin SSE.
- Unitarias: 5/5 entre card-notices y arrows-cluster, incluyendo límites de tres minutos, fechas inválidas, pedido nuevo, cierre, muerte, entrega causal y turno liberado/vencido/de otro dueño.
- ESLint focal y TypeScript: código 0.

La UI se verificó con Vite aislado en 7360 y sesiones fixture, bloqueando escrituras a sesiones reales. No hubo despliegue ni reinicio del 7321. Se conservó el resultado original del runner sin editar su código de TypeScript. La ejecución posterior está en `.temp/resultados/2026-10-22-Z/tsc-final.log`. Se inspeccionaron las capturas de 1440 y 390 px, copiadas a la evidencia Z. La compuerta devuelve código 2: `No hay baseline.json: fijarlo a mano con ejecutar.mjs --fijar`. La suite global y la aceptación corresponden a la coordinadora.
