# Plan de refactor de lienzo (2026-10-04)

Pedido de Ariel: revisar todo el código desde el diseño, sin errores silenciados, con patrones que
realmente apliquen; un plan, no cambios. Fuente: cuatro revisiones de solo lectura (server.py,
sessions.py + state.py, resto del backend + skill, front React), 74 hallazgos con `archivo:línea`.
Base al revisar: commit b268776, 595 pruebas Python y 104 de interfaz en verde.

Reglas para ejecutarlo: un commit por punto; si es un bug, primero la prueba que lo reproduce y
después el arreglo; la suite completa (pytest, ruff, tsc, eslint, Playwright) en verde en cada commit;
nada cambia el contrato con el front (`/sessions`, SSE) ni el formato entre PCs (`/peer/*`) salvo
donde se dice explícitamente.

Ids: S = server.py, E = sessions/state, B = resto del backend, F = front.

## Estado (2026-10-04, 01:40)

**Ola 1 hecha** (fases 0 y 1, más los hallazgos nuevos de las revisiones adversariales): 50 commits de
cuatro agentes sobre `main`, uno por punto, y la clave del par con SPAKE2 (0.4). Suite completa en
verde: 735 pruebas de Python, 115 de interfaz, tsc, eslint y build. Pusheado hasta `de4cf58`.

| Punto | Estado | Commit |
|---|---|---|
| 0.1 aprobador del skill | hecho, más los bypass que encontró la revisión (verbo por palabra, `do`/`X=`, redirecciones, git por subcomando) | 1ce69ab |
| 0.2 `expect` al aprobar | hecho (queda una ventana chica entre leer la pantalla y teclear, documentada) | 244e548, a9f19c2 |
| 0.3 auto-aprobar en otras PCs | hecho: `peers` en la respuesta, pendientes en disco que se reenvían cuando la PC vuelve, aviso en la UI | 5527702, 547067c |
| 0.4 clave del par | hecho con **SPAKE2** sobre MODP-2048 (frase de una palabra); **falta reemparejar** las dos PCs | 17e34bc |
| 0.5 `subproc.correr` | hecho (secretos, health, procs, tmux) | 989d33a |
| 0.6 secretos sin saltos de línea | hecho | 496ee7b |
| 0.7 cuerpo sin leer antes del login | hecho en Handler y PeerHandler | 0a69c1f, 9479778 |
| 0.8 JSON corruptos | hecho (state, peers.json, peer.json); falta hook.py | 8b4faf5, d806d99 |
| 0.9 / 0.10 espejo y SSE | hecho; además la salud con 401 ya no cuenta como viva | 56203c1, c2201fd |
| 0.11 flecha de envíos a otra PC | hecho (link); el copiar/pegar entre PCs sigue sin hacerse | eaff7ed |
| Fase 1 (1.1 a 1.18) | hecha | ver `git log` |
| Nuevos de la revisión | espejo que no reconectaba al cambiar la IP (41f28c8); permiso de coda invisible por la ventana del log (de4cf58); `propose_policy` (b0c81d2) | |

**Pendiente (ola 2):** 2.1 acciones de tarjeta en una tabla (en 4 commits, con prueba de paridad
antes), 2.2 reducido a `RUTAS_PUBLICAS` (ya hecho en 0.7), 2.3 registro de agentes (solo datos, en 3
partes), 2.5 fusionado con 1.7 (hecho), 2.6 parcial (`CacheEnSegundoPlano`, `_io.atomic_write`), 2.7
cliente tipado y componentes de Card, fase 3. Descartados por la revisión: 2.4 como refactor (es una
funcionalidad nueva), 2.8 y el contexto de acciones del front.

---

## Fase 0 — Seguridad y bugs que pueden hacer daño hoy (costo S salvo aclaración)

| # | Qué | Evidencia | Arreglo | Patrón |
|---|---|---|---|---|
| 0.1 | **El aprobador del skill se saltea** | B4: `skills/lienzo/aprobador.py:112-138` aprueba `gitpushoriginmain&&echo…`, `find.-delete`, `gitfilter-branch`, `cp ../../..`, `python -c` | Endurecer: push por tramo, git por subcomando exacto, rechazar `..`, sacar `python`/`py`/`find` | ninguno |
| 0.2 | **Aprobar sin mirar el comando que se aprueba (TOCTOU)** | B4: `vigilar` lee la pantalla y después `POST /approve`; `answer_coda_ask` (sessions.py:2097) solo ve que hay *un* diálogo | `/approve` acepta `expect=<hash del comando>` y teclea Enter solo si la pantalla sigue mostrando ese comando | ninguno |
| 0.3 | **Apagar auto-aprobar puede fallar en otra PC y la UI lo muestra apagado** | S1: server.py:1369-1375 siempre responde 200; F1: App.tsx:122 carga `/config` una sola vez | Respuesta con `peers: {pc: ok|error}` y aviso en la UI; `/config` se refresca cada 20 s y el PUT manda el valor deseado | ninguno |
| 0.4 | **La clave del par sale de UNA palabra** (≈13 bits, crackeable offline en ~7 min con un POST capturado) | B1: pairing.py:39 `PHRASE_WORDS = 1` | **Decisión de Ariel (2026-10-04): opción (b)**. Queda una palabra por ahora y auto-aprobar sigue propagándose a todas las PCs; Diffie-Hellman efímero (grupo MODP 14, stdlib, la frase autentica el intercambio) va PRIMERO en la segunda ola y exige reemparejar con Ariel presente. Ojo (revisión adversarial): el material para el ataque offline no es solo el emparejamiento, alcanza con cualquier beacon firmado (broadcast cada 10 s) | — |
| 0.5 | **`leer_git_local` se puede colgar para siempre** (el mismo cuelgue del Git Credential Manager ya resuelto en health) | B5: secretos.py:153-174 usa `subprocess.run(capture_output=True)` | `lienzo/subproc.py: correr(argv, entrada, timeout, sin_prompts)` con salida a archivo temporal y matar el árbol al vencer; usarlo en health, secretos, procs, tmux | ninguno: una función |
| 0.6 | **Inyección de líneas en `git credential approve`** | B6: secretos.py:113-133 no rechaza `\n` en usuario/valor; usa `netloc` (puede traer `user:pass@`) | Rechazar `\r \n \0`; host desde `hostname[:port]` | ninguno |
| 0.7 | **Leer hasta 64 MB antes de autenticar** | S7: server.py:817-855, `_prepare` lee el cuerpo antes de `_authed()` | Sin autenticar: no leer, cerrar la conexión y contestar | ninguno |
| 0.8 | **Un JSON corrupto borra datos sin aviso** (rules.json, config.json, peers.json, peer.json) | E3: state.py:259, 306-326; B15: identity.py:60, federation.py:185 | `FileNotFoundError` = vacío; `ValueError` = log + renombrar a `.corrupto-<ts>` y no escribir encima | ninguno |
| 0.9 | **El espejo de una PC se congela y se ve vivo** | B3: `SSEClient._run` solo atrapa `OSError`; un evento no-JSON, `IncompleteRead` o un error en `on_change` matan el hilo; `_health_loop` igual | `_pedir` convierte `HTTPException`/`ValueError` en `PeerError(OSError)`; los hilos atrapan `Exception` con log y siguen | ninguno |
| 0.10 | **El SSE entre PCs reconecta solo cada pocos segundos** (pierde eventos y reenvía el snapshot) | B2: federation.py:339,384 usa el timeout de conexión (5 s) como timeout de lectura; el ping es cada 15 s | `settimeout(~35 s)` después de conectar | ninguno |
| 0.11 | **Un envío a una tarjeta de otra PC pierde la flecha y el copiar/pegar** | S3: server.py:1303-1317 manda `from/link_to/copycat`, PeerHandler (1815) solo lee `text` | La PC que envía registra el link cuando el reenvío vuelve 200 | ninguno. **Confirmar con Ariel el comportamiento esperado** |

## Fase 1 — Errores silenciados y concurrencia (S cada uno)

1. **Excepciones de hilos que no llegan al log** (E6: sessions.py:667, 1440, 1840, 2186; rules.py:401, 442). Un `en_hilo(fn, *args)` que loguea el traceback, o `threading.excepthook` una vez en `server.main`.
2. **`touch()` resucita en disco una tarjeta borrada** (E1, S10: después de envíos de hasta 60 s). La guarda va en `touch`: si `sessions.get(sid) is not s`, no hace nada.
3. **`DEAD_TARGETS` sin lock** (E2: sessions.py:444, 485-521): bajo `state.lock`, `pop(old, None)`, mover a state.py. Documentar que la sucesión no sobrevive a un reinicio.
4. **Leer afuera, escribir adentro sin revalidar** (E4: `answer_coda_ask`, `set_stopped`; S9: `_send`; S11: alta de reglas). Revalidar bajo el lock o reservar antes (B11: el enfriamiento de `on_stop` se marca después de un envío de hasta 60 s → doble disparo).
5. **Una tarjeta con error corta toda la pasada de liveness** (E7: sessions.py:1905). Un `try` por tarjeta y alrededor de `sweep_once`.
6. **El mismo evento se reaplica si Windows no deja borrar el archivo** (E8: sessions.py:1482). Un set acotado de eventos aplicados.
7. **Cuatro formas de marcar «muerta», solo una avisa** (E9). `marcar_muerta(s, avisar)` única.
8. **401 sin motivo en el log** (S2: server.py:437-463; complementa lo hecho en federation): `verify` devuelve el motivo y se loguea con límite de frecuencia.
9. **JSON inválido de un peer se toma como `{}`** (S8: server.py:1639). 400 como en `Handler`.
10. **Errores que se le devuelven al cliente con detalles internos** (S13: `restore_local`). Id + traceback en el log.
11. **Envíos a todas las PCs que esconden las fallas** (S14, S1). `fan_out(method, path, body) -> (ok, fallaron)` y `unreachable` en la respuesta.
12. **peers.json leer-modificar-escribir sin lock**; el beacon escribe cada 10 s aunque no cambie la IP (B8).
13. **Una regla hacia otra PC se borra sin log si el espejo está vacío** (B10: rules.py:347). Si el espejo no está sincronizado, saltear el disparo; loguear todo borrado.
14. **Un error de disco deja un pedido sin auto-aprobar para siempre** (E16): marcar el intento solo si dio 200.
15. **`read_pending`, `load_sessions`, `listdir(EVENTS)`, `read_screen`** fallan en silencio o inundan el log (E15). Helper `avisar_si_cambia(clave, msg)` (la idea de `FuenteTemperatura._avisar`).
16. **`procinfo.py` no importa fuera de Windows** (B7: `WinDLL` fuera del `if _WIN`). Con él caen hook, procs y backend en Mac/Linux.
17. **Timeouts desalineados**: `coordinar.restaurar` 120 s contra 300 s del reenvío (B16) → reintento que duplica sesiones.
18. Front: **pantalla trabada en «conectando…»** si el server no respondía al abrir (F2); **efecto de arrastre con estado viejo** (F3: Board.tsx:386); **doble click en Permitir manda dos POST** (F7); **éxito a medias reportado como falla** en Forward (F10); **`/peers/lan` que falla se ve igual que «no hay PCs»** (F16).

## Fase 2 — Diseño: patrones que de verdad aplican

| # | Cambio | Hallazgos | Patrón y por qué | Lo que NO se hace |
|---|---|---|---|---|
| 2.1 | **Acciones sobre una tarjeta en una sola tabla** (send, approve, dialog, title, stopped, coordinator, pending, retarget, launch) usada por `Handler` y `PeerHandler`; un `locate(sid)` único en vez de 5 funciones | S4, S5, S19 (9 pares duplicados que ya divergieron; 17 `forward`) | **Tabla de despacho (Command como funciones)**: lo que se repite es el par validar+ejecutar por acción en dos handlers | Sin clases Command; sin Proxy (forward ya devuelve la misma forma) |
| 2.2 | **Rutas en una tabla con banderas** `public`, `lan_only`, `max_body` | S6: qué pide login depende de la posición en una cadena de `if` | **Tabla de despacho**: vuelve explícita y testeable una regla de seguridad. Más una prueba que liste las rutas públicas | Sin framework web |
| 2.3 | **Registro de agentes**: `agentes.py` con `Perfil` (dataclass congelada) y `AGENTES[nombre]`: exe, retomar, modelo, parser, buscar transcripción, cierre por transcripción, lee adjunto con shell, lee pantalla… El front lee capacidades del mismo catálogo | E11 (44 ramas en sessions), B12 (87 literales en 12 archivos; un agente desconocido cae a `parse_claude` sin aviso), F8 (9 ramas en el front) | **Registry + Strategy por datos** (los parsers como funciones en la tabla). Sumar un agente pasa de ~7 archivos a una entrada | **No** una jerarquía de clases por agente: las condiciones mezclan agente con estado/hooks y las clases de claude/codex quedarían vacías |
| 2.4 | **Política de auto-aprobación como estrategia** del bucle del server: `AprobarTodo` y `ListaPermitida`; el skill deja de tener su propio bucle | B4 (dos bucles sobre el mismo diálogo) | **Strategy**: dos políticas reales sobre los mismos proveedores (`ProveedorPermisos` ya existe) | — |
| 2.5 | **Transición de estado única** `set_state(s, new, cierra_turno=…)`, sin escrituras directas | E10 (4 escrituras directas; regla de agente dentro de la transición) | ninguno: función + tabla chica de efectos | **No** el patrón State con una clase por estado (4 estados, transiciones casi libres) |
| 2.6 | **Utilidades compartidas**: `subproc.correr` (0.5), `_io.atomic_write` (auth no tiene el reintento de Windows), `CacheEnSegundoPlano(ttl, medir)` (dos copias en health) | B5, B18, B20 | ninguno: funciones / clase chica | No tocar las copias deliberadas de hook.py (arranca en cada evento) |
| 2.7 | **Front**: cliente de API tipado (`sessionsApi.send/approve/…`, `rulesApi.create`), `isMissingRoute(e)` por `ApiError.status`, `useCardActions` + `<CardNeeds>` + `<PermissionPrompt>`, `usePeerStatus`, un contexto solo de acciones | F4, F5, F6, F7, F9, F11 | **Custom hooks y composición**; cliente tipado porque los cuerpos son contratos sin tipo hoy | Sin Redux ni react-query (el estado ya llega por SSE); datos por props, no por contexto |
| 2.8 | **Helper de turnos** para los 4 parsers de transcripción | B19 | ninguno: helper `_Turnos` | **No** Template Method: los formatos difieren demasiado |

## Fase 3 — Partir los módulos grandes (después de la fase 2, por pasos chicos)

- `server.py`: la lógica de reglas y restaurar sale a `rules_api.py` / `restore.py` (S12); base `JsonHandler` con leer cuerpo, json y error 500 (S15); borrar `Handler._session`, código muerto (S16).
- `sessions.py`, solo lo que baja acoplamiento: `tarjeta_texto.py` (≈250 líneas puras: títulos, adjuntos, preguntas) y `referencias.py` (reglas en espera, sucesión, links, que hoy viven en sessions para evitar el ciclo con rules). El resto (eventos, barrido, consola, permisos) solo si sigue creciendo. Ojo: ~35 `monkeypatch.setattr(ses, …)` en las pruebas; hay que moverlas, la fachada no alcanza.
- Front: `Card.tsx` se achica con 2.7, no partiéndolo por partirlo.

## Fase 4 — Opcional, con medición o decisión antes

- Firmar también el emisor y el receptor (B14) y las respuestas entre PCs (B9); `ts` estrictamente creciente por peer en el beacon (B9, S).
- Rendimiento del tablero con muchas tarjetas (F12): medir con el Profiler antes de tocar.
- Freno de emparejamiento por IP (B21); timeouts que pasa el que llama y no por sufijo de ruta (B17).

## Lo que no se toca

- El lock único con «leer afuera, aplicar adentro» (el problema son las excepciones a la regla, no la regla).
- El formato entre PCs y el contrato con el front (SSE, `code: "unknown_session"`, textos de error).
- Los controles de seguridad del server (`_host_ok`, `_csrf_ok`, `_is_local`, Content-Length estricto): se mueven a la tabla de 2.2, no se reescriben.
- El cifrado de secretos.py (bien hecho); la debilidad es la clave del par (0.4).
- `arrows-geometry.ts` y el reparto de subcolumnas del tablero: medidos y con muchas pruebas.
- send.py y screen.py como subprocesos (AttachConsole afecta a todo el proceso).
