# Informe · el server colgado del 2026-10-05

## Resumen

El server quedó bloqueado al escribir en la consola. A las 14:50 la consola
dejó de aceptar texto. `state.log` escribía el archivo y después hacía `print` en el mismo hilo,
así que cada hilo que logueaba quedaba trabado en el `print`. A las 14:57:33 un hook logueó con el
`lock` de las tarjetas tomado y ya no lo soltó. Desde ahí `GET /sessions`, la liveness, la salud de
los pares y el espejo esperaron ese lock hasta que se mató el proceso, a las 23:29.

El cambio de red ocurrió después, mientras el server ya estaba colgado: la PC se suspendió a las
18:31 y volvió a las 23:00 en otra red.

## La evidencia

Del `~/.lienzo/lienzo.log` y de los eventos de Windows:

1. El par dejó de recibir respuestas a las 14:50. `ar-it33940` le pide `/peer/health` a esta PC
   cada 15 s, y su timeout es de 5 s. Hasta las 14:50:47 los pedidos llegaban cada 15,1 a 15,5 s.
   Desde las 14:51:07 llegaban cada 20,2 s, hasta las 17:50:20: cada pedido llegaba y se
   anotaba en el log, pero nunca recibía respuesta. El intervalo de 20,2 s es la espera de 15 s
   más el timeout de 5 s.
2. El último log hecho con el lock tomado es de las 14:57:33: `chess/f719c8f9: idle_prompt sin
   pregunta al final`. Viene de `sessions.py:1145` (`hook_notification`), que corre adentro de
   `with lock:` de `apply_event` (`sessions.py:1358`).
3. Después de esa línea sólo loguearon hilos que no esperan el lock: el hilo de temperatura a
   las 15:17 y el beacon a las 15:56. Cada uno escribió su línea en el archivo y se trabó en el
   `print`. No quedó en el log nada de lo que sí espera el lock: ni la liveness, que debería haber
   borrado tarjetas muertas, ni los timeouts de la salud y el SSE del espejo, que hubieran aparecido
   al volver de la suspensión en otra red.
4. La red no cambió hasta las 18:31. El log de eventos de Windows no tiene ningún cambio de
   red entre las 17:40 y las 18:31. Recién ahí aparece la suspensión: Kernel-Power 42 a las 18:31:42
   y la vuelta a las 23:00:38, en la red «ARIEL 2» con Tailscale conectado.

Qué trabó la consola no quedó registrado en ningún lado. En una ventana de conhost, un click
adentro abre una selección de QuickEdit, y eso frena toda escritura hasta que se aprieta `Esc`.
Esa ventana se había usado a las 14:36 para relanzar el server durante la prueba de Tailscale, pero
eso no prueba el click. Para no tener que deducirlo la próxima vez, ahora el vigía deja en el log qué hilo retiene el lock y dónde
está parado (ver más abajo).

## La causa en el código

| dónde (en HEAD 96d4124) | qué hacía |
|---|---|
| `lienzo/state.py:171-176` (`log`) | `print(..., flush=True)` en el hilo de quien loguea |
| `lienzo/sessions.py:1358` → `:1145` | un hook loguea con `lock` tomado (hay más casos así: `rules.py`, `sessions.py:1579`, `:1614`) |
| `lienzo/server.py:1303` (`GET /sessions`) | `with lock:` espera |
| `lienzo/server.py:176` (`_local_state`, vía `mirror.on_change`) | los hilos del espejo esperan el mismo lock |

Para confirmar que no había otro bloqueo del mismo tipo, corrí la suite entera con un vigía que
anota toda llamada que puede esperar (sockets, subprocesos, `sleep`, `Event.wait`, `Queue.get`,
`print`) hecha con el `lock` tomado. Fuera de los `print` del log, no encontró nada que espere sin
límite: el `Event.wait` que aparece es el arranque de un hilo (`en_hilo`), y los `sleep` son de
pruebas que lo reemplazan. Ningún pedido a un par corre con el lock tomado.

## El arreglo (commit en `main`, sin push)

- El log ya no bloquea a quien loguea (`state.py`). Escribe el archivo y deja la línea en una
  cola de hasta 2000 líneas. Un hilo `consola` es el único que hace `print`. Si la consola se traba,
  se traba sólo ese hilo. Con la cola llena, las líneas que no entran se descartan y al vaciarse se
  avisa cuántas no salieron por consola. El archivo las tiene todas.
- El lock dice quién lo tiene (`state.LockVigilado`, que reemplaza al `RLock` y se usa igual).
  Un hilo `vigia` lo mira cada 2 s. Si el lock lleva más de 10 s tomado, deja en el log la pila del
  hilo que lo retiene, una vez por episodio. Si la consola lleva más de 5 s trabada, también lo
  avisa una vez.
- **`GET /salud`** no toma el lock. Devuelve el estado del lock (qué hilo lo tiene y desde hace
  cuánto), el de la consola (cola, líneas descartadas, segundos trabada), los pares (`alive`,
  `last_seen`, diagnóstico), los listeners y su IP, el último cambio de red y la cantidad de hilos.
  `ok` es `false` si el lock lleva más de 1 s tomado o la consola más de 5 s trabada.
- Red (`server.py`):
  - `ListenersDePares` y `red_loop` revisan cada 10 s la IP de LAN y la de Tailscale. Si alguna
    cambió, cierran el listener de la IP vieja, abren el de la nueva, lo registran con el motivo
    (`red: la IP de la LAN cambió de A a B`, `Tailscale sin red (era X)`) y hacen reconectar el
    espejo enseguida. Antes el listener de la LAN se ligaba una sola vez al arrancar, y el de
    Tailscale no se volvía a abrir si Tailscale se apagaba y se prendía.
  - Sin IP de LAN, ya no se escucha en 127.0.0.1, que a ningún par le sirve. Se registra una vez
    con el motivo y el listener se abre cuando vuelve la red. Reemplaza al hilo
    `_tailscale_listener_loop`.
  - `PeerHandler.timeout = 60 s`: una conexión entrante de un par que no lee ni escribe se corta,
    en lugar de dejar un hilo esperando para siempre.
- Pares caídos (`mirror.py`): `revisar_vivos()` corre en cada vuelta de la salud y registra
  cada transición. Por ejemplo: `par ar-it33940: caída (sin noticias hace 47 s; <diagnóstico>)` y
  `par ar-it33940: de vuelta`. Antes la caída sólo se veía en el tablero.

## Las pruebas

Están en `tests/test_red_resiliente.py`, 8 pruebas.

- `test_consola_trabada_no_deja_sin_respuesta_a_sessions` reproduce el camino de las 14:57: un
  stdout que no vuelve del `write` y un `Notification idle_prompt` que se loguea con el lock
  tomado.
  - Sin el arreglo, falla: `GET /sessions no contesto en 3 s: el hook se quedo con el lock
    trabado en el print` (TimeoutError).
  - Con el arreglo: contesta en milisegundos y el archivo de log tiene la línea.
- `test_con_un_par_colgado_sessions_contesta` usa un par que acepta la conexión y nunca habla. La
  salud y un reenvío quedan esperando su timeout, `GET /sessions` contesta en menos de 0,5 s en
  las cinco llamadas, y al vencer el par queda `alive: false`, con su diagnóstico y con la línea
  «caída» en el log. Esta prueba ya pasaba antes en la parte de `/sessions`: ningún pedido a un par
  corre con el lock tomado. Lo nuevo es el registro de la caída.
- Las otras seis cubren:
  - que la cola de la consola descarta y avisa cuántas líneas no salieron;
  - el timeout del listener de pares;
  - el cambio de IP de 127.0.0.1 a 127.0.0.2, que vuelve a ligar el listener y lo registra, y la
    falta de red, que lo cierra;
  - el reintento de un bind fallido, que se avisa una sola vez;
  - que `/salud` contesta con el lock tomado y dice qué hilo lo tiene;
  - que el vigía deja la pila de quien retiene el lock.
- `test_ola1_seguridad.py::test_lan_ip_avisa_cuando_no_hay_red` reemplaza a la prueba anterior
  del S17: sin red, `_lan_ip` ahora da `None` y lo avisa una vez con el motivo.
- Suite completa: 935 pasan y 1 se saltea, en 3 min 10 s. `ruff check` está limpio en lo que
  toqué; los dos avisos que quedan son de antes, en `launch.py:81` y `sessions.py:2170`.
- Prueba con el server real: levanté un server aparte con su propio `LIENZO_HOME`, en el puerto
  7398 (pares en 17322, beacon en 17323), y un par falso colgado en 127.0.0.1:17999. Durante 80 s,
  `GET /sessions` contestó siempre en 3 a 14 ms. A los 20 s el log dijo `par colgada: caída (no
  contestó desde que se conectó; …)`, y `/salud` lo mostró con su diagnóstico. Después lo apagué.

## El reinicio de 7321

A las 00:02:53 del 2026-10-06 reinicié el server de 7321 con `POST /restart` (compiló y se
relanzó en la misma ventana). A las 00:02:59 volvió con 12 sesiones (9 vivas), 5 reglas activas y
el listener de pares en 192.168.1.72:7322. Respondió `/sessions` en 10 ms y `/salud` dio
`ok: true`. Fue el único reinicio.

## Lo que quedó afuera

- Se sigue logueando con el lock tomado en `sessions.py`, `rules.py` y `rules_api.py`. Ya no
  traba porque el log no bloquea, así que no lo moví: hacerlo tocaba muchos caminos sin ganar nada.
- **El HTTP local (`Handler`) no tiene timeout de socket**, a diferencia del de pares. Sólo lo
  alcanza 127.0.0.1 o el túnel, y un cliente mudo traba únicamente su propio hilo.
- No probé un cambio de red de verdad. La reconciliación de listeners está probada con
  127.0.0.1 y 127.0.0.2, y el arreglo de la causa no depende de la red. La prueba real queda para
  la próxima vez que Ariel cambie de red con Tailscale: ahí `/salud` y el log van a decir qué pasó.
- **Hay otro `lienzo-server` corriendo desde el 2026-10-02 en el puerto 7399** (PID 39924/5472,
  `--port 7399 --no-sweep`, sin sesiones). No lo toqué: parece de una prueba vieja de otra sesión.
- **Una prueba vieja escribe en el `lienzo.log` real.** A las 23:57:02, durante la suite, apareció
  la línea `peers.json corrupto (...)` con una ruta de `Temp`: algún hilo de esa prueba logueó
  después de que se restaurara `state.LOG`. No viene de las pruebas nuevas, y no la busqué.
