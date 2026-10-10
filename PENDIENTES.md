# Pendientes del lienzo

Esta es la única lista de pendientes; lo hecho está en MEJORAS.md y en DISENO.es.md.

Fecha: 2026-10-10.

Las casillas heredadas se conservan textuales. El 2026-10-10 se cerraron (con `[x]` y su evidencia
debajo) las verificadas en código, pruebas o decisión de Ariel; las demás siguen pendientes. La evidencia histórica no es una prueba
ejecutada hoy. Las referencias de código de esta consolidación se revisaron estáticamente.

## Pendientes trasladados de MEJORAS.md

### Seguridad

- [x] Pruebas que conviene escribir (salieron de la revisión adversarial): matriz de autenticación
  por ruta para el túnel, paridad entre `Handler` y `PeerHandler`, el contrato de los 404
  (`unknown_session` contra ruta desconocida) y referencias (golden) por agente en los parsers.
  - **Cerrado el 2026-10-10:** Ya escritas: matriz del túnel en `tests/test_ola1_seguridad.py` (`test_por_el_tunel_sin_cookie_todo_da_401_salvo_las_rutas_publicas`), paridad `Handler`/`PeerHandler` en `tests/test_ola2_server.py`, 404 `unknown_session` en `tests/test_server.py` y golden por agente en `tests/test_ola2_agentes.py`.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 5. Gravedad: media.

### Multiplataforma

- [ ] **Evaluar una forma más óptima de sincronizar las bases de memoria entre PCs** (pedido de Ariel,
  2026-10-10). Hoy cada server le pide a cada par, cada 120 s, los cambios y capturas nacidos allá desde su
  cursor (`lienzo/replica.py`, `/peer/conocimiento`), en lotes, aunque no haya nada nuevo; los cuerpos van
  aparte. Lo que habría que medir y comparar:
  - **Empujar en vez de sondear:** que el par avise por el SSE que ya tienen abierto (`/peer/events`) cuando
    nace un cambio, y recién ahí se pida; el ciclo de 120 s queda solo como red. Menos tráfico ocioso y la
    otra PC se entera en segundos, no en hasta dos minutos.
  - **Tamaño y forma de los lotes:** comprimir el JSON (gzip) y ajustar el límite por pedido; medir cuánto
    pesa hoy un ciclo vacío y uno con capturas largas.
  - **Changesets de SQLite** (extensión session) o una base CRDT (cr-sqlite) en vez de la tabla `cambio`
    propia: ver si ahorran código y bytes o si suman una dependencia que no paga (la stdlib no trae ninguna).
  - **Qué no replicar:** si las capturas `observado` de una carpeta temporal o los textos muy largos tienen que
    viajar enteros o alcanza con el resumen y el hash.
  - Criterio: latencia entre que nace un cambio y lo ve la otra PC, bytes por hora con el tablero quieto y
    activo, y que no se rompan los cursores ni la idempotencia (las 10 pruebas de `replica.py` siguen
    pasando).

  Origen: conversación con Ariel del 2026-10-10. Gravedad: **alta, prioridad** (Ariel, 2026-10-10).

- [ ] Integración uniforme de CLI y hallazgos del code review: capacidades compartidas entre
  Python/TypeScript, proveedores de identidad/transcripción/modelo/diálogo/reanudación, Kiro V3
  limitado explícitamente a Windows y diagnóstico de metadatos sin repetir errores.
  Evidencia inicial: 190 pruebas focales pasan y build del frontend pasa (2026-10-07).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 3. Gravedad: media.

### Federación

- [x] Coordinadora sólo del repo (pedido del 2026-10-07): eliminado el rol por PC del menú,
  cliente y API. Las marcas guardadas se migran al cargar; se conserva una marca local por repo,
  prefiriendo la general existente. Seleccionar una coordinadora desmarca las del mismo repo
  en las demás PCs visibles. Las PCs desconectadas requieren reconciliarse al volver.
  Prueba focal: 134 casos pasan. Corrida agéntica `2026-10-07T06-12-22.146Z-27252`:
  cinco suites sin fallas, 981 backend y 117 UI; menú real verificado con captura.
  - **Cerrado el 2026-10-10:** Implementado y probado el 2026-10-07 (nota de arriba); la compuerta del 2026-10-10 pasa con esas pruebas.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 1. Gravedad: media.

- [ ] Cierres del plan multi-PC (`docs/plan-multi-pc-2026-09-26.md`, historial de Git) que siguen sin
  prueba real con la otra PC: la regla de firewall real de `install.py --peer` (código y `--dry-run`
  probados); ver en vivo desde A las tarjetas y la salud de B; aprobar un permiso de B desde el
  tablero de A; lanzar un frente en B desde la ★ de A y que su informe vuelva solo; una ronda real
  repartida entre dos PCs usando solo el skill, y el skill corregido contra lo medido. Hasta ahora
  todo eso se probó entre dos procesos en la misma PC.

  Origen: `docs/plan-multi-pc-2026-09-26.md`, cierres F1 a F5. Gravedad: media.

- [x] Reiniciar lienzo en la otra PC cierra las codas que corren (medido el 2026-10-03; la recarga automática por `git pull` NO las cerró: la coda de la sesión 4 siguió viva; la hipótesis de pestañas de Windows Terminal en la misma ventana del server tampoco, según la coda A cada coda abre en su propia consola, aunque lo dijo leyendo el código y no la configuración): la coda de la sesión 3 quedó
  `ended_at` en el mismo segundo del reinicio y hubo que restaurarla (`restaurar`, con contexto). Además, con la causa sin
  resolver, todo lo que sale hacia esa PC dio `401 firma invalida` de repente (sin cambios de reloj ni de claves) y solo se
  arregló reiniciando su lienzo. Ideas: que las codas no cuelguen del proceso del server, y que ante un 401 el lienzo
  intente el reinicio del peer o avise con el motivo («su server no valida mi firma»), en vez de dejar el tablero mudo.
  - **Nota del 2026-10-10:** el 401 ya llega al tablero con su motivo («la otra PC no acepta mi firma», `federation.py`, con `causa_401`). Queda la causa de que mueran las codas, que necesita la otra PC.
  - **Cerrado el 2026-10-10 (no se reprodujo):** con el código de db12f5e se lanzó una coda en ar-it33940 desde el tablero de
    la otra PC (PID 16848, contestó «OK») y se reinició ahí el server matando solo el PID de 7321 y relanzando con
    `lienzo-server.cmd`: la coda siguió viva antes, durante y después (mismo padre, PID 19636), y el tablero la volvió a
    ver. Si vuelve a pasar, reabrir con el modo en que se abrió esa coda (a mano o desde el lienzo).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 10. Gravedad: alta.

- [x] El lienzo no puede cerrar un agente colgado de otra PC: `/exit` queda en cola y `interrupt` no
  alcanza si el proceso está clavado. Hoy hubo que pedirle a otro coda un `taskkill` por PID. Idea:
  `POST /sessions/<sid>/kill` que la PC dueña ejecute sobre su propio PID (con la misma
  confirmación que las demás acciones destructivas).
  - **Cerrado el 2026-10-10:** Implementado el 2026-10-07: `POST /sessions/<sid>/kill` con confirmación, que ejecuta la PC dueña (`lienzo/kill_agent.py`).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 13. Gravedad: media.

- [x] Latencia entre PCs: un pedido mínimo a la otra PC tarda ~86 ms (mediana, p95 136 ms) contra 2,5 ms
  local; la pantalla de una tarjeta remota, ~470 ms. Cada pedido abre una conexión TCP nueva y firma
  con HMAC. Idea: conexión persistente (keep-alive) por peer y cachear `screen` unos 500 ms.
  - **Cerrado el 2026-10-10:** Conexiones HTTP reutilizables por peer desde el 2026-10-07 (cierre de implementación). Queda medir por LAN con la otra PC (ítem de Chrome remoto).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 14. Gravedad: media.

- [x] El SSE del peer se corta y reconecta cada ~15 s (`peer GET /peer/events` en el log cada 15 s).
  Funciona, porque cada reconexión trae el snapshot entero, pero es tráfico de más y una ventana en
  la que el espejo se reemplaza. Hay que ver si el server corta el stream a propósito.
  - **Cerrado el 2026-10-10:** Causa: el timeout de lectura del cliente. `SSEClient` lo cambia después de conectar (verificado el 2026-10-07).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 15. Gravedad: media.

- [x] **`launch_roots` no se ve desde la otra PC**: `peers.json` no lo trae y no hay forma de saber qué
  carpetas permite un peer sin intentar lanzar. Mostrarlo en `GET /peers`.
  - **Cerrado el 2026-10-10:** `GET /peers` trae `launch_roots` en la salud de cada PC desde el contrato de capacidades (2026-10-07; `tests/test_health.py`).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 16. Gravedad: media.

- [x] Traspasar un encargo entre PCs: copiar y pegar trabajo entre tarjetas funciona dentro de una
  PC; entre PCs no hay forma de mover un encargo a una tarjeta de la otra.
  - **Cerrado el 2026-10-10:** Implementado el 2026-10-07 (traspaso de trabajo entre PCs, cierre de implementación).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 19. Gravedad: media.

- [x] Persistir las reglas cruzadas si la otra PC reinicia: una regla vive en la PC del `from`; si
  esa PC reinicia el lienzo, hay que ver que sobreviva (hoy se guardan en `~/.lienzo`, falta probarlo
  con un reinicio real).
  - **Nota del 2026-10-10:** la regla de qué se conserva al arrancar quedó nombrada (`server.conservar_regla`) y probada releyendo `rules.json` (tests/test_pendientes_tanda3.py): la regla hacia otra PC sobrevive aunque su destino todavía no se vea. Falta el reinicio real en la otra PC.
  - **Cerrado el 2026-10-10:** reinicio real en ar-it33940: la regla `on_stop` de su coda (`e3e32f37`) hacia una sesión
    de la otra PC siguió en `GET /rules` (vive en ar-it33940, la PC del `from`) después de reiniciar su server dos veces.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 20. Gravedad: media.

- [ ] Pruebas reales pendientes (solo se probaron con transportes simulados): recuperación cuando una
  tarjeta remota ya no existe, y el reintento ante conexión rechazada.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 21. Gravedad: media.

- [x] Detectar el lienzo viejo de la otra PC por capacidades: hoy se reconoce por el texto «ruta
  desconocida» de la respuesta (`cablear` y el reenvío). Un campo de capacidades en el handshake
  (`/peer/health` o el emparejado) sería un contrato; el texto cambia sin avisar.
  - **Cerrado el 2026-10-10:** Contrato de capacidades en la salud (`protocol.CAPABILITIES`) desde el 2026-10-07; el 2026-10-10 la réplica de memoria también lo consulta (`memoria.replica`, tests/test_pendientes_tanda1.py).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 22. Gravedad: media.

- [x] **`xpc` + `purge_stale_xpc` con hilo y reloj fijo**: la purga corre en un hilo con un reloj fijo y
  una regla hacia otra PC solo guarda el flag `xpc`. Guardar `to_pc` en la regla y conciliar por peer
  al aplicar su snapshot: hoy un peer apagado frena la purga de las reglas hacia los demás.
  - **Cerrado el 2026-10-10:** Las reglas hacia otra PC guardan su PC y se concilian por peer al aplicar su snapshot (2026-10-07).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 23. Gravedad: media.

- [x] El espejo se reconcilia por rebote: una tarjeta fantasma se detecta cuando un envío vuelve con
  `unknown_session` (`mirror.forward` → `_tarjeta_fantasma`). Debería reconciliarse con un snapshot
  periódico o una secuencia en el SSE, no esperar a que alguien escriba.
  - **Cerrado el 2026-10-10:** Snapshots periódicos con protección ante eventos nuevos (2026-10-07).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 24. Gravedad: media.

- [x] **El enrutado owner→forward está repetido en ~10 handlers de `lienzo/server.py`** (`_route_session`
  + `mirror.MIRROR.forward` en cada ruta de `/sessions/<id>/...`): una sola función `route_or_local`.
  - **Cerrado el 2026-10-10:** `atender_accion` y `ACCIONES_SESION` centralizan las acciones de los dos listeners (verificado el 2026-10-07).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 25. Gravedad: media.

- [x] **`restorables_all` y `cablear` consultan en serie**: una PC lenta o caída suma su timeout al de las
  demás. Paralelizar las consultas por peer.
  - **Cerrado el 2026-10-10:** `restorables_con_fallas` usa `fan_out` paralelo (2026-10-07) y `cablear` crea las reglas en paralelo desde el 2026-10-10 (tests/test_pendientes_tanda1.py).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 26. Gravedad: media.

- [x] Timeout de acciones lentas por sufijo de ruta (`SLOW_ACTIONS`, `RESTORE_ACTION` y
  `_timeout_para` en `lienzo/federation.py`): una ruta nueva lenta se olvida y cae en los 5 s.
  Pasar el timeout como parámetro de `forward`.
  - **Cerrado el 2026-10-10:** `forward` recibe el timeout explícito (2026-10-07).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 27. Gravedad: media.

### UI

- [x] La tarjeta se queda en «Te necesita» con un permiso que ya no existe (medido el 2026-10-02): la tarjeta del Claude del gestor
  mostró durante unas 16 horas «Pide permiso» con el comando de un ruff de un subagente, desde un aviso (Notification) de las 05:06,
  aunque en su terminal no había ningún cartel. Ese permiso lo había aprobado yo hacía horas y la marca no se limpió. Confunde a
  quien mira el tablero y a la coordinadora, que gasta consultas en revisar. Los permisos de los subagentes (forks) de Claude Code
  salen en la terminal del Claude principal y el tablero no los distingue. Idea: cuando el estado dice permiso en la terminal
  y la pantalla ya no muestra el cartel («Do you want to proceed?» o «Enter confirm»), limpiar `needs` y volver al estado real.
  - **Cerrado el 2026-10-10:** Se limpia cuando la pantalla ya no muestra el cartel y nunca ante un fallo de lectura (`tests/test_mejoras.py::test_old_terminal_permission_requires_visible_prompt`).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 6. Gravedad: media.

### Conocimiento por proyecto

- [ ] Replicar la base de conocimiento entre PCs con un protocolo explícito de propiedad,
  concurrencia y recuperación. El código de las etapas 1 a 5 de v5 §9 usa la base local de la
  PC que registra los encargos; un pull de Git no transfiere esa base. Se conservan todas las
  revisiones de informes y los duplicados se sugieren sin fusionarlos automáticamente.

  Origen: v5 §9. Gravedad: media.

  Nota del 2026-10-09: diseño en `docs/propuesta-memoria-2026-10-08/anexo-c-replica.md` e
  implementación en `lienzo/replica.py` (cada PC trae de sus pares los cambios nacidos allá, por
  `/peer/conocimiento`, con cursores transaccionales; choques y duplicados para la coordinadora).
  10 pruebas con dos bases simuladas en un proceso. Falta probarlo entre las dos PCs reales.
  - **Nota del 2026-10-10:** primera réplica real: con las dos PCs en db12f5e, esta PC trajo de ar-it33940
    «replica con dee050ccab4f: 9 aplicados» (12:00:21, en `lienzo.log`). Falta ver el sentido inverso en el log de
    ar-it33940 y un choque real.

- [x] **Decidir qué PC es dueña de la base de cada proyecto mientras no haya base compartida.**
  Propuesta, sin decidir (pedido de la ronda 3):
  - Opción A, ninguna dueña (lo que hace hoy la réplica del anexo C): cada PC escribe en su base y
    trae lo de las demás; los choques quedan para la coordinadora. Lo bueno: no depende de que una
    PC esté prendida. Lo malo: puede haber choques y duplicados para revisar.
  - Opción B, dueña la PC de la carpeta (la del remote más viejo): las demás le reenvían las
    escrituras. Sin choques, pero si esa PC está apagada, las otras no escriben.
  - Opción C, dueña la PC donde corre la coordinadora de la ronda: lo natural mientras dura una
    ronda, pero cambia de ronda a ronda y un frente de otra PC escribe por la red.
  - Recomendación: A, que ya está implementada. B o C sólo si en uso real los choques resultan
    frecuentes. Las capturas no chocan (son inmutables); los choques posibles son veredictos dados
    a la vez en dos PCs.
  - **Decidido por Ariel el 2026-10-10: opción A, ninguna dueña.** Revisar sólo si los choques
    resultan frecuentes en uso real.
  - **Cerrado el 2026-10-10:** Decidido (opción A).

- [x] **Decidir la retención de las revisiones de informes y de las capturas.**
  Medido el 2026-10-10: un día cargado (1525 capturas, 990 KB de texto) suma 2,0 MB a la base;
  las revisiones de informes son unos 10 KB cada una. Propuesta, sin decidir:
  - Opción A, todo para siempre: del orden de 0,3 a 0,7 GB por año por PC en el peor caso.
  - Opción B, revisiones para siempre y capturas por 180 días, con un respaldo
    (`POST /conocimiento/<p>/respaldo`) antes de borrar: el conocimiento declarado no se pierde y
    la prosa vieja queda en el respaldo.
  - Opción C, recortar el texto de las capturas viejas a su primera línea y conservar hash y fecha.
  - Recomendación: A por ahora (el volumen es chico) y medir otra vez a los tres meses; si pasa
    de 1 GB, B. Las revisiones de informes conviene conservarlas siempre: son la procedencia de
    lo declarado.
  - **Decidido por Ariel el 2026-10-10: opción A, todo se conserva por ahora.** Queda volver a medir
    el tamaño de las bases hacia enero de 2027.
  - **Cerrado el 2026-10-10:** Decidido (opción A); volver a medir hacia enero de 2027, como dice la nota.

### Otros

- [ ] **Evaluador de performance por harness** (pedido de Ariel, 2026-10-10). Por agente (claude, codex,
  pi, coda) y modelo, el resultado contra el gasto (tokens y dólares) y el tiempo, acumulado entre rondas,
  con señales objetivas (aceptado/refutado en las consultas, veredictos de la coordinadora y pruebas en
  los encargos) antes que la opinión de otro modelo. Spec con el método SDD en
  `docs/specs/evaluador-harness/`, código en el worktree `D:/Apps/lienzo-evaluador` (rama
  `evaluador-harness`). Primer caso real: la consulta `c-20261010-a841ea` de Teorema (sólo lectura).

- [x] Identidad de Codex en el barrido (hallazgo del cierre, 2026-10-07): `codex.exe` de
  sandbox/helpers podía ocupar una tarjeta con transcripción de una CLI ya cerrada. Se filtran
  subcomandos no interactivos y flags internos `--codex-run-as-*`, y la comprobación de vida
  también lee el comando. Si no se puede leer, no se supone una TUI. Focal: 51 pruebas pasan;
  no se mataron helpers ni procesos de aplicaciones. El PID 26924 ya no existía al verificar.
  Corrida backend posterior `2026-10-07T06-16-42.580Z-16520`: 993 pruebas pasan.
  Revisión y cinco roles en resultados; baseline sin aprobar, compuerta exit 2. Estas notas
  documentales se agregan después de medir; el código probado no cambia.
  - **Cerrado el 2026-10-10:** Implementado con pruebas focales el 2026-10-07; la batería del 2026-10-10 (1313 pruebas) las incluye.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 2. Gravedad: media.

- [x] Validación con `pruebas-agenticas`: obligatoria por la preferencia global de Ariel.
  Reutilizar la configuración del repo; registrar los cinco roles, logs y veredicto sin fijar baseline.
  - **Cerrado el 2026-10-10:** Compuerta PASS el 2026-10-10 sobre daf92bb: 7 de 7 casos y 5 de 6 mutantes muertos, con requisitos y casos aprobados.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 4. Gravedad: media.

- [x] **Coda: `stop_reason` del Stop sin mirar** (medido el 2026-10-02): el `Stop` trae `stop_reason` y el doc solo muestra
  `turn_complete`; ver qué otros valores existen (respuesta cortada que continúa, error) y usarlos en vez de adivinar.
  - **Cerrado el 2026-10-10:** Implementado el 2026-10-07 (lectura de `stop_reason` de CODA).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 7. Gravedad: media.

- [ ] **Probar `PreCompact`/`PostCompact` con una coda real**: solo hay prueba con eventos simulados, y falta correr
  `install.py` en las dos PCs para que coda los mande (toca `~/.coda/config.json`).
  - **Nota del 2026-10-10:** en esta PC los hooks ya estaban y con una coda real (CODA 1.4.0) el PreCompact llegó. El
    PostCompact no se vio: con cinco vueltas cortas coda contesta «Too few messages for compaction» y aborta sin mandarlo (ni
    Stop), lo que dejaba la tarjeta trabada; arreglado (`sessions.coda_compactacion_abortada`). Falta una compactación que
    sí ocurra (conversación larga) y la otra PC.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 8. Gravedad: media.

- [x] **`--coda-home DIR` aísla la configuración de coda** (está en `coda --help`): sirve para lanzar con `--model` sin pisar el
  modelo por defecto de la PC (ver el punto de `--model`). Falta ver cómo conserva el login.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 9. Gravedad: media.
  - **Cerrado el 2026-10-10:** probado con `coda --globant --coda-home C:\Users\ArielLevy\.coda-prueba-home`. Una carpeta
    nueva arranca en el alta (log: «the coda home is not set up (missing .secrets and/or empty global config)»); con
    `--globant` se elige el entorno (Clients) y se pega la clave una vez, que queda en `<carpeta>/.secrets`, y hay que
    reiniciar coda para que cargue el proveedor (antes da 401). Después contestó por el DGX. Cambiar el modelo ahí
    escribió el `config.json` de esa carpeta (`globant_dgx/Qwen3.8-27B`) y el de `~/.coda` siguió en
    `globant_dgx/GLM-5.3-Flash`: aísla el default. Sin `--globant` el alta no ofrece Globant. Que `launch.py` lo use solo
    queda como mejora, sin pedido.

- [ ] **La herramienta `read` de coda se traba** (medido el 2026-10-02): se evita (el adjunto a un coda se lee con
  el shell y los mensajes cortos se tipean directo), pero la causa sigue en coda: avisar a quien lo mantiene.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 11. Gravedad: media.

- [x] **`--model` en coda cambia el modelo por defecto de la PC** (medido el 2026-10-02): `coda --model X` se
  documenta como «para esta corrida», pero el `config.json` de esa PC pasó de `globant_dgx/Qwen3.8-27B` a
  `globant_dgx/GLM-5.3-Flash` a las 00:52:18, justo al lanzar el primer coda con GLM, y las sesiones
  lanzadas después sin modelo ya mostraban GLM. Efectos: se pisa el default del usuario sin que lo sepa
  y las comparaciones entre modelos no valen (la medición «Qwen contra GLM» de esa noche fue GLM contra
  GLM). Ideas: que `lanzar` con `model` avise si el agente es coda, que el lienzo lea el default antes
  y lo restaure al terminar el lote, o lanzar con un `--coda-home` propio para aislar la configuración
  (hay que ver cómo conserva el login).
  - **Cerrado el 2026-10-10:** Desde el 2026-10-10 lanzar una coda con `model` devuelve un `aviso` (tests/test_pendientes_tanda2.py). Aislar con `--coda-home` sigue en su ítem.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 12. Gravedad: alta.

- [x] (Revisar: desactualizado) «Coda no tiene hooks»: el 2026-10-02 las codas figuran `hooked=True`; antes nacía como tarjeta de barrido (`pid-NNNN`, sin título ni
  transcripción), cambia de id, y su estado no refleja que está trabajando. Un hook de coda daría
  título, estado y `last_reply` confiables.
  - **Cerrado el 2026-10-10:** Desactualizado: las codas figuran `hooked=True` desde el 2026-10-02.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 17. Gravedad: media.

- [x] Un solo modelo para todos los codas: Qwen en el DGX atiende de a poco; con 5 codas a la vez
  todos quedan en «Waiting for model». El coordinador tiene que escalonar el trabajo, no repartirlo
  en paralelo sin límite. `capacidad` mide RAM, no el cupo del modelo.
  - **Cerrado el 2026-10-10:** `coordinar.capacidad(pc, n, agent="coda")` cuenta las codas que ya corren en esa PC y deja entrar a lo sumo dos (`CODAS_EN_PARALELO`); lo demás se escalona (`tests/test_coordinar.py`, skill actualizado).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 18. Gravedad: media.

### Notas de implementación y aceptación trasladadas

#### Cierre de implementación del 2026-10-07

Las casillas se conservan pendientes de aceptación. Implementado en esta ronda:
limpieza de permisos con prompt visible (sin limpiar ante fallo de lectura), lectura
de `stop_reason` de CODA, contrato de capacidades y `launch_roots`, snapshots periódicos
con protección ante eventos nuevos, conciliación de reglas por PC, conexiones HTTP
reutilizables, timeout explícito, traspaso de trabajo entre PCs y cierre forzado Windows
con confirmación e identificación del proceso. `POST /run` exige un comando nombrado
en `run_allowlist` de la PC destino y una carpeta dentro de sus `launch_roots`; no se
habilitó ninguna lista ni se ejecutaron comandos remotos reales.

Validación final y revisión: evidencia en `pruebas-agenticas/resultados/` (ignorada por
Git), corrida `2026-10-07T06-02-08.125Z-26940`: cinco suites con código 0; 981 pruebas
backend y 117 UI pasan, además de lint, build y unitarias frontend. Cinco roles registrados
secuencialmente en `roles.json`; revisión en `revision-cierre.json`. Falta baseline aprobado:
el runner sale con 1 y la compuerta con 2; no se certifica PASS ni se aprueban propuestas.
Sin mutaciones ejecutadas. Esta nota documental se agrega después de la medición.

Siguen pendientes las verificaciones con CODA real y dos PCs, aislamiento de login/modelo
con `--coda-home`, capacidad del servidor de modelos, instalación NUC desatendida y
paralelización del cableado. La integración visual de specs/SDD de Kiro no está implementada.
La documentación de Kiro V3 confirma que ofrece un agente Spec nativo; eso no acredita
su integración en Lienzo. El canal cifrado de secretos ya estaba implementado, como
consta en «Hecho»; se quitó la propuesta duplicada.

Checklist conservado por pedido de Ariel (2026-10-07). Las casillas quedan pendientes de
su aceptación; las notas distinguen implementación, pruebas y verificaciones externas.

Verificaciones del 2026-10-07: `restorables_con_fallas` ya usa `fan_out` paralelo;
`atender_accion` y `ACCIONES_SESION` ya centralizan las acciones de ambos listeners;
`SSEClient` ya cambia el timeout de lectura después de conectar; CODA ya registra
`PreCompact` y `PostCompact` en `install.py`. No equivalen a pruebas reales en ambas PCs.
La PC `ar-it33940` figura desconectada en `/peers`; no se puede verificar allí en vivo.

## Pendientes del triage de docs

### Seguridad

- [x] Restringir los datos de GET /health antes de autenticar, también por túnel.
  - Evidencia: lienzo/server.py: Handler.do_GET, rama health anterior a _authed; devuelve sessions, pending y ts.
  - Origen: `docs/pentest-2026-09-07.md, B1` (historial de Git). Gravedad: **media**.
  - **Cerrado el 2026-10-10:** Sin autenticar (o por el túnel) `/health` sólo dice `ok` y `ts` (`salud_publica`, tests/test_pendientes_tanda1.py; verificado en vivo con `CF-Connecting-IP`).

- [x] Definir controles de sesión web y una vista para listar y revocar sesiones activas.
  - Evidencia: lienzo/auth.py: check sólo comprueba token y vencimiento; login guarda ip/ua y SESSION_DAYS vale 7. logout no ofrece administración de otras sesiones.
  - Origen: `docs/pentest-2026-09-07.md, B4` (historial de Git). Gravedad: **media**.
  - **Cerrado el 2026-10-10:** `GET /auth/sessions` y `POST /auth/sessions/<id>/revoke`, con la lista y el botón Cerrar en el diálogo de Authenticator (tests/test_pendientes_tanda2.py).

- [x] Agregar cuota de adjuntos por sesión.
  - Evidencia: lienzo/server.py: MAX_ATTACH limita cada pedido; lienzo/sessions.py: limpieza por ATTACH_MAX_DAYS, sin cuota acumulada por sesión.
  - Origen: `docs/pentest-2026-09-07.md, B5` (historial de Git). Gravedad: **media**.
  - **Cerrado el 2026-10-10:** 200 MB por sesión en `/attach`, 413 al pasarse (tests/test_pendientes_tanda2.py).

- [x] Acotar hilos y conexiones SSE simultáneas.
  - Evidencia: lienzo/server.py: QuietServer hereda ThreadingHTTPServer; el servicio SSE no tiene cupo global. El cupo MAX_SESSIONS de Chrome no cubre SSE.
  - Origen: `docs/pentest-2026-09-07.md, B6` (historial de Git). Gravedad: **alta**.
  - **Cerrado el 2026-10-10:** Tope de 64 streams (`MAX_SSE`), 503 con `Retry-After` al pasarse (tests/test_pendientes_tanda2.py).

- [x] Validar request_id antes de construir la ruta de respuesta a permisos.
  - Evidencia: lienzo/sessions.py: answer_pending usa os.path.join(ANSWERS, f"{request_id}.json") tras buscar el pendiente, sin validar el identificador cargado desde disco.
  - Origen: `docs/pentest-2026-09-07.md, I2` (historial de Git). Gravedad: **baja**.
  - **Cerrado el 2026-10-10:** `answer_pending` rechaza con 400 lo que no sea `[A-Za-z0-9_-]{1,100}` (tests/test_pendientes_tanda1.py; verificado en vivo).

### Multiplataforma

- [x] Resolver PID y destino del hook en Unix.
  - Evidencia: lienzo/hook.py: find_agent_pid usa procinfo.proc_info; lienzo/procinfo.py devuelve valores vacíos fuera de Windows. Sin TMUX_PANE en lienzo/*.py; el destino se obtiene por barrido.
  - Origen: `docs/plan-multiplataforma-2026-09-08.md` (historial de Git). Gravedad: **media**.
  - **Cerrado el 2026-10-10:** fuera de Windows `procinfo.proc_info` lee `/proc` (o `ps` en macOS) y el hook manda `TMUX_PANE`, que pasa a ser el `target` de la tarjeta de tmux (tests/test_pendientes_tanda3.py). Sin corrida en un Linux real, que sigue en «Verificar el servidor nativo».

- [x] Hacer portable --remote y el arranque de cloudflared.
  - Evidencia: lienzo/server.py: CLOUDFLARED apunta a Program Files (x86)/cloudflared/cloudflared.exe; tunnel_loop pasa creationflags=0x08000000 sin condición POSIX.
  - Origen: `docs/plan-multiplataforma-2026-09-08.md` (historial de Git). Gravedad: **alta**.
  - **Cerrado el 2026-10-10:** `cloudflared` del PATH y `creationflags` sólo en Windows. Probado en Windows; Linux y macOS siguen en «Verificar el servidor nativo».

- [x] Traducir rutas de adjuntos de Windows para los agentes de WSL.
  - Evidencia: lienzo/sessions.py: compose_send y run_send pasan rutas locales; no hay conversión con wslpath en lienzo/*.py.
  - Origen: `docs/plan-multiplataforma-2026-09-08.md` (historial de Git). Gravedad: **media**.
  - **Cerrado el 2026-10-10:** `tmux.ruta_wsl` traduce lo que se tipea a un agente de WSL (`/mnt/c/...`) (tests/test_pendientes_tanda2.py).

- [x] Informar backend y fuentes activas en /health.
  - Evidencia: lienzo/server.py: Handler.do_GET, rama health, sólo devuelve ok, sessions, pending y ts; lienzo/backend.py distingue fuentes.
  - Origen: `docs/plan-multiplataforma-2026-09-08.md` (historial de Git). Gravedad: **baja**.
  - **Cerrado el 2026-10-10:** `/health` autenticado o local trae `fuentes` (`win32`, `tmux`) (tests/test_pendientes_tanda1.py).

- [ ] Descubrir y direccionar varias distros de WSL.
  - Evidencia: lienzo/tmux.py: _PREFIX = ["wsl.exe"] en Windows, sin selección de distro; backend.proc_key distingue fuente y PID, no distro.
  - Origen: `docs/porting-linux-2026-09-08.md` (historial de Git). Gravedad: **baja**.

- [ ] Verificar el servidor nativo en Linux y macOS, incluido emparejamiento.
  - Evidencia: lienzo/backend.py: sweep; lienzo/tmux.py: _ps_all. El documento de origen registra simulación de plataforma y pruebas desde Windows/WSL, no una corrida nativa completa; esta revisión no ejecutó esas plataformas.
  - Origen: `docs/porting-linux-2026-09-08.md, Integrado a main; README.md, Limitaciones` (historial de Git). Gravedad: **media**.

### Chrome remoto

- [ ] Verificar en vivo la aprobación de conexión del Chrome habitual de Globant.
  - Evidencia: lienzo/browser_consent.ps1 y lienzo/browser_host.mjs: approveChrome implementan el pedido; docs/code-review-2026-10-07.md deja expresamente pendiente la prueba de ese perfil.
  - Origen: `docs/code-review-2026-10-07.md` (historial de Git). Gravedad: **media**.

- [ ] Sincronizar el portapapeles en modo ventana.
  - Evidencia: lienzo/browser_window.py no implementa clipboard. web/src/components/RemoteBrowser.tsx: onPaste manda texto local, pero eso no sincroniza el portapapeles remoto; el copy por CDP es otro modo.
  - Origen: `docs/code-review-2026-10-07.md` (historial de Git). Gravedad: **media**.

- [ ] Evaluar transporte no ordenado para movimientos mediante WebRTC/UDP, sólo como idea pendiente de decisión.
  - Evidencia: lienzo/browser_stream.py y lienzo/ws.py usan WebSocket ordenado; no hay transporte WebRTC/UDP para la entrada.
  - Origen: `docs/code-review-2026-10-07.md, Canal vivo` (historial de Git). Gravedad: **baja**.

- [ ] Medir latencia sostenida por LAN después del canal WebSocket.
  - Evidencia: lienzo/browser_stream.py: serve_viewer; docs/code-review-2026-10-07.md registra cuadros locales y la caída de ar-it33940 antes de medir el canal nuevo por LAN. No hay medición nueva en este encargo.
  - Origen: `docs/code-review-2026-10-07.md, Detective del canal vivo` (historial de Git). Gravedad: **media**.

### Federación

- [x] Incluir conexiones del espejo en GET /links.
  - Evidencia: lienzo/server.py: Handler.do_GET devuelve links.snapshot(); GET /rules sí agrega mirror.MIRROR.rules().
  - Origen: `docs/ronda2/` (historial de Git). Gravedad: **baja**.
  - **Cerrado el 2026-10-10:** `GET /links` suma `mirror.MIRROR.links()` (tests/test_pendientes_tanda1.py).

- [x] Unificar LIENZO_PEER_PORT entre pairing y el listener real.
  - Evidencia: lienzo/pairing.py lee LIENZO_PEER_PORT; lienzo/server.py no consulta esa variable para sus listeners.
  - Origen: `docs/ronda3/` (historial de Git). Gravedad: **baja**.
  - **Cerrado el 2026-10-10:** `--peer-port` toma por defecto `pairing._my_port()` (tests/test_pendientes_tanda1.py).

### UI

- [ ] Verificar un lanzamiento real en otra PC desde el selector de proyecto/PC del tablero; la UI está implementada y sus recorridos con fixtures pasan.
  - Evidencia: lienzo/server.py: accion_launch implementa POST /sessions/launch; la búsqueda de sessions/launch en web/src no tiene coincidencias.
  - Origen: `docs/ronda3/` (historial de Git). Gravedad: **media**.

## Alcance de la consolidación

Se trasladaron 27 casillas previas y 18 pendientes del cuerpo del triage. Su resumen decía
16: omitía la verificación nativa de Linux/macOS y la inconsistencia de LIENZO_PEER_PORT.
No se cerró ninguna casilla ni se aprobó un baseline. Las secciones «Plan» e «Ideas» de
MEJORAS.md quedan fuera de la edición autorizada de ese archivo; sus puntos se conservan allí.
