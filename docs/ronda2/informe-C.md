# Informe del frente C, ronda 2: enchufar la federación en el server (F1 + F2)

Registro histórico de esta ronda. Los resultados corresponden al código revisado en ese momento.

## Qué quedó, archivo por archivo

- **`lienzo/mirror.py`** (nuevo): `Mirror` y el singleton `MIRROR`.
  - `connect(pc_id, info, host, port, key, self_pc_id)` / `disconnect(pc_id)`: arranca o reemplaza
    el espejo de un peer, un `federation.SSEClient` contra `/peer/events`, snapshot completo en
    cada (re)conexión. `stop()` corta todo (para tests y apagado limpio).
  - `_apply_event`: snapshot/session/removed/pending/links/rules/ping, igual formato que `/events`
    local. pending/links/rules siempre llegan como lista completa (se reemplazan enteras, no se
    acumulan).
  - `owner_of(sid)`, `sessions()`, `pending()`, `links()`, `rules()` (con `pc` completado si el
    ítem no lo traía), `peers_status()` (alive/last_seen/health, vivo si hubo actividad hace menos
    de `PEER_TIMEOUT_S` = 45 s), `forward(pc_id, method, path, body)` → `(status, cuerpo)` tal cual
    los dio el peer, o `503` si está caído o no se conoce.
  - Salud: hilo propio, la pide cada `HEALTH_EVERY_S` = 15 s (espera antes del primer pedido, no
    al conectar: un peer recién emparejado no muestra salud vieja).
  - Cubierto por `tests/test_mirror.py`: 21 pruebas, con un transporte doble (sin red ni hilos
    reales): snapshot y cada tipo de evento, `owner_of`, el tageo de `pc`, salud viva/caída,
    `forward` con status/cuerpo tal cual, peer desconocido y peer caído.

- **`lienzo/federation.py`** (además de lo que ya traía la ronda 1, ajustes míos):
  - `PeerConn` suma `self_pc_id` (con quién identificarse, header `X-Lienzo-Peer`); default vacío,
    no rompe la construcción vieja.
  - `HTTPTransport.request(peer, method, path, body) -> (status, cuerpo)`: nuevo, para el enrutado
    (necesita el código real del peer, no solo el cuerpo). `get/post/put/delete` no cambiaron su
    firma pública.
  - Sin tocar firma ni comportamiento de nada más de ronda 1. Los 28 tests de
    `tests/test_federation.py` siguen en verde sin cambios.

- **`lienzo/server.py`** (soy el único que lo toca esta ronda):
  - Listener de peers (`PeerHandler`, clase nueva): segundo `ThreadingHTTPServer` en
    `--peer-port` (7322 por defecto) bind a `--peer-host` (autodetectada por `_lan_ip()` si no se
    pasa). Solo atiende `/peer/*` (404 el resto); toda request firmada
    (`X-Lienzo-Peer`/`-Ts`/`-Nonce`/`-Sig`, verificada con `federation.verify` contra la clave del
    peer en `peers.json`) salvo `GET /peer/hello` y `POST /peer/pair`. Log con la etiqueta `peer`
    (vía el `log()` de siempre, que ya tiene tags).
  - Rutas de peer: `hello`, `pair` (→ `pairing.accept`), `snapshot` (estado local, nunca lo que
    esta PC espeja de un tercero, evita que una malla de 3-4 PCs reenvíe en círculo), `health`
    (→ `health.snapshot()`), `events` (SSE, misma verdad local), `launch` (→ `launch.launch`),
    `rules/lock` y `rules/check` (→ `rules.handle_peer_lock`/`handle_peer_check`, con `getattr`:
    todavía no existen del lado de B), y `/sessions/<sid>/<vista|acción>`, `/sessions/<sid>` DELETE,
    `/pending/<id>` POST, los mismos comandos que la UI local, ejecutados contra la sesión de
    verdad de esta PC.
  - Enrutado (F2): `_route_session(sid)` decide local vs. remota; `send`, `interrupt`,
    `approve`, `dialog`, `attach` (POST), `title`, `stopped`, `coordinator` (PUT), `DELETE
    /sessions/<sid>`, `POST /pending/<id>` reenvían con `mirror.MIRROR.forward` y devuelven código
    y cuerpo tal cual. `attach` viaja en base64 adentro del JSON (no hay transporte binario en
    `HTTPTransport` todavía: más tráfico, un solo camino). Peer caído → 503 con
    `{"error": "sin conexión con <nombre>"}`. Las vistas remotas (`digest`/`turns`/`screen`/
    `connections`) se piden a la dueña bajo demanda, con la misma query string (`n`, `before`).
  - **`GET /sessions`, `GET /pending`, `GET /events`**: mezclan local + espejo. `/events` reemite un
    snapshot completo a los clientes del tablero (lista separada `ui_clients`, nunca a un peer que
    esté escuchando `/peer/events`: ahí solo va la verdad local, para no amplificar en una malla).
  - **`GET /peers`**: la propia PC primero (`local: true`, con `identity.pc_info()` +
    `health.snapshot()`), después cada peer (`mirror.MIRROR.peers_status()`). Sin peers, un array
    de un elemento. `POST /peers/offer` / `POST /peers/join` (→ `pairing.offer`/`join`, 501 si
    `pairing.py` no está disponible), `DELETE /peers/<pc_id>` (corta el espejo y lo saca de
    `peers.json`), `PUT /peers/self {name}` (→ `identity.set_name`).
  - **`POST /rules`**: `new_rule` agrega `"pc": identity.pc_id()`. `check_rule` acepta un destino
    (`to`/`from`) que viva en otra PC (antes solo miraba `sessions` local: un `to` remoto daba 404
    de siempre, un bug real de esta misma ronda que quedó corregido). `create_on_stop` llama a
    `check_global_loop` (→ `rules.loop_conflict`, con `getattr`). `create_rule` llama a
    `check_remote_destination` cuando el `to` es de otra PC (→ `rules.check_at_destination` /
    `rules.loop_lock`, con `getattr`: todavía no existen).
  - Canal nativo entre PCs: un `send` con `native: true` cuyo `link_to` (o `from`) es de otra
    PC devuelve `409 {"error": "el canal nativo no cruza PCs"}`, sin tocar la consola.
  - **`POST /sessions/launch`**: local (→ `launch.launch`) o reenviada a `pc` por `/peer/launch`.
  - **`main()`**: `--peer-port`, `--peer-host`, `--peers`; arranca el listener solo si hay peers
    guardados o se pasó `--peers`; conecta el espejo de cada peer de `peers.json` al arrancar;
    arranca `beacon.start()` + un hilo que aplica `beacon.seen()` a `peers.json`/al espejo
    (`_beacon_sync_loop`), si `beacon.py` está disponible.
  - `pairing.py`, `launch.py`, `beacon.py` se importan con import perezoso + `try/except`: si no
    existen (o quedan momentáneamente rotos a mitad de una edición de otro frente, en el mismo
    working tree) el server sigue funcionando, esas rutas contestan 501 en vez de tirar abajo el
    proceso.

- **`tests/test_mirror.py`** (nuevo): 21 pruebas, arriba.
- **`tests/test_peer_server.py` (nuevo): 5 pruebas de punta a punta con dos procesos reales**
  (PC A = este proceso de test con `LIENZO_HOME` propio + un `server.Handler` real; PC B = un
  subproceso con su propio `LIENZO_HOME`, un `server.PeerHandler` real y una tarjeta + un pendiente
  de prueba), la clave del par derivada y escrita directo en los dos `peers.json` (sin pasar por
  `pairing.py`, que ya prueba eso `test_pairing.py`):
  - el listener solo atiende `/peer/*` y exige firma (salvo `hello`);
  - una firma con la clave equivocada da 401, la correcta 200 con el `/peer/snapshot` real;
  - punta a punta completo: `GET /sessions` en A mezcla la tarjeta de B (con `pc` correcto);
    `POST /sessions/<sid-de-B>/interrupt` viaja firmado, se verifica y corre de verdad en B (409
    real "sin PID vivo", no un 404 disfrazado); `POST /pending/<id>` enrutado deja la respuesta en
    el disco de B; una sesión desconocida en las dos puntas sigue dando 404;
  - el espejo refleja un cambio de B (un `PUT /sessions/<id>/title`) sin que nadie vuelva a pedir
    el snapshot;
  - un `forward` sin B corriendo da 503.
- Ajustados por mi cambio (regresiones que introduje y arreglé en el mismo commit lógico):
  - `tests/test_server.py::test_las_claves_de_una_regla_nueva_no_cambian_de_orden`: sumé `"pc"` al
    orden esperado (consecuencia directa de `new_rule`).
  - `tests/test_integration_guards.py::test_pi_missing_log_is_not_reported_as_empty_conversation`:
    monkeypatchaba `h._session`, que `_session_view` ya no llama (ahora usa `_route_session`, que
    lee `state.sessions` de verdad, para poder reenviar). Cambié el test para plantar la tarjeta en
    `st.sessions` con la fixture `aislado`, en vez de mockear el método.
  - Until y no perdí ningún comportamiento viejo: reordené `_put_title`/`_put_stopped`/
    `_put_coordinator` para que la validación del cuerpo (400) siga ganándole al 404 de sesión
    desconocida, exactamente como antes (lo verifica
    `test_una_vista_desconocida_de_una_tarjeta_no_dice_sesion_desconocida`); `DELETE
    /sessions/<id>` de una tarjeta que no existe en ningún lado sigue devolviendo `200` (idempotente,
    como siempre), no un 404 nuevo.

## Qué medí

- **`tests/test_mirror.py` + `tests/test_peer_server.py`**: 26 pruebas, ~8.7 s (incluye levantar y
  bajar dos procesos Python cinco veces).
- **`python -m pytest tests -q` (suite completa): 385 passed**, ~26 s, cinco corridas seguidas
  sin fallos intermitentes (antes de fijar el punto de abajo, tuve una corrida con un 401 en vez de
  503, ver "qué dejé afuera / trampa").
- Latencias reales, punta a punta, dos procesos por sockets de LAN local (127.0.0.1), medidas
  dentro de `test_punta_a_punta_dos_pcs_mirror_sessions_y_enrutado` (varias corridas):
  - `GET /sessions` mezclado (local + espejo): 1.5 a 3.4 ms.
  - Un comando enrutado (`POST .../interrupt`, firmado, verificado y ejecutado en el otro proceso):
    2.4 a 27 ms (varía con la carga de la máquina, ~53 procesos `node` corriendo en simultáneo
    durante esta ronda; sin esa carga debería ser más estable cerca del piso).
  - El espejo refleja un cambio del otro lado (sin pedir snapshot de nuevo, solo el SSE) en
    3.7 ms en la corrida medida.
- `python -m ruff check` y `python -m black --check` sobre mis archivos exactos (`lienzo/server.py`,
  `lienzo/mirror.py`, `lienzo/federation.py`, `tests/test_mirror.py`, `tests/test_peer_server.py`,
  y los dos que ajusté de otros, `tests/test_server.py`, `tests/test_integration_guards.py`):
  limpios.

## Qué dejé afuera y por qué

- **`rules.check_at_destination` / `rules.loop_lock` / `rules.handle_peer_lock` /
  `rules.handle_peer_check`**: no existían en `rules.py` al momento de cerrar (pedidas por la
  coordinadora a mitad de ronda, después del informe de B). Llamadas con `getattr(..., None)`,
  igual que `loop_conflict`: si faltan, el comportamiento es el de siempre (sin chequeo remoto de
  duplicado/clash ni lock de la carrera A↔B); si el frente que las escriba usa una firma distinta a
  la que asumí, hay que ajustar `check_remote_destination` y las dos rutas
  `PeerHandler._rules_lock`/`_rules_check` en `server.py`. Detalle de la firma asumida en
  `notas-C.md`.
- Beacon UDP real entre dos procesos-PC descubriéndose: confío en los tests propios de
  `beacon.py` (frente A) y en que mi wiring en `main()` llama a las firmas correctas; no armé una
  prueba de punta a punta propia (A ya anotó que no es determinística en Windows sobre 127.0.0.1).
- Adjuntos reenviados en base64 en vez de un transporte binario nuevo en `federation.py`: ~33%
  más de tráfico en el peor caso, aceptable para lo que se adjunta desde el lienzo (texto,
  capturas chicas); no abrí un segundo camino de transporte solo para esto.
- **`/links` y `/rules` (GET) no mezclan el espejo**: el encargo común solo pedía `/sessions` y
  `/pending`; las flechas entre PCs son del front (F4), fuera de esta ronda.
- Prueba real con la notebook (terminales de prueba, plan §6 F1): no la hice, corresponde al
  cierre de F4 con hardware real, no a esta ronda de escritorio.

## Qué vi fuera de mis archivos (y dónde lo anoté)

Todo el detalle en `docs/ronda2/notas-C.md`:

- El estilo `except A, B:` (sin paréntesis) en `identity.py`/`rules.py`/`federation.py` (ronda 1)
  funciona en este Python 3.14.7 y es lo que **el propio `black` de este entorno prefiere**, lo
  confirmé dejando que `black` reformateara mis propios `except (A, B):` a esa forma. No es un bug
  a corregir, es el estilo del repo.
- El incidente del `git stash` de las 20:31 (corrido por B, según confirmó la coordinadora) se
  llevó puesto un estado intermedio de mi propio `server.py` y de `federation.py`; lo reconstruí
  desde el estado real en disco. No corrí ningún comando de git en ningún momento.
- `server.PEERS_FILE` es una constante calculada una vez al importar: un test que aísla
  `state.LIENZO` sin también aislar `server.PEERS_FILE` no alcanza a aislar las rutas de peers.
- El esquema real de `peers.json` (`pc_id`, `name`, `color`, `ip`, `port`, `key` hex) lo terminé
  fijando yo (no había contrato escrito antes de esta ronda); coincidió con lo que `pairing.py`
  (frente A) ya tenía escrito al momento de revisarlo, sin ajustes.
