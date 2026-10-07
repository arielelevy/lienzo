# Informe del frente C · federacion, sin enchufar

Registro histórico de esta ronda. Los resultados corresponden al código revisado en ese momento.

## Que queda

- **`lienzo/federation.py`** (nuevo, ~340 lineas): todo el modulo del plan §1, §3.1, §3.2, §3.3 y
  §4, sin engancharse a `server.py` (eso es ronda 2). Docstring de modulo con las piezas y lo que
  falta para enchufarlas.
  - Firma y replay: `sign`, `verify`, `NonceCache` (registro de nonces acotado en memoria, se purga
    solo). Cubierto por `test_firma_buena_pasa`, `test_cambiar_*_rompe_la_firma` (cuerpo, ruta,
    metodo, ts, nonce), `test_ts_fuera_de_ventana_se_rechaza`, `test_ts_dentro_de_ventana_pasa`,
    `test_mismo_nonce_dos_veces_se_rechaza`, `test_nonce_cache_purga_los_vencidos_y_queda_acotado`.
  - Emparejamiento: `derive_pair_key` (scrypt de stdlib, mismos parametros que `auth.py`, sal de
    los dos `pc_id` ordenados). Cubierto por `test_misma_frase_y_mismo_par_dan_la_misma_clave_...`,
    `test_frase_equivocada_da_clave_distinta`, `test_distinto_par_da_clave_distinta`.
  - `peers.json`: `add_peer`, `remove_peer`, `list_peers`, `update_peer_ip`, escritura atomica,
    tope `MAX_PEERS = 4`. Cubierto por `test_alta_baja_y_lista_de_peers`,
    `test_actualizacion_de_ip_por_pc_id`, `test_tope_de_cuatro_peers`,
    `test_escritura_atomica_no_deja_tmp`, `test_archivo_corrupto_no_rompe`.
  - Beacon UDP: `encode_beacon`/`decode_beacon` y la variante firmada
    `encode_signed_beacon`/`decode_signed_beacon`. Cubierto por
    `test_codificar_y_decodificar_el_anuncio`, `test_decodificar_basura_no_rompe`,
    `test_anuncio_firmado_solo_lo_acepta_quien_tiene_la_clave_del_par`, y
    `test_beacon_real_con_dos_sockets_udp_en_loopback` (dos sockets UDP reales en 127.0.0.1).
  - Cliente SSE: `SSEClient`, con reconexion y backoff inyectable, y `on_reconnect` llamado en cada
    conexion (incluida la primera), como pide el plan ("al (re)conectar pide el snapshot
    completo"). Cubierto por `test_cliente_sse_reconecta_con_backoff_y_avisa_para_pedir_snapshot`
    contra un `ThreadingHTTPServer` real que corta la conexion a proposito.
  - Transporte: `Transport` (Protocol) y `HTTPTransport` (get/post/put/delete firmados,
    `subscribe` que devuelve un `SSEClient`). Cubierto por
    `test_transporte_http_get_y_post_firmados`, que ademas reverifica del lado servidor que las
    dos requests llegaron firmadas de verdad.

- **`tests/test_federation.py`** (28 tests): todo lo de arriba mas los dos ajustes de abajo.

## Ajustes pedidos por la coordinadora (verificacion), con test primero

1. Beacon firmado sin ts, replay desde otra IP. `encode_signed_beacon`/`decode_signed_beacon`
   ahora meten el `ts` adentro de lo firmado (no solo al lado) y `decode_signed_beacon` rechaza
   uno fuera de +-`SIGN_WINDOW_S` (30 s), con `now` inyectable para el test. Escribi primero
   `test_anuncio_firmado_viejo_se_rechaza` (dentro de la ventana pasa, 31 s despues no) y
   `test_anuncio_firmado_con_ts_alterado_sin_recalcular_la_firma_se_rechaza` (tocar el `ts` sin
   la clave del par invalida la firma), los corri en rojo (`TypeError: unexpected keyword
   argument 'ts'`), despues implemente.
2. **`verify` con `sig` no-str tira `TypeError`.** `hmac.compare_digest` exige `str` (ASCII) o
   bytes-like de los dos lados; un `sig` `None`, `bytes`, `int`, `float` o una lista reventaba con
   `TypeError` en vez de devolver `False`. Escribi primero
   `test_verify_con_firma_que_no_es_str_no_revienta` (5 casos: `None`, `bytes`, `int`, `float`,
   lista), lo corri en rojo, despues agregue el chequeo `isinstance(sig, str) and sig.isascii()`
   antes de `compare_digest`. De paso le aplique el mismo chequeo a `decode_signed_beacon` (el
   `sig` del beacon tiene el mismo problema si alguien manda basura por UDP).

## Que medi

- `python -m pytest tests/test_federation.py -q --durations=5`: 28 tests, 2.58 s en total (el
  mas lento sigue siendo el del cliente SSE, por los dos sockets TCP reales; el resto son
  milisegundos). Sin `sleep` largos: el backoff en los tests es instantaneo (0.0 s) y el UDP y el
  SSE usan `127.0.0.1` con puertos altos (`bind(("127.0.0.1", 0))`).
- Costo de `verify` por request (`test_verify_es_rapido`, 500 iteraciones sobre HMAC-SHA256 de
  stdlib): muy por debajo del umbral de 5 ms/request que puse como piso de regresion (en la
  practica, microsegundos).
- Corrida completa: `python -m pytest tests -q` → 262 pasan, 1 falla (`test_server.py::
  test_coordinadora_una_por_repo`, ajeno; ver mas abajo). `tests/test_home.py` (frente A), que en
  mi corrida anterior fallaba 7/7, ahora pasa entero: era del frente A, que seguia trabajando,
  tal como aviso la coordinadora.

## Que deje afuera y por que

- El modulo no se enchufa en `server.py`: es explicito del encargo, eso es ronda 2.
- No agregue el hilo que emite el beacon cada 10 s ni el listener UDP que lo escucha en loop: el
  encargo pide "codificar y decodificar el anuncio", no el hilo de fondo, y armar ese hilo sin
  saber todavia de donde sale `LIENZO_HOME`/`pc_id` (frente A) hubiera sido estado global
  prematuro. Lo dejo como una linea en el docstring de que falta para la ronda 2.
- `install.py --peer` (regla de firewall) es F1 pero es de `install.py`, que no es mio.
- No mido "cuanto tarda la suite completa de federacion" en la maquina bajo carga (siete sesiones
  mas): la medi sola, en un momento en que no vi otro proceso pesado corriendo (`Get-Process node`
  antes de empezar no mostro nada).

## Que vi fuera de mis archivos

- `tests/test_server.py::test_coordinadora_una_por_repo` falla ahora (no fallaba en mi corrida
  anterior): compara `session_id` esperando un orden puntual y le toco otro. Es del area de
  `sessions.py`/`rules.py` (frente B), que sigue trabajando en paralelo sobre el mismo arbol; no
  lo toque. Anotado en `docs/ronda1/notas-C.md`.
- `lienzo/auth.py` usa `except OSError, ValueError:` (lineas 51, 222, 252): la coordinadora
  confirmo que es sintaxis valida desde Python 3.14 (PEP 758), no un bug. Sin accion.
- `tests/test_home.py` (frente A): ya no falla, resuelto. Sin accion de mi parte.
