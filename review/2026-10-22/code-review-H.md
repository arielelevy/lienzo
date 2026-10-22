# Code review — encargo H (2026-10-22)

Alcance: `lienzo/bitacora.py` (nuevo), `lienzo/remote_run.py`, `lienzo/server.py` (sólo el delta H),
`tests/test_rechazos_run.py` (nuevo), `pruebas-agenticas/rechazos_e2e.py` (nuevo). Skill `code-review`, nivel medium.

| # | Hallazgo | Resultado |
|---|---|---|
| 1 | `permitted()` aceptaba abreviaturas largas de git (`--upload-pac`, `--rece`, `--forc`) | Corregido: se niega todo prefijo de force/force-with-lease/force-if-includes/upload-pack/receive-pack/exec/output/strategy. Test rojo→verde. |
| 2 | Se registraba `CF-Connecting-IP` como IP también en el listener de peers y en la LAN | Corregido: la IP del túnel sólo se toma en `Handler` con `_via_tunnel()`/`_client_ip()`; en peers, siempre `client_address`. Test rojo→verde. |
| 3 | Sin límite de frecuencia: un peer con el reloj corrido llenaba el tope y borraba la evidencia | Corregido: el mismo rechazo va una vez por 60 s y la siguiente línea lleva `omitidos`. El diccionario tiene un tope de 512 claves. Test rojo→verde. |
| 4 | Una excepción del registro tumbaba la respuesta 401/403 | Corregido: `try/except` con traceback al log; la respuesta sale igual. Test rojo→verde. |
| 5 | `?n=²` daba 500 (`isdigit` con Unicode) | Corregido: `isascii() and isdigit()`. Test rojo→verde. |
| 6 | Si `_run` explotaba, no quedaba la línea del comando | Corregido: `try/finally`; la línea queda con código 500. Test rojo→verde. |
| 7 | `permitted()` mira sólo el nombre base (un `D:/x/git.exe` pasa) | Sin cambio: el argv sale del `config.json` local, que escribe el dueño de la PC, y una ruta explícita es intencional. El pedido remoto no manda argv. |
| 8 | `_negada` rechaza `-mfix` o `-Sfoo` (una f en el valor pegado) | Sin cambio, a propósito: falla cerrada. El valor va aparte (`-m`, `fix`). Queda documentado en el docstring. |
| 9 | Duplicaba `_client_ip`; `urlparse` tomaba `//x` como host | Corregido: usa los helpers y `path.split("?")`. Además, http.server ya colapsa `//`; el test lo fija. |
| 10 | `ultimas()` leía con el lock tomado | Corregido: lee sin lock (el archivo sólo crece o se renombra entero). |

Verificación después de los arreglos: `tests/test_rechazos_run.py` + `tests/test_mejoras.py`, 50 pasan. Los 15 focales
de server, peers y seguridad: 383 pasan. Runner: los dos casos OK (falta baseline). Ruff check y format limpios en
las rutas propias.

Límites conocidos (no corregidos): `claude_pipe.py:49` (`send_error(403)`, listener propio) y el 400 de handshake de
`ws.py:174` no pasan por `_json` y no quedan registrados.
