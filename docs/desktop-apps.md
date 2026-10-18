# Lienzo con Claude Desktop y Codex desktop

Investigación del 2026-10-16, pedida por Ariel: qué hace falta para que el lienzo trabaje del todo
con las apps de escritorio de Claude y de Codex, en vez de con las terminales. El 2026-10-17 se midió
en vivo con las dos apps abiertas y se implementó el monitoreo: ver la sección siguiente, que manda
sobre lo inferido más abajo.

Cada afirmación lleva su marca:

- **[V]** verificado: en el código del repo, en un archivo de esta PC o en la documentación oficial.
- **[I]** inferido: deducido de lo anterior, sin medir. Hay que probarlo antes de construir encima.

## Cambio de continuidad en 0.4.0

El adaptador autorizado conserva las credenciales Claude en su memoria mientras vive el mismo
proceso dueño. Tras reiniciar Lienzo, vuelve a autenticar el servidor y conecta un canal nuevo;
el archivo de encuentro contiene únicamente ids públicos e identidades de procesos. No guarda
tokens ni mensajes. Un cierre explícito del enlace cancela esa recuperación y requiere conectar
de nuevo. Los mensajes cuyo resultado quedó incierto no se repiten.

Un adaptador de una versión anterior necesita conectarse una vez con el código nuevo. Si el
adaptador anterior ya murió, Lienzo no puede recuperar sus credenciales desde archivos.

La validación y los límites de esta versión están en [las notas 0.4.0](releases/0.4.0.md).
Las mediciones siguientes son antecedentes del 2026-10-17.

## Medido e implementado el 2026-10-17

### Estado del corte de integración (13:31)

Claude Desktop tiene envío directo probado desde el servidor principal: registro explícito por
sesión, adaptador hijo autenticado, un mensaje peer y un ACK exacto, ambos contados una vez.
La API publicó el mismo UUID como `entregado`, con confirmación final. Versión receptora
Claude Code 2.1.299; pruebas propias previas en 2.1.302. Evidencia de coordinación:
`.temp/coordinacion/2026-10-17/verificacion-tablero-desktop.md` y
`claude-pipe-prueba/desktop-tablero-real-result.json`.

Para conectar una sesión Desktop existente, usar su acción de conexión en Lienzo y pegar el
comando público vigente directamente en esa conversación. El bootstrap vence a los 120 s.
La conexión no exige autorizar cada mensaje. Una sesión nueva o un cierre del adaptador requiere
conectar de nuevo. Automatización del inicio y un Claude Code como puente quedan fuera de este
release. No se agregan reglas de permisos ni se desactiva auto mode.

Codex Desktop usa `codex queue`; Codex CLI escribe en su consola con el proceso fijado por PID y FILETIME.
La UI distingue aceptación, incertidumbre y entrega confirmada.
Recibir por estos canales no habilita matar/interrumpir procesos Desktop. La verificación integrada
de Claude acredita HTTP/transporte/confirmación, no un click de UI ni aceptación global de release.
La revisión de diseño y las pruebas finales del corte se registran por separado.

### Antecedente histórico del corte de las 12:44

La implementación local y el servidor principal activo todavía difieren. A entregó `codex queue`
con pruebas reales de TUI quieta/ocupada y deduplicación, más 2022 pruebas backend y 3 omitidas.
D integra la publicación de capacidad y estado, la confirmación periódica y el formulario de
envío para tarjetas sin consola. No basta con mostrar el transporte en la tarjeta.

Para Claude, se verificó un envío autenticado al named pipe de una sesión propia de prueba:
un mensaje peer válido y un ACK exacto; el marcador con token inválido no apareció. La sesión
terminó y retiró su registro. El token se tomó del entorno del hijo, sin leer archivos de claves.
Esta prueba no demuestra todavía el envío desde el servidor independiente de Lienzo ni a Desktop.
E implementa el puente con adaptador hijo y confirmación por transcript; su integración y prueba
Desktop siguen pendientes. La decisión anterior de no implementar ningún cliente de pipe queda
reemplazada por este alcance autorizado. No se usa el stdin privado del motor de Desktop.

Evidencia: `.temp/coordinacion/2026-10-17/claude-pipe-prueba/verification.json`, informes A/C/E
y `orden-release.md`. No se reinició el servidor principal ni se aprobó un baseline.

### Compatibilidad de las interfaces y límites (revisión pedida por Ariel)

- `codex queue` figura **Stable** en la [referencia oficial](https://learn.chatgpt.com/docs/developer-commands?surface=cli#codex-queue).
  Se usa el comando del harness, con UUID de hilo y argv sin shell. No se abre el app-server privado
  de la app ni se manipulan sus locks. Las pruebas reales de A acreditan CLI; la medición previa de
  la coordinadora acredita el hilo de la app. No extiende soporte a chats generales de ChatGPT.
- Claude documenta el [pipe y la autenticación del hijo](https://code.claude.com/docs/en/cross-session-messaging#the-sessions-inbox-socket).
  El formato de entrega utilizado sigue siendo interno: prueba real propia en 2.1.302, guardia
  `peerProtocol == 1` y versión mínima Windows 2.1.234. No se garantiza compatibilidad futura.
- El adaptador conserva el token Claude en memoria. El bootstrap sólo entrega la credencial del
  enlace al hijo validado por Windows; comandos y settings contienen dirección e identidad públicas.
  No se leen archivos de claves ni se comparten credenciales entre cuentas.
- Entrega y ejecución del pedido siguen las reglas de la sesión receptora. La autorización de un
  par no reemplaza el consentimiento del usuario: Desktop pidió confirmación directa y no ejecutó.
  La autorización directa posterior permitió la prueba integrada positiva de las 13:31; los rechazos
  anteriores no se eludieron ni se usaron como motivo para cambiar permisos.
- Un envío puede iniciar un turno y consumir la cuota del plan. En Codex, una cola hacia un hilo
  sin proceso puede incluso activar trabajo en segundo plano; el transporte de Lienzo lo rechaza.
  En una prueba Claude, el costo informado superó `--max-budget-usd 0.50`; ese flag no se trata como
  techo monetario estricto. No se repiten llamadas de modelo para eludir un bloqueo.

Esto es una revisión técnica de esta implementación y de las interfaces documentadas. No constituye
una garantía sobre la cuenta, condiciones de uso o versiones que no fueron probadas.

### Qué se midió

- **Claude Desktop** `Claude` 2.42304.0.0 (se actualizó sola desde 2.16120). La app Electron es
  `WindowsApps\Claude_…\app\claude.exe`, con unos diez hijos del mismo ejecutable. El motor de cada
  sesión es otro `claude.exe`, hijo de la app, en `%APPDATA%\Claude\claude-code\<ver>\<hash>\claude.exe`.
  El hook lo ve con la ruta real del paquete: `…\Packages\Claude_<id>\LocalCache\Roaming\Claude\claude-code\…`.
  Corre con `--input-format stream-json --output-format stream-json --permission-prompt-tool=stdio`:
  la app le habla por un pipe, sin consola. [V]
- Esa sesión dispara los hooks del lienzo (`SessionStart` del 2026-09-14 y la tarjeta 5d0f9e6b del
  17, `hooked: true`). Antes del cambio el lienzo la tomaba como CLI con consola: un envío habría
  intentado teclearle. [V]
- **Registro de Claude Code** `~/.claude/sessions/<pid>.json` (respeta `CLAUDE_CONFIG_DIR`). Hay uno
  por proceso vivo, de la CLI y del motor de Desktop. Trae `sessionId`, `entrypoint` (`cli` o
  `claude-desktop`), `name` (el nombre en el canal nativo), `kind`, `status` y `procStart`.
  `procStart` es la creación del proceso como FILETIME: coincidió exacto con `GetProcessTimes` del
  pid 3568. Al lado hay un `<pid>.<hash>.key` y el campo `messagingSocketPath` (un pipe): no se leen. [V]
- **Canal nativo:** `ListAgents` lista la sesión de Desktop («Claude Desktop session»), y un `SendMessage`
  desde una sesión de Claude le llega y vuelve. Lo midió la coordinadora, y este frente lo repitió:
  respondió «medición C ok» a los 20 s. [V]
- **Desktop muestra las sesiones de la CLI** porque comparte `~/.claude/projects` (observado por Ariel).
  Verlas no crea un proceso. Retomar una sesión en la app (`claude --desktop --resume`) cierra la CLI,
  y la retoma un motor de la app con el mismo `session_id` [V doc]. No se midió en vivo para no cortar
  una CLI de trabajo. [I]
- **Codex desktop** se instala con el instalador de ChatGPT, en el paquete `OpenAI.Codex` 26.1007.9446.0.
  La app es `ChatGPT.exe`; los procesos `--type=` son de Electron. Su motor es
  `%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe … app-server`, hijo de la app y por stdio, sin
  `--listen`: es privado de la app. [V]
- Los rollouts de la app traen `originator: Codex Desktop` (el hilo vivo 01a14a5d del 17) o
  `codex_work_desktop` (los del 12 al 14). Los otros 90 «Codex Desktop» de esta PC son transcripciones
  de Claude importadas, listadas en `external_agent_session_imports.json`, y no son trabajo de la app.
  `[features] hooks = false` sigue, así que de la app no llega ningún hook. [V]
- **Un solo escritor por hilo:** `~/.codex/thread-writer-locks/<hilo>.lock`, tomado por el proceso dueño.
  Ariel observó que la app no deja escribir en un hilo abierto por la CLI. [V]
- **¿Un segundo cliente sobre los hilos de la app?** Se investigó sólo leyendo: la ayuda de codex-cli
  0.163.0 y los archivos de `~/.codex`. No se conectó nada, ni a sockets ni a pipes, ni se tocaron los
  `.lock`.
  - `codex app-server daemon start|stop|…` levanta un app-server local **compartido**, con socket de
    control en `~/.codex/app-server-control/app-server-control.sock`. A ese daemon se enganchan varios
    clientes: `codex --remote`, `codex agents` («Browse all agent sessions on the shared local
    app-server daemon») y `codex app-server proxy`. Corrió del 12 al 14 (su log muestra turnos) y hoy
    no está vivo (daemon.pid 29996). [V]
  - La app no usa ese daemon: su app-server es suyo, por stdio. `\\.\pipe\codex-ipc` es de la app y
    su protocolo no está documentado. [V]
  - Ni el daemon ni el socket de control dan acceso a los hilos de la app, porque la app no los usa. [V]
- **Escribirle a un hilo de la app sí se puede, con `codex queue`.** Lo midió la coordinadora a las 12:12,
  con codex-cli 0.163.0: `codex queue --thread <id> --message <texto>` (documentado en `codex queue
  --help`) encoló un mensaje para el hilo 01a14a5d, que tenía abierto la app.
  - Salió con exit 0 y sin dejar procesos. Usa `~/.codex/queue_1.sqlite`.
  - La app lo tomó en 1 s como turno nuevo (`task_started`, el mensaje, la respuesta, `task_complete`).
  - No necesitó el daemon ni tocó el lock del hilo. [V]
  - Esto corrige la conclusión anterior de este documento: «no hay camino soportado para escribir en
    hilos de la app». La cola es el camino soportado; el app-server de la app sigue siendo privado.
  - A implementa ese transporte en el lienzo (`lienzo/codex_queue.py`), con confirmación por el rollout.
    Que también entregue a una TUI viva lo está midiendo A.

### Qué hace el lienzo ahora

- **Detección de Claude Desktop** (`lienzo/procs.py`), en orden:
  1. El registro: `entrypoint: claude-desktop`, sólo si su `procStart` es el del proceso (un pid reciclado no cuenta).
  2. La ruta del motor (`\Roaming\Claude\claude-code\`).
  3. Un padre bajo `WindowsApps\Claude_` u `OpenAI.Codex_`.

  La sesión queda `external = {kind: "claude-desktop", via, desktop: true, canal}` y `no_console`.
  Con eso no se le teclea, no se la mata, no la mueven reglas y no se reabre en una terminal. Los
  procesos Electron siguen descartados por `is_impostor`.
- La detección vale para la tarjeta que nace por hook (`claim_pid`) y para la del barrido. Además, el
  barrido reclasifica una tarjeta que ya existía, como la 5d0f9e6b, sin pisar la marca de un orquestador.
- **Sin duplicados:** si un motor de Desktop emite con el `session_id` de una CLI viva, la tarjeta
  sigue con la CLI. Cuando la CLI muere (retomada en Desktop), el motor la toma y la tarjeta pasa a
  sólo lectura. Un `claude --resume` en terminal la vuelve personal.
- **Envío a Claude Desktop:** con adaptador propio conectado se habilita `claude_pipe`. Sin enlace
  vigente se informa el motivo y no se degrada a tecleo. El formato interno y la guardia de protocolo
  se verifican por versión; ver el corte integrado de las 13:31. El canal nativo desde otra sesión
  Claude sigue siendo una alternativa, sujeta a permisos y cuota del receptor.
- **Hilos de Codex desktop** (`agentes.codex_desktop_threads`, `sessions.adopt_desktop_threads`):
  - En cada barrido se toman los rollouts escritos en las últimas 2 h, con originator de la app y que
    no sean importados. Respeta `CODEX_HOME`.
  - Cada hilo es una tarjeta sin pid, `source: desktop`, con
    `external = {kind: "codex-desktop", via: "rollout", desktop: true}`. Estado, pedido y respuesta
    salen del rollout, que la liveness relee cuando crece.
  - Se retira a las 2 h sin escritura. No pisa una tarjeta que ya tenga ese id.
  - Sus permisos no llegan (sin hooks), y la tarjeta lo dice.
- **La marca de envío de la tarjeta** sale del server, no de un texto fijo. Cada sesión trae
  `envio: {puede, motivo, transporte}`, el resultado de `puede_enviar` del contrato de D, acordado con A.
  - Con `puede`: «· se le escribe por codex queue» (o el transporte que venga).
  - Sin `puede`: «· solo lectura», con el motivo en el tooltip.
  - Si el server todavía no lo manda: en Codex desktop, «envío sin informar»; en Claude Desktop, la
    indicación del canal nativo.
  - Falta cablear `envio` en `GET /sessions` (`server.py`), que pidió A.
- Medido en vivo con el código nuevo, en un proceso aislado y sin reiniciar el server:
  - El barrido real mostró 5 CLI personales.
  - El motor 3568 salió `claude-desktop` por registro, con canal «Sesión de prueba».
  - El hilo 01a14a5d salió de sólo lectura, con pedido y respuesta reales.
  - La tarjeta de Desktop se actualizó con un mensaje enviado por el canal: el pedido a los 8 s y la respuesta a los 20 s. [V]

## Cómo estaba el lienzo el 2026-10-16

- El barrido descarta por ruta la app de Claude (`\WindowsApps\Claude_`), todo lo que corre bajo
  `\.vscode\extensions\`, cualquier proceso con `app-server` en la línea de comando y los procesos
  Electron (`--type=`) (`is_impostor`). No exige un padre shell: por eso adoptó el motor de Desktop
  como una sesión más (barrido del 2026-09-14 16:35, pid 34840). [V; corrige lo escrito el 16]
- Una sesión que llega por hook sin consola queda marcada `no_console`: se ve y se lee, pero no se le
  escribe (`lienzo/sessions.py:1217`). El comentario del código ya cuenta que las apps de escritorio
  disparan hooks. El envío la rechaza con «esta sesion no tiene consola (panel de VS Code o app de
  escritorio)» (`lienzo/sessions.py:2371`). [V]
- Para emparejar una TUI de Codex con su rollout se descartan los que traen `originator` distinto de
  `codex-tui` o `codex_cli_rs` (`lienzo/agentes.py:375`). [V]
- `procs.is_tui(pid)` decide si se puede teclear mirando sólo la ruta del ejecutable, sin la línea de
  comando (`lienzo/procs.py:84`). [V]

## Claude Desktop

### Lo que hay en esta PC

- Paquete MSIX `Claude` 2.16120.0.0 en `C:\Program Files\WindowsApps\Claude_2.16120.0.0_x64__pzs8sxrjxfjjc`. [V]
- Sus datos van virtualizados a
  `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude`, con carpetas
  `claude-code-sessions`, `local-agent-mode-sessions`, `scratch-workspaces` y `git-worktrees.json`. [V]
- Trae su propio motor: `...\Roaming\Claude\claude-code\2.1.284\claude.exe`. **No está bajo
  `WindowsApps`**: el filtro por ruta de `is_impostor` no lo atrapa. [V]
- Las sesiones de la pestaña Code escriben su transcripción en `~/.claude/projects/` como la CLI, con
  `"entrypoint":"claude-desktop"`. Hay dos de septiembre: `C--Users-ArielLevy-OneDrive---smartBI-Desktop/`
  y una en `scratch-workspaces`. Las de la CLI dicen `"entrypoint":"cli"`. [V]
- `claude_desktop_config.json` tiene `ccdScheduledTasksEnabled` y `coworkScheduledTasksEnabled` en
  `true`: Desktop puede arrancar sesiones solo, por tarea programada, sin que nadie abra nada. [V]

### Lo que dice la documentación oficial

Fuente: [Claude Code en Desktop](https://code.claude.com/docs/en/desktop) y
[deep links](https://code.claude.com/docs/en/deep-links).

- «Desktop runs the same underlying engine with a graphical interface». Lee los mismos archivos de
  configuración: «Hooks and skills defined in settings apply to both», y las reglas de permisos de
  `~/.claude/settings.json` también. [V]
- Pasar una sesión de la CLI a Desktop: `/desktop` en la terminal, o `claude --desktop --resume <id>`
  (Claude Code 2.1.285 o más nuevo). La CLI se cierra. No mueve una sesión que sigue abierta en otra
  terminal. [V]
- Al revés: `/resume` dentro de Desktop lista las sesiones de la CLI de esta PC. «Desktop continues the
  same session rather than a copy, so `claude --resume` in the terminal still finds it afterwards». [V]
- Desktop no tiene `--print` ni `--output-format`: «Desktop is interactive only». [V]
- Remote Control: una sesión local conectada aparece en claude.ai/code y en las apps de Claude. [V]
- Mensajes entre sesiones: Claude puede escribirle a otras sesiones de Claude Code «including terminal
  sessions». [V]
- Enlace `claude://code/new`: abre la página de sesión nueva; documentado con `ssh_host`, `ssh_port`,
  `ssh_folder` y `q` (texto precargado). No se documenta una carpeta local ni abrir una sesión
  existente. [V] El `claude-cli://open?cwd=...&q=...` es de la CLI y abre una terminal, no Desktop. [V]
- No hay API documentada para mandarle un mensaje a una sesión de Desktop desde afuera. [V]

### Por canal

| Canal | Qué funciona | Qué falta | Imposible o frágil |
|---|---|---|---|
| Detectar la sesión y su estado | Los hooks de `~/.claude/settings.json` corren también en Desktop [V doc]. El hook sube por los padres hasta un `claude.exe` (`hook.py:103`) y la tarjeta nace por evento, no por barrido [I]. | Medir que el evento traiga el PID y la ruta del `claude.exe` de Desktop y que la tarjeta salga `no_console`. Una marca propia («Desktop») para no mezclarla con VS Code. | `is_tui` no reconoce ese `claude.exe` como de Desktop por la ruta: podría darlo por TUI e intentar `AttachConsole` [I]. Hay que filtrarlo por padre (`claude.exe` de Electron) o por la ruta `\Roaming\Claude\claude-code\`. |
| Leer el contenido | La transcripción está en `~/.claude/projects` con el mismo formato [V]. | Nada nuevo: la cola ya la lee. Mostrar `entrypoint` en la tarjeta. | — |
| Mandar un mensaje | Nada hoy: el lienzo lo rechaza [V]. | Dos caminos a medir: (1) el canal nativo Claude-Claude, que la doc dice que alcanza a otras sesiones; (2) Remote Control, que la deja en claude.ai/code. | Teclear: Desktop no tiene consola. Automatizar la ventana Electron con UI Automation sería frágil y robaría foco. |
| Permisos y preguntas | Si `PermissionRequest` corre en Desktop, el hook del lienzo espera 60 s y contesta igual que en la terminal [I]. Si nadie contesta, Desktop muestra su tarjeta de aprobación [I]. | Medir que el `allow`/`deny` y el `updatedInput` de `AskUserQuestion` se respeten en Desktop. | Contestar después de los 60 s, cuando ya está la tarjeta de Desktop: no hay forma conocida. |
| Lanzar | `claude --desktop` abre Desktop en la carpeta actual; `claude://code/new?q=...` precarga un texto [V]. | Elegir la carpeta local desde el enlace (no documentado) y saber qué `session_id` nació. | El texto queda precargado, no se manda solo [V para `claude-cli://`; I para `claude://`]. |
| Retomar | `claude --desktop --resume <id>` lleva una sesión del lienzo a Desktop; `/resume` en Desktop la toma; `claude --resume` vuelve a la terminal [V]. | Un botón «abrir en Desktop» en la tarjeta. Al pasar, la terminal se cierra: la tarjeta tiene que seguir por `session_id` y quedar `no_console`. | La sesión no puede estar abierta en los dos lados a la vez [V]. |

## Codex desktop

### Lo que hay en esta PC

- Paquete MSIX `OpenAI.Codex` 26.1007.9446.0 en
  `C:\Program Files\WindowsApps\OpenAI.Codex_26.1007.9446.0_x64__2p2nqsd0c76g0`. [V]
- Comparte `~/.codex` con la CLI. Los rollouts de `~/.codex/sessions` traen `originator`
  `Codex Desktop`, `codex_work_desktop`, `codex_exec` o `codex-tui`. [V]
- Hay un daemon de app-server: `~/.codex/app-server-daemon/` (pid, logs, `daemon-updater.sock`) y
  `~/.codex/app-server-control/app-server-control.sock`. Al momento de mirar, su PID no estaba vivo.
  Su log del 2026-10-13 y 14 muestra que corre turnos (conecta a `responses`, cierra sesiones MCP):
  no es sólo un actualizador. [V] Que sea el app-server de la app, y no de otro cliente, es [I].
- `~/.codex/external_agent_session_imports.json` registra transcripciones de Claude
  (`~/.claude/projects/...jsonl`) importadas como hilos de Codex. [V]
- `~/.codex/hooks.json` tiene los hooks del lienzo, pero `~/.codex/config.toml` dice
  `[features] hooks = false`. Según la doc, eso apaga los hooks. Está así en los respaldos desde el
  2026-10-07. Ver «Riesgos». [V]

### Lo que dice la documentación oficial

Fuentes: [App Server](https://learn.chatgpt.com/docs/app-server.md),
[hooks](https://learn.chatgpt.com/docs/hooks.md),
[comandos y deep links de la app](https://learn.chatgpt.com/docs/reference/commands.md),
[«Unlocking the Codex harness»](https://openai.com/index/unlocking-the-codex-harness).

- La app de escritorio y la extensión de VS Code usan `codex app-server`: JSON-RPC 2.0. Transportes:
  `stdio://` (por defecto), `ws://` (experimental, sin soporte), `unix://` sobre el «default control
  socket», y `off`. `codex --remote` conecta la TUI a un app-server. [V]
- Métodos: `thread/list`, `thread/read`, `thread/resume`, `thread/start`, `turn/start`, `turn/steer`
  (agrega texto al turno activo, con `expectedTurnId`), `turn/interrupt`. [V]
- Aprobaciones: son pedidos del server al cliente (`item/commandExecution/requestApproval`,
  `item/fileChange/requestApproval`, `item/permissions/requestApproval`); el cliente contesta
  `accept`, `acceptForSession`, `decline` o `cancel`, y el server avisa `serverRequest/resolved`. [V]
- Hooks: `hooks/list` y las notificaciones `hook/started` y `hook/completed` existen en el app-server [V].
  La página de hooks sólo nombra la CLI; no dice si corren en la app [V]. «Hooks are enabled by
  default»; se apagan con `[features] hooks = false` [V].
- No dice si un segundo cliente puede engancharse al app-server de la app ni recibir sus aprobaciones.
  Habla de varios suscriptores por hilo («last subscriber») sin confirmarlo. [V]
- Deep links: `codex://new?prompt=...&path=<ruta absoluta>` abre un chat local con el texto en el
  editor, sin mandarlo; `codex://threads/<thread-id>` abre un hilo. [V]
- `codex app-server generate-json-schema` saca el esquema exacto de la versión instalada. [V]

### Por canal

| Canal | Qué funciona | Qué falta | Imposible o frágil |
|---|---|---|---|
| Detectar la sesión y su estado | Los rollouts de la app están en `~/.codex/sessions` con `originator` `Codex Desktop` [V]. | Un lector de rollouts por `originator` que arme tarjetas de sólo lectura sin proceso, con estado por el rollout (turno abierto o cerrado). Medir si los hooks corren en la app. | Los hooks hoy están apagados en `config.toml` [V]. Si el hook corriera, subiría hasta un `codex.exe app-server` que `is_tui` (sólo ruta) podría dar por TUI [I]. |
| Leer el contenido | El formato del rollout es el mismo que lee `transcripts.py` [V]. | Dejar de descartar `Codex Desktop` cuando no se busca una TUI (`agentes.py:375`). | — |
| Mandar un mensaje | Nada el 16 [V]. El 17: `codex queue --thread <id> --message …` entrega al hilo de la app (ver arriba) [V]. | Lo implementa A con confirmación por rollout. El cliente de app-server de abajo ya no hace falta para esto. | Con la app abierta en ese hilo, dos clientes escribiendo a la vez: sin documentar [V]; la app podría no mostrar lo que llegó por otro cliente hasta recargar [I]. |
| Permisos y preguntas | Si el lienzo es el cliente, las aprobaciones le llegan a él como pedidos JSON-RPC [V]. | Mapear esos pedidos a la tarjeta y a `pending/` con su `answer`. | Las aprobaciones de un hilo que maneja la app van a la app, no a un segundo cliente [I]. El hook `PermissionRequest` en la app: sin confirmar. |
| Lanzar | `codex://new?prompt=...&path=...` [V]. O el lienzo arranca su propio `codex app-server` y crea el hilo [V]. | Saber qué `thread_id` nació cuando lanza el enlace (leerlo del rollout nuevo). | El enlace sólo precarga, no manda [V]. |
| Retomar | `codex://threads/<id>` abre el hilo en la app; `codex resume <id>` en la terminal [V]. | Un botón «abrir en Codex» en la tarjeta. | — |

## Riesgos

- **Hooks de Codex apagados.** `~/.codex/config.toml` tiene `[features] hooks = false` al menos desde el
  2026-10-07, y la doc dice que eso apaga los hooks. La tarjeta de Codex viva hoy tenía `"source":
  "sweep"`. No se tocó: queda para que Ariel o la coordinadora decidan si fue a propósito. [V]
- **Un `claude.exe` o `codex.exe` de app tomado por TUI.** `is_tui` sólo mira la ruta, y ni el motor de
  Claude Desktop (`\Roaming\Claude\claude-code\`) ni el `codex.exe` de la app caen en los filtros por
  ruta. El lienzo podría intentar `AttachConsole` contra ellos. [I]
- **Interfaces que cambian.** El app-server cambia nombres de método entre versiones; el esquema se
  genera por versión. Los enlaces `claude://` para carpeta local no están documentados.
- **Doble cliente.** Escribir en un hilo que la app tiene abierto puede chocar con lo que hace el
  usuario en ese momento. Conviene que el lienzo escriba sólo en hilos que lanzó él, o con la app en
  otro hilo.
- **Mover sesiones cierra la terminal.** `claude --desktop --resume` termina la CLI: se pierden el PID y
  la consola, y con ellos el envío por teclas.

## Próximo paso

Una sesión de medición con Ariel, con las apps abiertas en una carpeta de prueba:

1. Claude Desktop: abrir una sesión Code y mirar en `~/.lienzo/events` si llegan `SessionStart`,
   `UserPromptSubmit`, `Stop` y `PermissionRequest`, con qué `agent_exe` y qué padre; ver que la
   tarjeta salga `no_console`; contestar un permiso y una pregunta desde el lienzo; probar si una
   coordinadora en terminal le llega por el canal nativo.
2. Codex desktop: con permiso de Ariel para prender `hooks` en una prueba, ver si corren en la app. Generar
   el esquema con `codex app-server generate-json-schema` y escribir un cliente mínimo fuera del server
   que haga `thread/start`, `turn/start` y conteste una aprobación; ver si ese hilo aparece en la app.
3. Con eso, decidir: Claude Desktop entra como tarjeta `no_console` con permisos por hook y mensajes por
   canal nativo; Codex desktop entra como hilos que el lienzo maneja por app-server y la app sólo
   muestra.
