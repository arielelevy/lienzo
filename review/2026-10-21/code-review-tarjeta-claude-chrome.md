# Code review: tarjeta de Claude en Chrome

Fecha: 2026-10-21. Pedido de Ariel: ver la extensión Claude in Chrome en el tablero como una tarjeta con el logo
de Chrome. Alcance elegido: sólo presencia (no se lee el chat).

## Cambio

- `lienzo/chrome_claude.py`: `conexiones()` busca entre los procesos (`EnumProcesses`) los hosts nativos
  `chrome-native-host.exe` (Claude Desktop) y `claude.exe` (Claude Code) cuya línea de comando trae
  `chrome-extension://fcoeoabgfenejglbffodgkkbkcdhcgfn/`. Devuelve `{pid, host, desde}`. Caché de 15 s.
  Medido: 8 ms en una PC con ~410 procesos.
- `lienzo/protocol.py`: la salud de cada PC publica `chrome_claude_conexiones`.
- `web/src/components/ChromeCard.tsx`: la tarjeta, más `ChromeLogo`, que ahora también usa `Card.tsx`.
- `Board.tsx`: las tarjetas van primero en la columna Trabajo. Respetan el filtro de PC. No aparecen con filtro
  de repos ni con «sólo coordinadoras», y tampoco para PCs caídas.

## Revisión

- La línea de comando se lee solo de los procesos con nombre de host, no de todos.
- Una PC con una versión anterior no manda el campo: el front lo toma como `[]`.
- El host de Claude Desktop vive mientras la extensión está conectada, no solo mientras el panel está abierto.
  La tarjeta dice «Extensión conectada», no «panel abierto».
- Riesgo menor: el contador de la columna no cuenta la tarjeta de Chrome. Con el tablero sin ninguna sesión,
  las columnas colapsan y la tarjeta no se ve (`sinTarjetas`).
- La tarjeta no es un botón: no abre panel ni tiene menú, porque no hay nada que mandarle.

## Pruebas

- `tests/test_chrome_claude.py`: hosts válidos (desktop y code), descarta el `cmd.exe` envoltorio, otro
  `claude.exe` y otro origen. Fuera de Windows da `[]`.
- `tests/test_health.py`: clave nueva en el snapshot.
- 82 passed en las pruebas relacionadas. `npm run build` y `eslint` sin errores.
- En vivo: server reiniciado, `GET /peers` trae `{"pid":24780,"host":"desktop"}` y Playwright encuentra
  `.card.chromeext` con «Claude en Chrome · Extensión conectada vía Claude Desktop».
