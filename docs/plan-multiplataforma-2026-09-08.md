# Plan multiplataforma del lienzo — Mac, Linux, WSL

**Base:** commit `495c1de` más el árbol de trabajo a las 23:16 del 2026-09-07. Mientras se escribía
esto, la sesión coordinadora estaba editando `lienzo/sessions.py`, `lienzo/server.py` y
`lienzo/backend.py` (el rewire que este plan describe ya empezó): los números de línea de esos tres
archivos pueden haber corrido, el nombre de la función es la referencia firme. Sin tocar código:
el único archivo escrito es este.

**Qué es:** el diseño del port a Mac / Linux / WSL — la capa `backend`, lo que ya está hecho, lo que
falta, y una evaluación seria de la idea de meter Redis en el medio. No es una lista de deseos:
cada fase dice qué se puede medir para saber si quedó.

---

## La tesis, en cinco líneas

El lienzo no es una app de Windows: es una app de archivos con dos funciones de Windows adentro.
El estado sale de hooks que escriben JSON, el contenido de transcripciones `.jsonl` que los agentes
ya dejan en disco, las reglas son un JSON, el server es `http.server` y la UI es React estático.
Lo atado a Win32 son **dos verbos**: *escribirle a la consola de otro proceso* y *leer su pantalla*.
En Unix esos dos verbos los da tmux, mejor de lo que los da Windows —con scrollback y con la sesión
sobreviviendo al cierre de la terminal—. El port no es una reescritura: es una capa de indirección
de unas doscientas líneas, más media docena de detalles de plataforma que hoy están escondidos en
lugares que nadie miró (el hook, el instalador, dos `creationflags`, un `import` que no se puede
hacer fuera de Windows).

El precio real del port no es técnico, es de UX: **los agentes tienen que arrancar adentro de tmux**.
Esa condición es la única decisión de producto de todo este documento, y hay que tomarla explícita.

---

## 1. Dónde está atado a Windows, medido archivo por archivo

| Archivo | Qué tiene de Windows | Sale de acá |
|---|---|---|
| `send.py` | `AttachConsole` + `WriteConsoleInputW` sobre `CONIN$`, `VkKeyScanW`, `MapVirtualKeyW` | Reemplazo total: `tmux send-keys` |
| `screen.py` | `AttachConsole` + `ReadConsoleOutputCharacterW` sobre `CONOUT$` | Reemplazo total: `tmux capture-pane` |
| `procs.py` | `sweep()` por PowerShell/CIM, `cwd_of()` leyendo el PEB, `is_impostor()` por rutas de Windows | Reemplazo: `list-panes` + `/proc` (Linux) o `ps` (Mac) |
| `procinfo.py` | ctypes/`WinDLL` | **Ya resuelto**: `_WIN = sys.platform == "win32"`, importa en Linux sin reventar |
| `sessions.py` | `creationflags=0x00000008` en `run_send` y en `read_screen` | Condicional o innecesario (ver 3.4) |
| `server.py` | ruta de `cloudflared` en `Program Files (x86)`, `creationflags=0x08000000` en `tunnel_loop` | `shutil.which` + condicional |
| `hook.py` | `find_agent_pid()` sube por los padres con `procinfo.proc_info` | Reescritura chica, y hay un atajo mejor (ver 3.2) |
| `install.py` | candidatos de `python.exe` en `AppData`, comillas pensadas para PowerShell | Condicional por plataforma |
| `state.py` | `HOME = USERPROFILE or expanduser("~")`, `claude_slug()` reemplaza `:` `\` `/` | Ya es portable; el slug hay que confirmarlo en Unix |

Y lo que **no** tiene nada de Windows, que es la mayor parte: `transcripts.py` (703 líneas),
`rules.py`, `auth.py`, `state.py`, todo `server.py` salvo el túnel, y las 5.000 líneas de `web/`.
El barrido de procesos es un mecanismo de respaldo: la fuente principal de estado son los hooks, que
son JSON por stdin y archivos por disco en cualquier SO.

Dato duro del avance: **el server ya levanta en WSL** —health, UI y auth— sin instalar nada, con
stdlib pura. Eso no es un detalle: significa que el 90% del código ya es multiplataforma y lo que
queda es la capa de acceso a la consola.

---

## 2. La capa `backend`

### 2.1 La interfaz

Un módulo que elige implementación por plataforma y expone los mismos verbos. El resto del código
no debería saber cuál está abajo.

| Verbo | win32 | tmux | Qué devuelve |
|---|---|---|---|
| `NAME` | `"win32"` | `"tmux"` | para logs, `/health` y la UI |
| `sweep()` | CIM por PowerShell (~1 s) | `list-panes -a` + árbol de procesos (~30 ms) | lista de agentes vivos, con `target` |
| `alive(id)` | `GetExitCodeProcess` | el pane existe | bool |
| `agent_alive(id)` | vivo **y** sigue siendo claude/codex | ídem, por `cmdline` | bool |
| `can_write(card)` | `is_tui`: agente y no impostor | el pane existe y no está en copy-mode | bool |
| `cwd_of(id)` | PEB del proceso | `/proc/<pid>/cwd`, o `pane_current_path` | ruta o None |
| `send(card, texto)` | subproceso `send.py --pid` | `send-keys -l -- texto` + `Enter` | `{ok, chars, enter}` |
| `screen(card, scrollback)` | subproceso `screen.py --pid` | `capture-pane -p [-S -N]` | `{ok, lines[]}` |

Dos observaciones sobre la forma de la interfaz, mirando el rewire que está en curso:

**Pasar la tarjeta, no el PID.** Hoy `run_send(sid, pid, final)` y `read_screen(pid)` hablan PID.
Si la firma pasa a `send(s, texto)` y `screen(s)`, `sessions.py` deja de saber qué es la identidad
y el `if backend.NAME == "tmux"` desaparece del cuerpo de `run_send`. Con la firma por PID, ese `if`
(y el `import tmux` en `sessions.py`) se queda para siempre, y cada verbo nuevo lo repite. Es una
línea de diferencia hoy y una costura limpia después.

**`send_blocked()` tiene que preguntarle al backend.** Hoy arranca con `if not s.get("pid") or not
backend.agent_alive(s["pid"])`. En tmux la pregunta correcta no es "¿el PID vive?" sino "¿el pane
existe y es escribible?": un agente puede reemplazarse a sí mismo dentro del pane (un `/clear`, un
`exec`) y el pane sigue siendo el lugar correcto donde escribir. Que la razón por la que no se puede
escribir la dé el backend deja la lógica de negocio —huérfana, sin consola, tipeando— en un solo
lado.

### 2.2 Identidad genérica: de PID a pane

En Windows la identidad de "dónde escribo" es el PID, porque la consola pertenece al proceso.
En tmux es el **pane** (`%0`, `%1`, …), y el PID pasa a ser un dato satélite que sirve para dos
cosas: liveness y `cwd`.

El modelo que ya quedó en el árbol es el correcto: la tarjeta guarda `pid` **y** `target`, con
`target = None` en Windows. Vale la pena que la UI y el log hablen de "destino" y no de PID cuando
el backend es tmux (con *Detalles técnicos* prendido, "pane %3" en vez de "PID 20916").

**El riesgo que trae el pane, y que hay que atender:** los ids de pane son únicos mientras vive el
server de tmux, pero si tmux se reinicia vuelven a empezar en `%0`. Una tarjeta persistida en
`~/.lienzo/sessions/` con `target: "%3"` de ayer puede apuntar hoy a **otro pane, de otro repo**, y
escribir ahí es exactamente el peor error que puede cometer esta app: tecleo real en la terminal
equivocada. Es el mismo problema que en Windows resuelve `agent_alive()` con el PID reciclado, y se
resuelve igual: **revalidar antes de cada envío** que el pane sigue conteniendo al agente que la
tarjeta cree (comparar `pane_pid` y el árbol contra el `pid` guardado, o guardar además el
`pane_start_time`). Barato: un `list-panes` son ~15 ms. Sin esa revalidación, el port tiene un bug
de corrupción silenciosa desde el día uno.

### 2.3 Quién elige, y qué pasa si no hay tmux

`sys.platform == "win32"` → win32; si no → tmux. Es lo correcto: en Windows tmux no existe de forma
usable y el camino nativo ya está probado; en Unix no hay alternativa a tmux salvo no poder escribir.

Falta el tercer caso, que va a pasar seguido: **Unix sin tmux**, o con tmux instalado pero con los
agentes corriendo fuera de un pane. Hoy eso da un tablero vacío sin explicación. La degradación
correcta ya existe en el modelo: `no_console`. Una sesión que reporta por hooks pero no vive en
ningún pane es exactamente el caso del panel de VS Code —se ve, se lee, no se le escribe—, y la
tarjeta ya sabe mostrarlo. Con eso, un Mac sin tmux sigue siendo útil (tablero de sólo lectura con
transcripciones, digest y estado), y el mensaje "esta sesión no está en tmux: no puedo escribirle"
es una invitación clara en vez de un misterio. Si además `/health` dice `backend: tmux, panes: 0,
agentes fuera de tmux: 3`, el diagnóstico se hace solo.

### 2.4 Lo que **no** va en `backend`

Importa tanto como lo que sí, porque es donde se va a querer meter código de plataforma por comodidad:

- `compose_send()` —el armado del texto, el corte a adjunto arriba de 500 caracteres, el filtrado de
  caracteres de control del hallazgo A4— es agnóstico y tiene que quedarse en `sessions.py`. El
  backend recibe texto ya limpio y lo teclea.
- `input_area()` (hoy en `screen.py`) es una función pura sobre una lista de líneas: parsea la caja
  de entrada de la TUI de Claude Code. Sirve igual para lo que devuelve `capture-pane`. **Pero hoy
  no se puede importar fuera de Windows**, porque `screen.py` hace `ctypes.WinDLL` en el cuerpo del
  módulo. Hay que sacarla a un módulo neutro (`tui.py`, con `PLACEHOLDERS` y `RULE_CHARS`) e
  importarla desde los dos lados. Es el único pedazo de lógica compartida que hoy está preso.
- Las reglas, los links, el estado, la máquina de estados de la tarjeta: no tocan la plataforma.

---

## 3. Qué está hecho y qué falta

### 3.1 Hecho (fase 0 y 1, verificado)

- `lienzo/tmux.py`: `send`, `screen`, `list_panes`, `find_agent_panes`, `pid_alive`, `cwd_of`,
  `cmdline`. Solo stdlib.
- `tests/tmux_smoke.py`: levanta un tmux propio con un REPL de Python, lo descubre, le teclea una
  línea que **escribe un archivo**, y lee la pantalla. Es una prueba dura de verdad: no verifica que
  el comando no falle, verifica que el proceso del otro lado ejecutó lo que se le tecleó.
- `procinfo.py` aislado por plataforma; el server levanta en WSL (health, UI, auth).
- `lienzo-server.sh`.
- `backend.py` y el rewire de `sessions.py`: en curso mientras se escribe esto.

### 3.2 Falta: el hook en Unix (esto es lo que hoy rompe el circuito)

`hook.py:find_agent_pid()` sube por la cadena de padres con `procinfo.proc_info()`, que fuera de
Windows devuelve `(None, None)` en el primer salto. Resultado en Mac o Linux: **todo evento de hook
sale con `pid: None`**. Y en `apply_event()` la línea es `if ev.get("pid") and
backend.agent_alive(ev["pid"]): claim_pid(...)`, así que la tarjeta nunca reclama proceso: se ve,
pero no tiene liveness ni destino y no se le puede escribir. El barrido la adopta después por
`cwd`, con lo que la sesión aparece por la puerta de atrás y hasta 30 segundos tarde.

Hay un atajo mucho mejor que reescribir el paseo por `/proc`: **tmux exporta `TMUX_PANE` en el
entorno de cada pane**, y el hook corre como hijo del agente, que es hijo del shell del pane. O sea
que el hook puede leer su propio destino de una variable de entorno, sin `/proc`, sin `ps`, sin
árbol de procesos, y funciona igual en Mac que en Linux:

```python
target = os.environ.get("TMUX_PANE")   # "%3"
```

Con eso el evento trae el pane directo, el descubrimiento por hooks queda **más simple en Unix que
en Windows**, y el `cwd` ya viene en el payload del hook (se usa en `wait_for_answer`). El PID pasa a
ser opcional: se puede completar con un paseo por `/proc` en Linux y dejar en `None` en Mac, o
derivarlo del pane cuando haga falta. Vale la pena verificarlo antes de diseñar encima —es un
comando: `tmux new-session -d 'echo $TMUX_PANE > /tmp/p'`—, pero es estándar de tmux desde siempre.

### 3.3 Falta: descubrimiento en **Mac** (el agujero grande de `tmux.py`)

`tmux.py` está escrito contra `/proc`: `_ppid()` lee `/proc/<pid>/stat`, `_cwd()` hace `readlink
/proc/<pid>/cwd`, `pid_alive()` es `os.path.isdir("/proc/<pid>")`. **macOS no tiene `/proc`.** Tal
como está, en Mac `find_agent_panes()` devuelve lista vacía y `pid_alive()` devuelve `False` para
todo: el tablero queda mudo, sin ningún error visible. Esto no es un detalle pendiente, es la
diferencia entre "anda en Linux" y "anda en Unix".

Lo que hace falta, chico y acotado:

- **Liveness**: `os.kill(pid, 0)` dentro de `try/except` es portable y reemplaza a `isdir(/proc/...)`
  en los dos SO. Es el cambio más barato del plan.
- **Árbol de procesos**: una sola llamada `ps -axo pid=,ppid=,comm=,command=` reemplaza al recorrido
  de `/proc` completo y sirve para Linux **y** Mac (más lenta: ~30-50 ms contra ~10 ms, irrelevante
  para un barrido cada 30 s). Conviene una sola implementación por `ps` para los dos, en vez de dos
  caminos: menos código, y el que se prueba en WSL es el mismo que corre en Mac.
- **`cwd` del agente**: es lo único que no tiene equivalente barato. En Mac se saca con
  `lsof -a -d cwd -p <pid> -Fn` (~50 ms, `lsof` viene con el sistema) o directamente con
  `#{pane_current_path}` del pane. La segunda alternativa alcanza para el 99% de los casos —los
  agentes no hacen `chdir` del proceso— y es gratis, porque `list_panes()` ya la trae. Propuesta:
  `cwd` del pane por defecto, `/proc` cuando existe, `lsof` sólo si algún día aparece un caso que
  lo justifique.

### 3.4 Falta: los detalles de plataforma sueltos

- **`creationflags`**: `subprocess.run(..., creationflags=...)` **levanta `ValueError` en POSIX**, no
  se ignora. Está en `run_send` (`0x00000008`, DETACHED_PROCESS) y en `read_screen` (ídem), y en
  `tunnel_loop` de `server.py` (`0x08000000`, CREATE_NO_WINDOW). En el camino tmux los dos primeros
  desaparecen —no hace falta subproceso, `tmux send-keys` se llama en proceso—, pero el del túnel
  hay que condicionarlo o `--remote` explota en Mac apenas se lo intente.
- **`cloudflared`**: hoy la ruta está clavada en `Program Files (x86)`. En Unix, `shutil.which("cloudflared")`
  (brew en Mac, paquete en Linux). El resto del túnel es agnóstico.
- **`install.py`**: los candidatos de `python.exe` en `AppData` y las comillas pensadas para
  PowerShell son de Windows; en Unix alcanza `sys.executable` y `~/.claude/settings.json` está en el
  mismo lugar. Conviene además hacer `chmod +x hook.py` y verificar que Codex en Mac use el mismo
  `~/.codex/hooks.json`.
- **`claude_slug()`**: reemplaza `:` `\` `/` por `-`. En Unix, `/home/ariel/apps/lienzo` da
  `-home-ariel-apps-lienzo`, que es la convención que usa Claude Code, pero hay que confirmarlo con
  un `ls ~/.claude/projects` en un Mac real antes de darlo por hecho: si no coincide, las tarjetas
  aparecen sin transcripción y el síntoma es confuso (tablero con estado pero sin contenido).
- **Los tests**: los 97 de la suite corren en Windows y varios prueban Win32 (`test_procs.py`).
  Necesitan marcadores para saltearse en Linux, y `tmux_smoke.py` merece volverse `test_tmux.py`
  bajo pytest. Sin eso, el port no tiene red de contención en el lado nuevo y el lado viejo se
  vuelve difícil de correr en el nuevo.

### 3.5 Ganancias que el port trae de regalo

No es sólo paridad; en tmux hay tres cosas que Windows no puede dar:

1. **Scrollback**. `capture-pane -S -N` lee hacia atrás. La pestaña *Pantalla*, que hoy muestra sólo
   lo visible, puede tener un "más arriba". (En Windows hay un equivalente parcial: `screen.py --all`
   lee el buffer entero.) La API `screen(target, scrollback)` los unifica.
2. **La sesión sobrevive a la terminal**. La limitación conocida "una sesión cuya terminal se cerró
   no acepta mensajes" desaparece: en tmux cerrar la ventana es un detach. Para el flujo de delegar
   y volver más tarde, eso vale más que todo el resto del port.
3. **Latencia**. El envío deja de ser un subproceso de Python con `AttachConsole` y pasa a ser un
   `send-keys` de milisegundos; la lectura de pantalla baja de los 183 ms medidos por sesión a unos
   pocos, con lo que el `screen_loop` cada 5 s deja de ser un costo a cuidar.

---

## 4. Arrancar los agentes adentro de tmux

Es la condición del port y el único costo de UX. Vale la pena mirarlo de frente.

**El costo.** Hoy en Windows abrís una terminal, escribís `claude`, y la tarjeta aparece sola: cero
ceremonia, y el barrido levanta hasta las sesiones que ya estaban abiertas antes de instalar nada.
En Unix eso deja de ser cierto: una sesión arrancada fuera de tmux es invisible para el envío. Es un
paso más y una cosa nueva que recordar, y quien no use tmux hoy lo va a vivir como una imposición.

**Lo que lo compensa.** tmux no es un impuesto arbitrario: es lo que hace que la sesión sobreviva al
cierre de la terminal, y eso es justo lo que el flujo de delegación necesita —repartís tres encargos,
cerrás la laptop, volvés y siguen—. En Mac, además, `tmux -CC attach` (integración nativa de iTerm2)
muestra cada pane de tmux como una **pestaña nativa de iTerm2**: se usa igual que siempre y por
debajo es tmux. Con eso el costo de UX en Mac se vuelve casi cero, y conviene que el README lo diga
en la primera línea de la sección, no en una nota al pie.

**El helper.** `lienzo new` como envoltorio de una línea:

```
lienzo new [ruta] [--agent claude|codex] [--name titulo]
  → tmux new-session -d -s lienzo-<repo>-<n> -c <ruta> <agente>   (y attach, o new-window si ya estás adentro)
```

Vale la pena que haga tres cosas más, que son las que lo convierten en herramienta y no en alias:
nombrar la sesión de tmux de forma que se lea en el tablero, dejar el título de la tarjeta puesto de
entrada (hoy el título tarda hasta el primer turno), y avisar si el server no está corriendo.

**La degradación, otra vez, porque es la que decide si esto se siente bien o mal.** El caso "abrí
claude sin tmux" va a pasar todos los días al principio. La respuesta correcta no es un tablero
vacío: es la tarjeta visible en modo lectura con el motivo escrito, y el atajo para arrancarla bien
la próxima vez. Es exactamente lo que ya hace el lienzo con el panel de VS Code.

---

## 5. Dos mundos en una PC: Windows + WSL

Este es el escenario multi-máquina que Ariel va a tener **primero**, y sin comprar nada: agentes
corriendo en Windows y agentes corriendo en WSL, en la misma computadora. Merece su propio análisis
porque es el que la gente confunde con "necesito Redis".

Los hechos:

- Son dos `HOME` distintos: `C:\Users\ArielLevy\.lienzo` y `/home/ariel/.lienzo`. Dos juegos de
  eventos, reglas, links y tarjetas. Dos servers, dos tableros, cada uno ciego al otro.
- Windows **puede** leer los archivos de WSL (`\\wsl$\Ubuntu\home\ariel\...`) y puede ejecutar
  comandos adentro (`wsl.exe -d Ubuntu tmux …`).
- Lo que no puede es al revés de forma útil: desde WSL no hay manera de escribir en una consola de
  Windows.

De ahí sale el camino barato, si alguna vez se quiere un solo tablero en esa PC: **el server corre en
Windows y suma un segundo backend** cuyo `_tmux()` es `wsl.exe -d <distro> tmux …`. El descubrimiento,
el envío y la lectura de pantalla funcionan tal cual (son comandos de tmux); los eventos y las
transcripciones se leen por `\\wsl$`. No hace falta ningún servicio nuevo: es la misma capa `backend`
con un prefijo. Un backend por mundo, y la tarjeta ya guarda a cuál pertenece.

Los dos problemas reales de ese camino, para que quede escrito antes de intentarlo:

1. **Las rutas de los adjuntos.** Un texto largo viaja como "Adjunto: C:\Users\...\mensaje.md" y el
   agente lo abre por ruta. Un agente en WSL no puede abrir esa ruta: necesita `/mnt/c/Users/...`.
   Hay que traducir con `wslpath` en el momento de componer el envío, según el mundo del destino. Es
   chico pero es obligatorio: sin eso, todo mensaje largo llega roto.
2. **El costo de leer `\\wsl$`.** El bucle de eventos hace `listdir` cada 250 ms. Sobre 9P eso pasa
   de microsegundos a milisegundos. Se resuelve bajando la frecuencia del mundo remoto o dejando que
   el hook de WSL escriba en el `~/.lienzo/events` de Windows (que desde WSL es `/mnt/c/...`, y es
   escritura local rápida). La segunda es mejor: **un solo buzón de eventos, el del mundo donde corre
   el tablero**. Cambia una constante del hook, nada más.

Conclusión de esta sección, que es la que importa para la siguiente: el escenario "dos mundos" se
resuelve con traducción de rutas y un prefijo de comando. No hace falta un bus de mensajería.

---

## 6. Redis: la evaluación

Ariel pidió que se evalúe en serio meter Redis para la mensajería. Va en serio, entonces: primero
qué es hoy "la mensajería", después qué reemplazaría, qué gana, qué cuesta, dónde sí y dónde no.

### 6.1 Qué es hoy la mensajería del lienzo

No es una cosa: son seis, y sólo tres son "mensajes".

| # | Canal | Cómo | Volumen / latencia hoy |
|---|---|---|---|
| 1 | hook → server (estado) | archivo JSON en `~/.lienzo/events`, consumo destructivo, orden por `time_ns` | poll cada 250 ms |
| 2 | server ↔ hook (permisos) | `pending/<id>.json` + `answers/<id>.json` con nonce, vencimiento 60 s | poll de 250 ms de los dos lados |
| 3 | server → agente (**el mensaje de verdad**) | tecleo en la consola / pane | milisegundos |
| 4 | server → navegador | SSE en memoria (`clients: list[queue.Queue]`) | push |
| 5 | estado persistido | `links.json`, `rules.json`, `sessions/*.json`, `config.json` | un solo escritor |
| 6 | Claude ↔ Claude nativo | `SendMessage` entre sesiones, **fuera del lienzo** | el lienzo sólo lo marca |

El punto 3 es el que define todo el análisis: **entregar un mensaje a un agente no es publicar en un
tópico, es tener un proceso en esa máquina que le teclee a una consola local.** Redis no puede
tocarlo. Cualquier arquitectura distribuida del lienzo necesita un proceso por máquina, con o sin
Redis. Redis no reemplaza al satélite: como mucho, es cómo el satélite se entera.

### 6.2 Qué reemplazaría Redis, punto por punto

- **Eventos (1)**: `XADD` a un Stream + `XREADGROUP`. Gana push en lugar de poll, historial y replay
  (hoy los eventos se borran al consumirse, y para depurar eso duele), y varios consumidores.
- **Permisos (2)**: `BLPOP` con timeout en lugar del bucle de 250 ms. Es el reemplazo más elegante
  de los seis: el rendezvous bloqueante es literalmente lo que `BLPOP` hace.
- **Estado (5)**: hashes o JSON en Redis, con `PUBLISH` para invalidar. Sólo tiene sentido si hay
  **más de un server**; con uno, un dict en memoria respaldado por un archivo es más rápido y más
  simple.
- **SSE (4)**: pub/sub para que varios servers le hablen al mismo navegador. Mismo comentario.
- **Comandos server → satélite** (que hoy no existe): una cola durable por máquina. Este es el único
  caso nuevo de verdad.

### 6.3 Qué gana

- **Multi-máquina**: sí, real. Con dos o tres máquinas, un bus con colas por destino es la forma
  natural de repartir "mandale este texto al pane %3 de la máquina B".
- **Latencia**: 250 ms → push. Honestamente: irrelevante. Un humano mirando un tablero no percibe
  la diferencia, y el `screen_loop` corre cada 5 s de todos modos.
- **Replay y depuración**: un Stream con los eventos de la semana es una herramienta linda para
  entender por qué una tarjeta quedó en un estado raro. Hoy eso se reconstruye del `lienzo.log`.
- **El permiso sin poll**: menos código y menos vueltas en el camino crítico que bloquea al agente.

### 6.4 Qué cuesta

- **Deja de ser "git clone y andar".** Hoy el requisito es Python y —sólo para compilar la UI— Node.
  Cero servicios. Con Redis: instalarlo (en Windows es WSL o Memurai; en Mac, brew), arrancarlo,
  mantenerlo corriendo, y que un tablero que no arranca pueda tener como causa "el servicio de Redis
  está caído". Ese valor —**cero dependencias, cero servicios**— es el que se pone en juego, y es de
  los que no se recuperan una vez perdidos.
- **La dependencia de cliente.** `redis-py` no es stdlib, y todo el proyecto es stdlib pura y a
  propósito. Hay salida: RESP2 es un protocolo de texto trivial y un cliente mínimo para los siete
  comandos que harían falta (`PUBLISH`, `SUBSCRIBE`, `XADD`, `XREAD`, `SET`, `GET`, `BLPOP`) entra en
  unas 120 líneas de socket y parseo. Es coherente con la línea de la casa, pero es código nuevo, con
  reconexión, timeouts y tests propios en dos SO. No es gratis.
- **La seguridad, que acá pesa el doble.** El modelo de amenaza de hoy es chico y explícito:
  `127.0.0.1`, más un túnel con TOTP. Aun así, el pentest de ayer encontró un crítico y cuatro altos
  sobre esa superficie. Un Redis escuchando en 6379 sin auth es el clásico de manual; y la primitiva
  que este sistema expone no es "leer datos", es **"tecleá esto en la consola de un agente con
  permisos de escritura sobre un repo"**. Un bus comprometido es ejecución remota en todas las
  máquinas conectadas. Hacerlo bien implica TLS, ACLs, bind local, credenciales rotables y firma de
  los comandos: eso es un proyecto de seguridad, no una línea de configuración.
- **El hook pasa a depender de la red.** Este es el argumento que a mi juicio cierra la discusión
  para el camino 1 y 2. Hoy el hook corre en **cada evento de cada agente**, arranca en ~200 ms,
  escribe un archivo y se va; si el server está caído, los eventos se acumulan y se consumen después.
  El archivo es el desacople. Si el hook habla Redis, un servicio caído o lento se transforma en
  latencia adentro del agente —y en el caso del `PermissionRequest`, que es sincrónico y bloquea al
  agente hasta 60 s, en un agente colgado—. Nunca hay que poner una dependencia de red en el camino
  crítico de una herramienta que corre en cada tecla.
- **Dos caminos de código para siempre**, con tests de los dos.

### 6.5 Dónde sí y dónde no

**No** en una sola PC. Los archivos ya dan durabilidad (el buzón de eventos *es* una cola durable),
orden (nombre por `time_ns`), atomicidad (`os.replace`) y desacople. Redis no agregaría nada que se
note.

**No** para Windows + WSL en la misma máquina: se resuelve con traducción de rutas y un backend
proxy (sección 5).

**Sí** cuando haya **dos o más máquinas con identidad de red propia** —una que se queda trabajando
en casa y la laptop, o una VM en la nube— y se quiera **un solo tablero**. Ahí el problema deja de
ser de archivos y pasa a ser de transporte, y un bus es la respuesta natural.

**Ni siquiera ahí, todavía**, y este es el contrapunto más fuerte: **el lienzo ya tiene un protocolo
remoto**. Es HTTP con `X-Lienzo`, cookie de sesión, TOTP, freno de intentos y túnel TLS por
cloudflared, todo probado y auditado. Un satélite en la máquina B que haga `POST /events` con lo que
recoge de su buzón local y un `GET /commands` con long-poll para recibir los envíos reusa **todo**
eso: cero servicios nuevos, cero protocolos nuevos, la misma auth, el mismo túnel, el mismo modelo de
amenaza que ya se revisó. Redis sería un tercer protocolo al lado de dos que ya funcionan.

Mi recomendación: si aparece la máquina 2, **empezar por el satélite HTTP**. Redis recién si aparecen
tres o más satélites, o si hace falta replay/durabilidad del bus más allá de lo que da el buzón de
archivos.

### 6.6 La frontera, si algún día se cruza

Que la decisión sea "no ahora" no significa "no prepararse". Lo que conviene hacer ya, porque es
barato y mejora el código igual, es **la costura**: que la mensajería no esté cableada a rutas de
archivo desparramadas por tres módulos.

**Queda en archivos, siempre, con backend o sin él:**

- Las transcripciones: son archivos de los agentes, de megabytes, y se leen por la cola.
- Los adjuntos: el agente los abre **por ruta local**. Un adjunto para un agente en otra máquina hay
  que copiarlo allá; ningún bus lo evita.
- El buzón de eventos del hook: por lo dicho en 6.4. El hook nunca habla red.
- El rendezvous de permisos: es local por definición —el agente y el que teclea están en la misma
  máquina—.

**Podría ir a un bus, el día que haya más de un server:**

- El fan-out de tarjetas, links, reglas y pendientes entre servers.
- La cola de comandos server → satélite.
- El SSE agregado.

**La forma:** un `bus.py` con cuatro verbos (`publish`, `subscribe`, `request/reply`, `kv`), una
implementación `files` que es exactamente lo de hoy y es **el default**, y una `http` (satélite) o
`redis` seleccionable por `~/.lienzo/config.json`. Opcional de verdad: quien hace `git clone` no se
entera de que existe.

**Veredicto: no a Redis hoy. Sí a la costura, y sí al satélite HTTP como primera respuesta a
multi-máquina.**

---

## 7. Plan por fases

Cada fase dice qué se puede medir. Sin eso, "está hecho" es una opinión.

### Fase 0 — Piso (hecha)

`tmux.py`, `procinfo.py` aislado, el `.sh`, el server levantando en WSL.
**Verificable:** `python3 tests/tmux_smoke.py` → "TODO OK"; `curl 127.0.0.1:7321/health` desde WSL.

### Fase 1 — `backend.py` y el rewire (en curso)

La capa de indirección y `sessions.py` hablando `backend.*`. Incluye pasar la tarjeta en vez del PID
(2.1) y sacar el `if NAME == "tmux"` del cuerpo de `run_send`.
**Verificable:** en Windows, los 97 tests de la suite siguen verdes y el tablero se comporta igual
—esta es la medición que importa, la de la no-regresión—; en WSL, `backend.NAME == "tmux"` y el smoke
verde.

### Fase 2 — El circuito completo en WSL

Hook con `TMUX_PANE` (3.2), `install.py` para Unix, `creationflags` condicionales, `input_area` fuera
de `screen.py`.
**Verificable, con un `claude` de verdad en un pane:** la tarjeta aparece en menos de 5 s (por hook,
no por barrido) con repo y título; pasa a *Te necesita* cuando pide permiso; **el permiso se
responde desde el tablero y el agente sigue** (esto prueba los dos sentidos del canal 2); un envío
desde la caja aparece en el `.jsonl` de la transcripción y el agente contesta; la pestaña *Pantalla*
muestra la caja de entrada.

### Fase 3 — Mac

`os.kill(pid, 0)` para liveness, `ps` en vez de `/proc`, `cwd` del pane. Confirmar `claude_slug` y la
ruta de `~/.codex`. `cloudflared` por `which`.
**Verificable:** la misma lista de la fase 2, corrida en un Mac real, más `--remote` levantando el
túnel. Sin un Mac de verdad esta fase no se puede cerrar: escribirla a ciegas es adivinar.

### Fase 4 — Que se sienta bien

`lienzo new`, degradación de las sesiones fuera de tmux a modo lectura con el motivo escrito,
scrollback en *Pantalla*, `backend` visible en *Detalles técnicos*, README con la sección de tmux y
`tmux -CC` arriba de todo.
**Verificable:** alguien que nunca usó el lienzo, en un Mac, del `git clone` a la primera tarjeta con
envío, sin preguntar nada. Ese es el test.

### Fase 5 — Condicional, sólo si aparece

`bus.py` con default `files` (costura, barata, se puede hacer antes). Satélite HTTP si aparece la
máquina 2. Redis si aparece la tercera.
**Verificable:** un envío desde el tablero de la máquina A llega a un agente de la máquina B, y su
informe vuelve al tablero de A.

---

## 8. Riesgos

**Regresión en Windows.** Es el riesgo número uno y el más caro: el rewire toca `sessions.py`, 1.365
líneas con la máquina de estados, el lock y la herencia de PID entre sesiones, que es lo más delicado
del proyecto. Toda la suite de tests vive del lado de Windows. Mitigación: que `backend.py` sea un
adaptador fino y que la semántica de Windows no cambie ni un poco en la fase 1 —mismo comportamiento,
otra indirección—, y correr la suite completa antes de cada commit de esa fase.

**El lado nuevo sin red de contención.** El camino tmux tiene un smoke y nada más. Todo bug ahí se
descubre usando. Mitigación: pasar el smoke a pytest, y correrlo en WSL en cada ronda; si en algún
momento hay CI, una matriz windows/ubuntu con los tests agnósticos en las dos.

**El pane equivocado.** Ya explicado en 2.2: sin revalidar el `target` antes de escribir, el sistema
puede teclear en la terminal de otro. Es el único riesgo del plan que produce daño en el repo del
usuario y no sólo una pantalla fea. Va con el envío, no después.

**El costo de UX de tmux.** Riesgo de producto, no técnico: gente que prueba el lienzo en Mac, no
está en tmux, ve un tablero mudo y se va. Mitigación: la degradación a modo lectura con el motivo
escrito, `lienzo new`, y `tmux -CC` visible en el README.

**Redis como dependencia opcional.** Si algún día entra: dos caminos de código, tests de los dos, y
la promesa "sin servicios" pasa a tener asterisco. Mitigación: que el default nunca lo necesite y que
el README no lo mencione en la instalación, sino en una sección aparte.

**Deriva entre plataformas.** Que el camino tmux quede segundo de siempre y se pudra sin que nadie se
entere. Mitigación: que `/health` diga el backend, y que cada ronda de trabajo se cierre con el smoke
corrido en los dos mundos.

---

## 9. Lo que hay que decidir (no lo decide el plan)

1. **¿tmux es requisito en Unix, o hay modo lectura sin tmux?**
   Recomendación: modo lectura, reusando `no_console`. Cuesta poco y decide la primera impresión.
2. **¿Windows se queda con su camino nativo para siempre?**
   Recomendación: sí. tmux en Windows nativo no es una opción real y el camino Win32 está probado y
   auditado. Dos backends, no uno.
3. **¿El tablero de una PC tiene que ver los dos mundos (Windows y WSL) a la vez?**
   Recomendación: por ahora no, un tablero por mundo. Si molesta, el camino es el de la sección 5
   —backend proxy por `wsl.exe` y traducción de rutas—, no un bus.
4. **¿Se hace la costura `bus.py` ahora o cuando haga falta?**
   Recomendación: ahora sólo si sale gratis mientras se toca ese código; si no, cuando aparezca la
   máquina 2. Lo que **no** hay que hacer es Redis primero y buscarle el caso de uso después.
5. **¿Hay un Mac disponible para cerrar la fase 3?**
   Sin eso, el port es "Linux y WSL", que es igual de válido pero hay que decirlo así en el README en
   vez de prometer Mac.
