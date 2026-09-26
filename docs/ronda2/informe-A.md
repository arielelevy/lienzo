# Informe del frente A · ronda 2: emparejamiento, beacon y firewall

## Que queda

- **`lienzo/pairing.py`** (nuevo): `offer(ttl_s=300)`, `accept(req)`, `join(phrase, host, port)`,
  las tres firmas exactas del encargo.
  - `offer()` genera una frase de seis palabras (`auth.new_passphrase()`) y la deja pendiente en
    memoria, una sola a la vez. Cubierto por `test_offer_da_una_frase_de_seis_palabras_y_vencimiento_futuro`.
  - `accept(req)` valida `{pc_id, name, color, port, proof}` contra la frase pendiente
    (`federation.derive_pair_key` + un HMAC donde cada lado firma su **propio** `pc_id`, no el del
    otro). Si da: guarda el peer con `federation.add_peer` (la clave del par en hex), consume la
    frase y devuelve `pc_info()` + el puerto propio (`PEER_PORT = 7322`, pisable con
    `LIENZO_PEER_PORT`) + su proof de vuelta. Si no da: `PairingError` con el motivo (frase
    vencida/inexistente, proof invalido, tope de `federation.MAX_PEERS`). Cinco intentos fallidos
    (proof invalido o frase vencida) bloquean `accept` 15 minutos, igual que `auth.login`. Cubierto
    por `test_accept_sin_oferta_pendiente_rechaza`,
    `test_accept_con_proof_correcto_guarda_el_peer_y_devuelve_proof_de_vuelta`,
    `test_accept_consume_la_frase_un_segundo_intento_ya_no_sirve`,
    `test_accept_con_frase_vencida_rechaza`, `test_accept_con_proof_invalido_rechaza`,
    `test_accept_con_proof_invalido_no_consume_la_frase`, `test_accept_respeta_el_tope_de_peers`,
    `test_cinco_intentos_fallidos_bloquean_accept_quince_minutos`,
    `test_bloqueo_se_libera_pasados_los_quince_minutos`, `test_mi_port_respeta_la_variable_de_entorno`.
  - `join(phrase, host, port)` no conoce el `pc_id` de la otra PC de antemano: pega `GET
    /peer/hello` (sin firma) y recien ahi arma el proof para `POST /peer/pair`; verifica el proof de
    vuelta antes de guardar el peer. Cubierto por un punta a punta real con sockets: la PC que
    ofrece corre en este proceso (con un `ThreadingHTTPServer` de prueba que envuelve `accept()`
    tal como lo va a enchufar C — ver `docs/ronda2/notas-A.md`), la que pega la frase corre en un
    subproceso con su propio `LIENZO_HOME` (`test_join_punta_a_punta_contra_un_server_http_real`,
    `test_join_con_frase_equivocada_no_guarda_nada_de_ningun_lado`,
    `test_join_sin_server_del_otro_lado_da_un_error_claro`).

- **`lienzo/beacon.py`** (nuevo): `start(port, stop_event) -> threading.Thread`, `seen()`.
  - `start()` levanta un hilo que cada `interval_s` (10 s en produccion) manda, por cada peer
    emparejado, un beacon UDP firmado con la clave de ESE par (`federation.encode_signed_beacon`) y
    escucha los de los demas; el que decodifica con la clave de un peer conocido llama a
    `federation.update_peer_ip`. `port` es el puerto TCP propio que se anuncia (7322); el socket UDP
    en si usa `udp_port` (7323 fijo, `BEACON_PORT`, pisable solo para pruebas) y `broadcast_addr`
    (pisable a `127.0.0.1` para pruebas reales sin depender del broadcast de la LAN). Nunca deja
    escapar una excepcion del hilo. Cubierto por `test_recibir_un_beacon_valido_actualiza_la_ip_y_seen`,
    `test_recibir_beacon_de_un_peer_desconocido_no_rompe_ni_actualiza_nada`,
    `test_recibir_basura_no_rompe`, `test_recibir_sin_nada_en_el_socket_no_bloquea`,
    `test_enviar_manda_un_paquete_firmado_por_cada_peer`, `test_enviar_sin_peers_no_manda_nada_ni_revienta`,
    `test_enviar_con_key_corrupta_sigue_con_el_resto`,
    `test_start_devuelve_un_hilo_vivo_y_stop_event_lo_frena`,
    `test_start_nunca_explota_si_no_puede_abrir_el_socket`,
    `test_start_con_un_peer_se_escucha_a_si_mismo_y_actualiza_seen` (ciclo completo real: el mismo
    hilo se manda un beacon a si mismo por loopback y lo ve en `seen()`).
  - Lo que no probe: dos procesos-PC descubriendose entre si por broadcast real (no determinista en
    Windows con sockets compartiendo puerto en 127.0.0.1 — ver `notas-A.md`, queda para la prueba
    real en la notebook, plan §6).

- **`install.py`**: agregue `--peer` (regla de firewall de Windows, 7322 TCP y 7323 UDP, perfil
  Privado; `--uninstall --peer` la saca) y `--dry-run` (cubre firewall **y** los hooks existentes:
  `merge_hooks`, `merge_pi`, `ensure_state` ahora aceptan `dry_run` y solo imprimen). Sin permisos
  de administrador, `peer_firewall` avisa claro y no toca nada (ni siquiera intenta `subprocess.run`).
  Cubierto por `tests/test_install_peer.py` (13 tests): forma exacta de los comandos `netsh`
  (`test_firewall_args_alta_perfil_privado`, `test_firewall_args_baja`), dry-run sin llamar a
  `subprocess.run` en ningun caso (`test_peer_firewall_dry_run_no_ejecuta_nada`,
  `test_peer_firewall_dry_run_no_requiere_admin`), sin admin no llama a nada
  (`test_peer_firewall_sin_admin_no_toca_nada`), con admin llama una vez por regla
  (`test_peer_firewall_con_admin_llama_netsh_para_cada_regla`,
  `test_peer_firewall_uninstall_borra_las_dos_reglas`), un netsh que falla no revienta
  (`test_peer_firewall_informa_el_fallo_de_netsh_sin_reventar`), y que `--dry-run` tambien frena los
  hooks y `ensure_state` sin escribir nada (`test_merge_hooks_dry_run_no_escribe_nada`,
  `test_merge_hooks_sin_dry_run_si_escribe`, `test_ensure_state_dry_run_no_crea_carpetas`,
  `test_merge_pi_dry_run_no_escribe_nada`). Un fixture `autouse` hace que **cualquier** test que se
  olvide de mockear `subprocess.run` reviente en vez de tocar el firewall de la maquina.

- **`lienzo/identity.py`**: sumé `set_name(name)` (cambia el nombre de la PC sin tocar el `pc_id`,
  para la pantalla de emparejamiento; rechaza nombre vacio). Cubierto por
  `test_set_name_cambia_el_nombre_sin_tocar_el_pc_id` y `test_set_name_vacio_rechaza` en
  `tests/test_identity.py`.

## Que medi

- Tests nuevos de esta ronda: **55** (`test_pairing.py` 14, `test_beacon.py` 10,
  `test_install_peer.py` 13, más 2 nuevos en `test_identity.py`; los 8 de `test_home.py` ya
  existian de ronda 1 y siguen en verde). Corrida de los cuatro archivos nuevos/tocados juntos:
  **63 passed en 8,7 s**. Maquina sin otra tarea pesada corriendo (`Get-Process node` antes de medir
  no mostro nada propio bloqueando).
- Emparejamiento de punta a punta (`join()` real contra un server HTTP real, dos procesos con
  `LIENZO_HOME` distintos, dos derivaciones scrypt): **293 ms** (una corrida suelta; el costo lo
  domina scrypt igual que anticipaba el encargo).
- `python -m ruff check` y `python -m black --check` sobre mis archivos exactos (`lienzo/pairing.py`,
  `lienzo/beacon.py`, `lienzo/identity.py`, `install.py` y sus cuatro archivos de test): limpios.
- Corrida completa, `python -m pytest tests -q`: **37 failed, 11 errors, 329 passed**. Los 48
  problemas son todos de `tests/test_mirror.py` y `tests/test_rules_federadas.py` (frentes B/C,
  trabajo en progreso en el momento exacto de la corrida: `sessions` sin atributo `mirror`, `rules`
  sin `loop_conflict`, `set_coordinator()` sin `scope=`) — no toque ninguno de esos tres archivos.
  Detalle en `docs/ronda2/notas-A.md`.

## Que deje afuera y por que

- Una prueba automatica de dos beacons de procesos distintos descubriendose por broadcast real en
  127.0.0.1: no determinista en Windows (ver `notas-A.md`). Queda para la prueba real con la
  notebook (plan §6, cierre de F1).
- No enchufe nada en `server.py` (`/peer/hello`, `/peer/pair`, el listener `:7322`, el hilo del
  beacon): es del frente C esta ronda; dejé las firmas exactas y las notas de que rutas y
  respuestas necesita para llamar a `pairing.accept()`/`identity.pc_info()`.
- No marque nada del checklist del plan.

## Que vi fuera de mis archivos

- Todo en `docs/ronda2/notas-A.md`: las rutas que necesita agregar C (`/peer/hello`, `/peer/pair`,
  el codigo de error sugerido), la variable nueva `LIENZO_PEER_PORT` para que el listener real la
  respete igual que `LIENZO_HOME`, y una anomalia rara donde `install.py` y `lienzo/identity.py`
  volvieron solos al contenido de HEAD a mitad de la sesion (sin que yo corriera ningun comando de
  git) — las rehice y confirme con `git status` que quedaron, pero lo anoto por si la coordinadora
  ve algo raro al mergear.
- Las fallas de `test_mirror.py`/`test_rules_federadas.py` (ajenas, en progreso): detalladas arriba
  y en `notas-A.md`, no las toque.
