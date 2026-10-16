# Code review 2026-10-16: skills/lienzo-infografias

Revisión con el skill `code-review` (nivel medio) de la skill nueva de infografías, sus SVG en
`docs/img/infografias/` y `tests/test_infografias.py`. Nueve hallazgos, ninguno rompía algo.

| # | Hallazgo | Estado |
|---|---|---|
| 1 | `--check` aprobaba aunque la página tuviera errores de consola o scroll lateral | Corregido: exige `console: clean` y `scrolls sideways: no` |
| 2 | El `aria-label` decía «lámpara blanca», que en el tema claro es negra | Corregido: «lámpara resaltada» |
| 3 | La leyenda atribuía el hook de 60 s a todos los agentes; `hook.py` lo registra para Claude Code, Codex y CODA | Corregido en la leyenda y en la clave |
| 4 | El rótulo «60 s» del reloj quedaba de unos 4 px en el README | Corregido: tamaño 4,2, verificado con acercamiento |
| 5 | `BUSY` tenía entradas muertas y duplicaba `JACK` | Corregido: se quitó el conjunto |
| 6 | Una opción mal escrita (`--chek`) se ignoraba y salía 0 | Corregido: sale 2; caso `test_opcion_desconocida_sale_2_sin_armar` |
| 7 | Dos SVG casi idénticos de 178 KB por figura | Pendiente: un solo SVG con `prefers-color-scheme` exige reescribir el CSS del kit |
| 8 | El ancho de captura no seguía el de la figura | Corregido: viewport de 1200 px, holgado para figuras más anchas |
| 9 | El README no mencionaba la skill ni sus figuras | Corregido en «Estructura»; insertar la figura en el texto queda a decisión de Ariel |

Verificación: `pytest tests/test_infografias.py` 7 de 7; `build.mjs --check` con consola limpia y
0 líneas sueltas en los dos temas; suite `pruebas-agenticas/infografias.json` con los dos casos OK.

## Segunda ronda: figura de plugins y renombre

Revisión de `figuras/plugins.mjs`, la sección «Plugins locales» del README y el renombre a
central de comunicaciones. Diez hallazgos, todos corregidos:

- Los SVG nuevos sin versionar y los viejos borrados: se commitean juntos.
- La ruta `/ext/<nombre>` existe sólo si el módulo define `get` o `post`: lo dicen el README y la leyenda.
- Un archivo con nombre fuera de `[a-z][a-z0-9_]{0,31}` se ignora sin aviso: documentado.
- Una vista `.tsx` con error rompe el build o el tablero (sin ErrorBoundary en `App.tsx`): documentado; «no frena» queda sólo para el módulo del server.
- Módulo y vista son independientes y opcionales: lo dicen la figura y el README.
- Cuatro carpetas `extensiones/` fuera de Git, no dos: corregido.
- `RUNNERS_EXTERNOS` e `iniciar()` faltaban en el README: agregados.
- La prueba de «no toca lo versionado» miraba la carpeta equivocada: ahora compara fechas de los SVG versionados.
- `--check` cubría sólo una figura: ahora recorre todas.
- «Coordinadora» como nombre del tablero chocaba con el rol de sesión: la figura dice «sesión coordinadora».

## Tercera ronda: delegar trabajo y memoria por proyecto

Revisión de `figuras/delegar.mjs`, `figuras/memoria.mjs`, los acentos de color de `kit.mjs` y su
lugar en el README. Diez hallazgos:

- Una cápsula ámbar (encargo) en la bandeja de vuelta y la pista «cada cápsula es un encargo» contradecían la leyenda: queda sólo la verde y la pista dice «Ámbar sale, verde vuelve».
- Lo vigente lo decide la coordinadora o una persona (README), no sólo una persona: corregido.
- Lo capturado es pedido, respuesta final, envío entre sesiones y disparo de regla: corregido en el `label`.
- 64 KB es un tope, no un tamaño fijo: corregido el comentario.
- La comprobación de anatomy miraba sólo `iso-kit.mjs`: ahora exige también `tube.mjs` y `lathe.mjs`.
- El `SKILL.md` no mencionaba `acento`, `fillet` ni `floorSvg`: agregados.
- La base repetida en cada figura pasó a `floorSvg` en `kit.mjs`.
- Orden de pintado de tubos y de la bandeja: revisado en las capturas de los dos temas, sin superposiciones erróneas; no se cambia.

## Cuarta ronda: scheduler de mejoras

Revisión de `figuras/scheduler.mjs` contra `lienzo/optimization_*.py`. Siete hallazgos, todos corregidos:

- El 100 es el tope de trabajos en cola; cada trabajo toma los 30 incidentes más recientes de un proyecto (`optimization_memory.py`): la tolva dice «30 / proyecto».
- Un cambio en los incidentes recientes encola otro análisis de los 30, no sólo de los nuevos: lo dice la leyenda.
- Los dos medidores son CPU ≤ 35 % (`MAX_CPU`) y memoria libre ≥ 1,5 GB (`RESERVA_GB`), y todo tiene que cumplirse en dos muestras seguidas (`good_samples`).
- La luz de «nadie ocupado ni permiso vigente» estaba apagada mientras la pista decía «todo en verde»: ahora es verde.
- Faltaba la llave del usuario (aprendizaje no pausado): agregada al panel.
- La figura iba al principio de la sección, junto a Caveman y RTK: pasa al párrafo del scheduler.
- El texto alternativo omitía el permiso vigente: corregido.

## Quinta ronda: «Mejoras de agentes» a pantalla completa

El panel pasó de un diálogo de 420 px (unos 2900 px de alto) a una vista de pantalla completa:
integraciones en tarjetas a la izquierda y el aprendizaje en segundo plano a la derecha. Diez
hallazgos, todos corregidos:

- Un clic dentro de la vista cerraba el panel de la sesión de atrás (`App.tsx` buscaba `.gate`): suma `.mejoras-vista`.
- Las cabeceras eran `<header>` y heredaban el encabezado global pegajoso: pasan a `<div>`.
- Cerrar desmontaba el `<dialog>` sin `close()`: ahora se cierra antes de desmontarlo.
- `width: 100vw` pasaba por debajo de la barra de scroll: la vista se dimensiona con `inset: 0`.
- El interruptor era un diseño propio sin `prefers-reduced-motion`: reusa el `.switch` del encabezado.
- La casilla con forma de interruptor lleva `role="switch"` y `aria-describedby` hacia su estado.
- El chip de estado estaba dentro del `<h3>`; la lista de trabajos vacía se dibujaba; cada trabajo repetía tipo e hipótesis: corregidos.

Verificación: `tsc`, ESLint, build y `tests-ui/mejoras.spec.ts` (6 de 6, la del interruptor
ahora toca la etiqueta); casos `frontend-lint`, `frontend-build` y `frontend-playwright` de la suite
principal; capturas a 1440 y 390 px.
