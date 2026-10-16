# Lienzo con Claude Desktop y Codex desktop

Investigación del 2026-10-16, pedida por Ariel: qué hace falta para que el lienzo trabaje del todo
con las apps de escritorio de Claude y de Codex, en vez de con las terminales. Sólo documenta:
no se implementó ni se probó nada en vivo con las apps abiertas.

Cada afirmación lleva su marca:

- **[V]** verificado: en el código del repo, en un archivo de esta PC o en la documentación oficial.
- **[I]** inferido: deducido de lo anterior, sin medir. Hay que probarlo antes de construir encima.

## Cómo está hoy el lienzo

- El barrido arma tarjetas sólo de agentes cuyo padre es un shell, y descarta por ruta la app de
  Claude (`\WindowsApps\Claude_`), todo lo que corre bajo `\.vscode\extensions\`, cualquier proceso
  con `app-server` en la línea de comando y los procesos Electron (`--type=`)
  (`lienzo/procs.py:70`, `is_impostor`). [V]
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
| Mandar un mensaje | Nada hoy [V]. | Un cliente del app-server en el lienzo: `thread/resume` + `turn/start` o `turn/steer`. | Con la app abierta en ese hilo, dos clientes escribiendo a la vez: sin documentar [V]; la app podría no mostrar lo que llegó por otro cliente hasta recargar [I]. |
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
