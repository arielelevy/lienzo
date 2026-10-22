# Revisión W — grupos por proyecto

Fecha: 2026-10-22. Revisión local del delta, secuencial, con skill `code-review`.
Alcance fijado por el encargo W y ampliado expresamente a `arrows-geometry.ts` por la coordinadora.
No se usó git ni se revisaron cambios ajenos.

## Resultado

Sin hallazgos P1/P2 pendientes en el alcance revisado. Sin cambios de dependencias, API, permisos ni datos del servidor.

Archivos revisados:

- `web/src/components/Board.tsx`: selector accesible con dos iconos y `aria-pressed`; preferencia local; agrupado por la identidad compartida de `repoGroups`; reutilización del render de tarjeta; filtros existentes antes del agrupado. El modo habitual mantiene las columnas y su botón Ordenar. En grupos la posición es automática; Alt y el agarre siguen conectando.
- `web/src/styles.css`: grupos vecinos cuando caben; coordinadora centrada abajo con 52 px de separación mínima de la fila superior; móvil apilado sin desborde. Conserva la escala de 213 px y el resto de medidas existentes.
- `web/src/arrows-geometry.ts:1011`: los controles de la curva salen hacia el exterior del extremo correspondiente. El canal de columnas escalonadas podía caer dentro de una tarjeta.
- `web/src/arrows-geometry.ts:1030`: también se comprueba colisión con origen y destino, con tolerancia interior de 0,5 px; si la curva entra en ellos se usa el ruteo alternativo existente.
- `web/src/arrows-cluster.test.ts`: reproduce el defecto con coordenadas escalonadas; exige camino limpio y muestrea 200 puntos si el resultado es cúbico. Se complementa con el muestreo real de todos los caminos SVG en Playwright.
- `web/tests-ui/proyectos-cluster.spec.ts`: posiciones y separación de coordinadoras contra todos sus frentes, dos grupos a la misma altura en escritorio, ausencia de estrellas inventadas, filtro sin coincidencias, persistencia y retorno a columnas. El oráculo nace del encargo y su precisión posterior.

## Hallazgo corregido

P2: una S entre tarjetas escalonadas podía entrar en origen/destino porque el canal caía dentro de un extremo y `routeItems` sólo comprobaba terceras tarjetas. Reproducido con prueba focal roja y recorrido UI: 2 cruces de 3–6 px. Corregido mediante salida exterior y comprobación de extremos; recorrido final sin cruces.

## Validación medida

- `geometria-rojo.log`: prueba focal falla por curva que entra en su tarjeta de origen.
- `geometria-verde.log`: focal verde y 41 comprobaciones existentes de geometría verdes.
- `runner-ui.log`: 22 pruebas UI verdes: 3 de grupos, 10 de flechas existentes y 9 de mover/ordenar; 39,4 s en la corrida del runner.
- `runner-negativo.log`: caso negativo verde, ejecutado también por el runner.
- `checks.log`: TypeScript y ESLint focal, códigos `[0, 0]`.
- Capturas 1440/390 inspeccionadas. Interfaz y Chromium reales en Vite aislado 7363; sesiones/API de fixture, con escrituras bloqueadas.

Evidencia: `.temp/resultados/2026-10-22-W/`. Turno de navegador liberado al terminar. Sin build de producción ni suite global: la coordinadora los centraliza y pidió pausa de recursos.

## Límites reales

No está desplegado ni verificado por Ariel sobre sus sesiones reales. Por debajo de 900 px `Arrows.tsx` ya oculta flechas; se conserva ese comportamiento. El recorrido móvil verifica grupos, posición, persistencia y desborde; los cruces se miden en escritorio.

Los cinco roles tienen artefactos y validadores. No se aceptaron propuestas, mutaciones ni baselines. El runner ejecutó sus dos casos con código 0, pero terminó con código 1 por ausencia de `baseline.json`; la compuerta también devolvió 1 por ese motivo. No hay PASS certificado. La referencia y las aceptaciones quedan para la coordinadora.

## Contraste posterior en producción — Alt

La coordinadora informó un fallo de `mover.spec.ts:115` entre 53 pruebas con 4 workers. No conservó el assert ni la traza. Se reprodujo la receta en un worktree temporal de HEAD con los cinco archivos de W, junction a las dependencias existentes, `vite build` y `vite preview` en 7393. No se modificó código durante el contraste.

- `produccion-build-rojo.log`: build código 0; conserva el aviso de bundle mayor de 500 kB.
- `produccion-alt-rojo-3.log`: caso Alt repetido 3 veces, 3/3 verdes, código 0, con trazas.
- `produccion-mover-rojo-3.log`: mover.spec completo repetido 3 veces con 4 workers, 27/27 verdes, código 0; incluye otras 3 ejecuciones verdes del caso Alt.
- `produccion-integracion.log`: 53/53 verdes en 27,3 s con 4 workers; incluye grupos, flechas, mover, tablero y selección. Esta pasada ya estaba iniciada al recibir la instrucción de cerrar. Es distinta de la combinación original de la coordinadora, que incluía pcs en lugar de selección.

Veredicto: fallo informado no reproducido en 3+3 ejecuciones del caso. No prueba ausencia de intermitencia. Por instrucción expresa de la coordinadora se conserva el código y ella repetirá al integrar con trace; si reaparece aportará el assert. No se inventó rojo/verde ni se aplicó un arreglo sin causa demostrada.

Preview detenido, turno navegador liberado, junction y worktree temporal eliminados al terminar. Traces y logs conservados en la carpeta de evidencia de W. Lista de archivos para commit sin cambios.
