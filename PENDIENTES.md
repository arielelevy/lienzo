# Pendientes del lienzo

Esta es la única lista de pendientes; lo hecho está en MEJORAS.md y en DISENO.es.md.

Fecha: 2026-10-09.

Las casillas heredadas se conservan textuales y pendientes de aceptación, incluso cuando
su nota posterior documenta una implementación. La evidencia histórica no es una prueba
ejecutada hoy. Las referencias de código de esta consolidación se revisaron estáticamente.

## Pendientes trasladados de MEJORAS.md

### Seguridad

- [ ] Pruebas que conviene escribir (salieron de la revisión adversarial): matriz de autenticación
  por ruta para el túnel, paridad entre `Handler` y `PeerHandler`, el contrato de los 404
  (`unknown_session` contra ruta desconocida) y referencias (golden) por agente en los parsers.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 5. Gravedad: media.

### Multiplataforma

- [ ] Integración uniforme de CLI y hallazgos del code review: capacidades compartidas entre
  Python/TypeScript, proveedores de identidad/transcripción/modelo/diálogo/reanudación, Kiro V3
  limitado explícitamente a Windows y diagnóstico de metadatos sin repetir errores.
  Evidencia inicial: 190 pruebas focales pasan y build del frontend pasa (2026-10-07).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 3. Gravedad: media.

### Federación

- [ ] Coordinadora sólo del repo (pedido del 2026-10-07): eliminado el rol por PC del menú,
  cliente y API. Las marcas guardadas se migran al cargar; se conserva una marca local por repo,
  prefiriendo la general existente. Seleccionar una coordinadora desmarca las del mismo repo
  en las demás PCs visibles. Las PCs desconectadas requieren reconciliarse al volver.
  Prueba focal: 134 casos pasan. Corrida agéntica `2026-10-07T06-12-22.146Z-27252`:
  cinco suites sin fallas, 981 backend y 117 UI; menú real verificado con captura.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 1. Gravedad: media.

- [ ] Cierres del plan multi-PC (`docs/plan-multi-pc-2026-09-26.md`, historial de Git) que siguen sin
  prueba real con la otra PC: la regla de firewall real de `install.py --peer` (código y `--dry-run`
  probados); ver en vivo desde A las tarjetas y la salud de B; aprobar un permiso de B desde el
  tablero de A; lanzar un frente en B desde la ★ de A y que su informe vuelva solo; una ronda real
  repartida entre dos PCs usando solo el skill, y el skill corregido contra lo medido. Hasta ahora
  todo eso se probó entre dos procesos en la misma PC.

  Origen: `docs/plan-multi-pc-2026-09-26.md`, cierres F1 a F5. Gravedad: media.

- [ ] Reiniciar lienzo en la otra PC cierra las codas que corren (medido el 2026-10-03; la recarga automática por `git pull` NO las cerró: la coda de la sesión 4 siguió viva; la hipótesis de pestañas de Windows Terminal en la misma ventana del server tampoco, según la coda A cada coda abre en su propia consola, aunque lo dijo leyendo el código y no la configuración): la coda de la sesión 3 quedó
  `ended_at` en el mismo segundo del reinicio y hubo que restaurarla (`restaurar`, con contexto). Además, con la causa sin
  resolver, todo lo que sale hacia esa PC dio `401 firma invalida` de repente (sin cambios de reloj ni de claves) y solo se
  arregló reiniciando su lienzo. Ideas: que las codas no cuelguen del proceso del server, y que ante un 401 el lienzo
  intente el reinicio del peer o avise con el motivo («su server no valida mi firma»), en vez de dejar el tablero mudo.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 10. Gravedad: alta.

- [ ] El lienzo no puede cerrar un agente colgado de otra PC: `/exit` queda en cola y `interrupt` no
  alcanza si el proceso está clavado. Hoy hubo que pedirle a otro coda un `taskkill` por PID. Idea:
  `POST /sessions/<sid>/kill` que la PC dueña ejecute sobre su propio PID (con la misma
  confirmación que las demás acciones destructivas).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 13. Gravedad: media.

- [ ] Latencia entre PCs: un pedido mínimo a la otra PC tarda ~86 ms (mediana, p95 136 ms) contra 2,5 ms
  local; la pantalla de una tarjeta remota, ~470 ms. Cada pedido abre una conexión TCP nueva y firma
  con HMAC. Idea: conexión persistente (keep-alive) por peer y cachear `screen` unos 500 ms.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 14. Gravedad: media.

- [ ] El SSE del peer se corta y reconecta cada ~15 s (`peer GET /peer/events` en el log cada 15 s).
  Funciona, porque cada reconexión trae el snapshot entero, pero es tráfico de más y una ventana en
  la que el espejo se reemplaza. Hay que ver si el server corta el stream a propósito.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 15. Gravedad: media.

- [ ] **`launch_roots` no se ve desde la otra PC**: `peers.json` no lo trae y no hay forma de saber qué
  carpetas permite un peer sin intentar lanzar. Mostrarlo en `GET /peers`.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 16. Gravedad: media.

- [ ] Traspasar un encargo entre PCs: copiar y pegar trabajo entre tarjetas funciona dentro de una
  PC; entre PCs no hay forma de mover un encargo a una tarjeta de la otra.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 19. Gravedad: media.

- [ ] Persistir las reglas cruzadas si la otra PC reinicia: una regla vive en la PC del `from`; si
  esa PC reinicia el lienzo, hay que ver que sobreviva (hoy se guardan en `~/.lienzo`, falta probarlo
  con un reinicio real).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 20. Gravedad: media.

- [ ] Pruebas reales pendientes (solo se probaron con transportes simulados): recuperación cuando una
  tarjeta remota ya no existe, y el reintento ante conexión rechazada.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 21. Gravedad: media.

- [ ] Detectar el lienzo viejo de la otra PC por capacidades: hoy se reconoce por el texto «ruta
  desconocida» de la respuesta (`cablear` y el reenvío). Un campo de capacidades en el handshake
  (`/peer/health` o el emparejado) sería un contrato; el texto cambia sin avisar.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 22. Gravedad: media.

- [ ] **`xpc` + `purge_stale_xpc` con hilo y reloj fijo**: la purga corre en un hilo con un reloj fijo y
  una regla hacia otra PC solo guarda el flag `xpc`. Guardar `to_pc` en la regla y conciliar por peer
  al aplicar su snapshot: hoy un peer apagado frena la purga de las reglas hacia los demás.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 23. Gravedad: media.

- [ ] El espejo se reconcilia por rebote: una tarjeta fantasma se detecta cuando un envío vuelve con
  `unknown_session` (`mirror.forward` → `_tarjeta_fantasma`). Debería reconciliarse con un snapshot
  periódico o una secuencia en el SSE, no esperar a que alguien escriba.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 24. Gravedad: media.

- [ ] **El enrutado owner→forward está repetido en ~10 handlers de `lienzo/server.py`** (`_route_session`
  + `mirror.MIRROR.forward` en cada ruta de `/sessions/<id>/...`): una sola función `route_or_local`.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 25. Gravedad: media.

- [ ] **`restorables_all` y `cablear` consultan en serie**: una PC lenta o caída suma su timeout al de las
  demás. Paralelizar las consultas por peer.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 26. Gravedad: media.

- [ ] Timeout de acciones lentas por sufijo de ruta (`SLOW_ACTIONS`, `RESTORE_ACTION` y
  `_timeout_para` en `lienzo/federation.py`): una ruta nueva lenta se olvida y cae en los 5 s.
  Pasar el timeout como parámetro de `forward`.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 27. Gravedad: media.

### UI

- [ ] La tarjeta se queda en «Te necesita» con un permiso que ya no existe (medido el 2026-10-02): la tarjeta del Claude del gestor
  mostró durante unas 16 horas «Pide permiso» con el comando de un ruff de un subagente, desde un aviso (Notification) de las 05:06,
  aunque en su terminal no había ningún cartel. Ese permiso lo había aprobado yo hacía horas y la marca no se limpió. Confunde a
  quien mira el tablero y a la coordinadora, que gasta consultas en revisar. Los permisos de los subagentes (forks) de Claude Code
  salen en la terminal del Claude principal y el tablero no los distingue. Idea: cuando el estado dice permiso en la terminal
  y la pantalla ya no muestra el cartel («Do you want to proceed?» o «Enter confirm»), limpiar `needs` y volver al estado real.

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

- [ ] **Decidir qué PC es dueña de la base de cada proyecto mientras no haya base compartida.**
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

- [ ] **Decidir la retención de las revisiones de informes y de las capturas.**
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

### Otros

- [ ] Identidad de Codex en el barrido (hallazgo del cierre, 2026-10-07): `codex.exe` de
  sandbox/helpers podía ocupar una tarjeta con transcripción de una CLI ya cerrada. Se filtran
  subcomandos no interactivos y flags internos `--codex-run-as-*`, y la comprobación de vida
  también lee el comando. Si no se puede leer, no se supone una TUI. Focal: 51 pruebas pasan;
  no se mataron helpers ni procesos de aplicaciones. El PID 26924 ya no existía al verificar.
  Corrida backend posterior `2026-10-07T06-16-42.580Z-16520`: 993 pruebas pasan.
  Revisión y cinco roles en resultados; baseline sin aprobar, compuerta exit 2. Estas notas
  documentales se agregan después de medir; el código probado no cambia.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 2. Gravedad: media.

- [ ] Validación con `pruebas-agenticas`: obligatoria por la preferencia global de Ariel.
  Reutilizar la configuración del repo; registrar los cinco roles, logs y veredicto sin fijar baseline.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 4. Gravedad: media.

- [ ] **Coda: `stop_reason` del Stop sin mirar** (medido el 2026-10-02): el `Stop` trae `stop_reason` y el doc solo muestra
  `turn_complete`; ver qué otros valores existen (respuesta cortada que continúa, error) y usarlos en vez de adivinar.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 7. Gravedad: media.

- [ ] **Probar `PreCompact`/`PostCompact` con una coda real**: solo hay prueba con eventos simulados, y falta correr
  `install.py` en las dos PCs para que coda los mande (toca `~/.coda/config.json`).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 8. Gravedad: media.

- [ ] **`--coda-home DIR` aísla la configuración de coda** (está en `coda --help`): sirve para lanzar con `--model` sin pisar el
  modelo por defecto de la PC (ver el punto de `--model`). Falta ver cómo conserva el login.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 9. Gravedad: media.

- [ ] **La herramienta `read` de coda se traba** (medido el 2026-10-02): se evita (el adjunto a un coda se lee con
  el shell y los mensajes cortos se tipean directo), pero la causa sigue en coda: avisar a quien lo mantiene.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 11. Gravedad: media.

- [ ] **`--model` en coda cambia el modelo por defecto de la PC** (medido el 2026-10-02): `coda --model X` se
  documenta como «para esta corrida», pero el `config.json` de esa PC pasó de `globant_dgx/Qwen3.8-27B` a
  `globant_dgx/GLM-5.3-Flash` a las 00:52:18, justo al lanzar el primer coda con GLM, y las sesiones
  lanzadas después sin modelo ya mostraban GLM. Efectos: se pisa el default del usuario sin que lo sepa
  y las comparaciones entre modelos no valen (la medición «Qwen contra GLM» de esa noche fue GLM contra
  GLM). Ideas: que `lanzar` con `model` avise si el agente es coda, que el lienzo lea el default antes
  y lo restaure al terminar el lote, o lanzar con un `--coda-home` propio para aislar la configuración
  (hay que ver cómo conserva el login).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 12. Gravedad: alta.

- [ ] (Revisar: desactualizado) «Coda no tiene hooks»: el 2026-10-02 las codas figuran `hooked=True`; antes nacía como tarjeta de barrido (`pid-NNNN`, sin título ni
  transcripción), cambia de id, y su estado no refleja que está trabajando. Un hook de coda daría
  título, estado y `last_reply` confiables.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 17. Gravedad: media.

- [ ] Un solo modelo para todos los codas: Qwen en el DGX atiende de a poco; con 5 codas a la vez
  todos quedan en «Waiting for model». El coordinador tiene que escalonar el trabajo, no repartirlo
  en paralelo sin límite. `capacidad` mide RAM, no el cupo del modelo.

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

- [ ] Restringir los datos de GET /health antes de autenticar, también por túnel.
  - Evidencia: lienzo/server.py: Handler.do_GET, rama health anterior a _authed; devuelve sessions, pending y ts.
  - Origen: `docs/pentest-2026-09-07.md, B1` (historial de Git). Gravedad: **media**.

- [ ] Definir controles de sesión web y una vista para listar y revocar sesiones activas.
  - Evidencia: lienzo/auth.py: check sólo comprueba token y vencimiento; login guarda ip/ua y SESSION_DAYS vale 7. logout no ofrece administración de otras sesiones.
  - Origen: `docs/pentest-2026-09-07.md, B4` (historial de Git). Gravedad: **media**.

- [ ] Agregar cuota de adjuntos por sesión.
  - Evidencia: lienzo/server.py: MAX_ATTACH limita cada pedido; lienzo/sessions.py: limpieza por ATTACH_MAX_DAYS, sin cuota acumulada por sesión.
  - Origen: `docs/pentest-2026-09-07.md, B5` (historial de Git). Gravedad: **media**.

- [ ] Acotar hilos y conexiones SSE simultáneas.
  - Evidencia: lienzo/server.py: QuietServer hereda ThreadingHTTPServer; el servicio SSE no tiene cupo global. El cupo MAX_SESSIONS de Chrome no cubre SSE.
  - Origen: `docs/pentest-2026-09-07.md, B6` (historial de Git). Gravedad: **alta**.

- [ ] Validar request_id antes de construir la ruta de respuesta a permisos.
  - Evidencia: lienzo/sessions.py: answer_pending usa os.path.join(ANSWERS, f"{request_id}.json") tras buscar el pendiente, sin validar el identificador cargado desde disco.
  - Origen: `docs/pentest-2026-09-07.md, I2` (historial de Git). Gravedad: **baja**.

### Multiplataforma

- [ ] Resolver PID y destino del hook en Unix.
  - Evidencia: lienzo/hook.py: find_agent_pid usa procinfo.proc_info; lienzo/procinfo.py devuelve valores vacíos fuera de Windows. Sin TMUX_PANE en lienzo/*.py; el destino se obtiene por barrido.
  - Origen: `docs/plan-multiplataforma-2026-09-08.md` (historial de Git). Gravedad: **media**.

- [ ] Hacer portable --remote y el arranque de cloudflared.
  - Evidencia: lienzo/server.py: CLOUDFLARED apunta a Program Files (x86)/cloudflared/cloudflared.exe; tunnel_loop pasa creationflags=0x08000000 sin condición POSIX.
  - Origen: `docs/plan-multiplataforma-2026-09-08.md` (historial de Git). Gravedad: **alta**.

- [ ] Traducir rutas de adjuntos de Windows para los agentes de WSL.
  - Evidencia: lienzo/sessions.py: compose_send y run_send pasan rutas locales; no hay conversión con wslpath en lienzo/*.py.
  - Origen: `docs/plan-multiplataforma-2026-09-08.md` (historial de Git). Gravedad: **media**.

- [ ] Informar backend y fuentes activas en /health.
  - Evidencia: lienzo/server.py: Handler.do_GET, rama health, sólo devuelve ok, sessions, pending y ts; lienzo/backend.py distingue fuentes.
  - Origen: `docs/plan-multiplataforma-2026-09-08.md` (historial de Git). Gravedad: **baja**.

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

- [ ] Incluir conexiones del espejo en GET /links.
  - Evidencia: lienzo/server.py: Handler.do_GET devuelve links.snapshot(); GET /rules sí agrega mirror.MIRROR.rules().
  - Origen: `docs/ronda2/` (historial de Git). Gravedad: **baja**.

- [ ] Unificar LIENZO_PEER_PORT entre pairing y el listener real.
  - Evidencia: lienzo/pairing.py lee LIENZO_PEER_PORT; lienzo/server.py no consulta esa variable para sus listeners.
  - Origen: `docs/ronda3/` (historial de Git). Gravedad: **baja**.

### UI

- [ ] Verificar un lanzamiento real en otra PC desde el selector de proyecto/PC del tablero; la UI está implementada y sus recorridos con fixtures pasan.
  - Evidencia: lienzo/server.py: accion_launch implementa POST /sessions/launch; la búsqueda de sessions/launch en web/src no tiene coincidencias.
  - Origen: `docs/ronda3/` (historial de Git). Gravedad: **media**.

## Alcance de la consolidación

Se trasladaron 27 casillas previas y 18 pendientes del cuerpo del triage. Su resumen decía
16: omitía la verificación nativa de Linux/macOS y la inconsistencia de LIENZO_PEER_PORT.
No se cerró ninguna casilla ni se aprobó un baseline. Las secciones «Plan» e «Ideas» de
MEJORAS.md quedan fuera de la edición autorizada de ese archivo; sus puntos se conservan allí.
