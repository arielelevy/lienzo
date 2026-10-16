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
