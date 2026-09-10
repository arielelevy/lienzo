# Lienzo

Tablero para las sesiones de **Claude Code** y **Codex CLI** que corren en terminales de
Windows: la integrada de VS Code, Windows Terminal, una PowerShell o un cmd sueltos. Una
tarjeta por sesión, agrupadas por columna (trabajo, te necesita, muerta), con la
conversación a un click, una caja para contestarles, **aprobación de permisos sin ir a la
terminal**, capturas pegadas con Ctrl+V y conexiones entre sesiones.

Corre local, en `127.0.0.1:7321`. El acceso desde el celular es opcional y no hace falta
instalar nada para usarlo en la propia PC.

No hospeda terminales ni guarda historial propio: es un monitor con derecho a contestar.

Las apps de escritorio de Claude y de Codex no tienen consola: sus sesiones se pueden ver
(si disparan hooks) pero no se les puede escribir desde acá.

![Tablero](docs/img/tablero.png)

## Cómo funciona

Al arrancar, y después cada 30 segundos, el server **recorre los procesos de la PC** y
encuentra todas las terminales de Claude Code (`claude.exe`) y Codex CLI (`codex.exe`) que
estén corriendo, aunque se hayan abierto antes de instalar nada: lee el directorio de
trabajo de cada proceso, ubica su transcripción y arma la tarjeta. Descarta las apps de
escritorio y las extensiones de VS Code, que usan los mismos nombres de ejecutable.

Después, cuatro canales, cada uno por su lado:

| Qué | Cómo |
|---|---|
| Estado de cada sesión | Hooks de los propios agentes (`SessionStart`, `UserPromptSubmit`, `Stop`, `PermissionRequest`…) que escriben un archivo en `~/.lienzo/events`. Nunca se raspa la pantalla para esto. |
| Contenido | Las transcripciones `.jsonl` que Claude Code y Codex ya escriben en disco. Se leen por la cola, nunca enteras. |
| Mandar un mensaje | Inyección de teclas en la consola del proceso por PID (`AttachConsole` + `WriteConsoleInputW`). Funciona sin foco y aunque la pestaña esté oculta. Los adjuntos viajan como ruta en el texto. |
| Contestar un permiso | El hook `PermissionRequest` es sincrónico: deja el pedido en una carpeta y espera hasta 60 s la respuesta que el tablero escribe. Si nadie contesta, el prompt aparece en la terminal como siempre. |
| Contestar una pregunta | El mismo hook: `AskUserQuestion` pide permiso como cualquier herramienta. La opción elegida vuelve adentro del `updatedInput` de la decisión, que es donde la deja el menú de la consola. |

Además: conexiones entre sesiones (reenvío ahora, cuando termine, programado a una hora o
cada tanto con tope, canal nativo Claude a Claude), flechas entre las tarjetas por cada
conexión, y una pestaña que muestra el texto visible de la terminal leído del buffer de consola.

Cuando una consola cambia de `session_id` sin cambiar de proceso (un `/clear` o un resume
en Claude Code), la tarjeta nueva hereda el PID de la vieja y todas las conexiones que la
apuntaban: las reglas "cuando termine" y el historial de envíos pasan a la sesión nueva y
la vieja se da de baja. Una prueba manual del hook con un `session_id` inventado y el PID
de una sesión viva no la reemplaza.

![Panel de una sesión](docs/img/panel.png)

## Requisitos

- Windows 10/11: es donde está probado. Hoy no corre en Mac ni en Linux.
- Python 3.12 o más nuevo, sólo biblioteca estándar. Sin `psutil`, sin frameworks.
- Node 20 o más nuevo para compilar la interfaz (Vite + React + TypeScript).
- Claude Code 2.1 o más nuevo, Codex CLI 0.153 o más nuevo, o los dos.
- Sólo para el acceso desde el celular, y sólo si lo querés: `cloudflared`
  (`winget install Cloudflare.cloudflared`). Para usarlo local no hace falta.

### Por qué Windows, y qué haría falta para Mac

El núcleo no depende del sistema operativo: el estado sale de los hooks de los propios agentes y
el contenido, de las transcripciones `.jsonl`. Lo atado a Win32 son dos archivos: `send.py`
(escribir en la consola de otro proceso, `AttachConsole` + `WriteConsoleInputW`) y `screen.py`
(leer su buffer, `ReadConsoleOutputCharacterW`).

En Mac o Linux esas dos piezas salen **más fáciles**, con tmux en el medio: `tmux send-keys -t
<pane>` en vez de attachearse a la consola ajena, `tmux capture-pane -p` en vez de leer el
buffer —y encima con scrollback y con la sesión sobreviviendo al cierre de la terminal, que en
Windows no existe—. La condición es que los agentes arranquen adentro de tmux, y el
direccionamiento pasa a ser por pane en vez de por PID. Sin tmux, en Mac queda peor que en
Windows: un PTY es de quien lo creó y no hay forma de leer la pantalla de otra terminal ni de
escribirle a un PID. **No está hecho: se podría.**

## Instalación

```powershell
git clone https://github.com/arielelevy/lienzo
cd lienzo\web
npm install
npm run build
cd ..
python install.py          # registra los hooks en ~/.claude/settings.json (con backup) y ~/.codex/hooks.json
.\lienzo-server.cmd        # http://127.0.0.1:7321
```

`install.py` hace merge, no pisa la configuración que ya tengas. `python install.py --uninstall`
saca los hooks. El estado vive en `%USERPROFILE%\.lienzo\` (eventos, permisos pendientes,
adjuntos, tarjetas); no toca AppData.

Codex pide confiar cada hook la primera vez que abre una sesión con `hooks.json` nuevo.

## Uso

### Tablero

Tres columnas: **Trabajo** (corriendo y terminó), **Te necesita** y **Muerta**. Una columna sin
tarjetas se colapsa a una tira vertical: click en la tira la abre, click en el título la cierra.
Cuando hay lugar, las tarjetas se reparten en hasta cuatro subcolumnas.

Una sesión pasa a *Te necesita* cuando pide permiso, cuando te hace una pregunta con opciones,
cuando su respuesta termina con una pregunta para vos, o cuando está libre sin ningún pedido. Un informe entregado sin pregunta la deja en
*Trabajo*.

`/` enfoca el buscador (agente, repo, rama, título, último pedido) y los chips filtran por agente.
Un click en una tarjeta **la elige**: se resaltan sus flechas y sus conexiones se leen en palabras
("Al terminar le manda su respuesta a lienzo · Coordinadora. Van 4 de 20."). El **doble click abre
el panel**. Esc cierra de a una capa: primero el panel, después la elección. Todo se alcanza con
el teclado: Tab recorre las tarjetas y las flechas los controles de la que tenga el foco.

### La tarjeta

Título (✎ para renombrarlo), último pedido, y **lo que el agente viene escribiendo en este turno**
—no el nombre de la herramienta—. Debajo, en qué anda: pasos, cuántos volvieron con error, los
últimos archivos que tocó, el último comando, los chips de sus conexiones y la sugerencia 💡 que
la terminal esté mostrando en ese momento.

La ★ marca la coordinadora del repo, una por repo: es a quien van los avisos "cuando termine". Una
sesión libre muestra un solo botón, "Darle trabajo". Si llegó al límite de uso y el aviso trae la
hora de vuelta, aparece "Continuar a las HH:MM", que deja programado el "Continuá"; si el turno se
cortó con un error de API ("The response stopped arriving"), aparece "↻ Reintentar". Con *Detalles
técnicos* apagado (menú ⋯) no se ven PID, hooks ni ids.

**Diálogos de la terminal**: los menús numerados de la TUI de Claude ("Switch model?", que abre
`/model`) no son un pedido de permiso y no disparan ningún hook: si nadie mira esa consola, la
sesión se queda esperando una tecla para siempre. El lienzo los lee de la pantalla y los muestra
en la tarjeta con sus opciones; elegir una teclea el número en su terminal.

### Contestar, aprobar, adjuntar

- **Contestarle**: la caja al pie del panel, Enter manda. Se le escribe en su terminal aunque esté
  oculta y sin robarte el foco. Más de 500 caracteres o varias líneas viajan como `.md` adjunto,
  que el agente lee por ruta. Si la terminal está mostrando una sugerencia, Tab la escribe.
- **Aprobar o denegar un permiso** sin ir a la terminal: la tarjeta muestra el comando con
  Permitir y Denegar. Nunca "permitir siempre". El pedido vence a los 60 segundos y ahí el prompt
  aparece en la terminal como siempre.
- **Elegir una opción cuando la sesión te pregunta**: `AskUserQuestion` llega por el mismo hook
  que un permiso, pero no es un permiso. La tarjeta muestra la pregunta y sus opciones con la
  descripción de cada una; se toca la que va (o se escribe otra cosa) y el agente sigue, sin
  pasar por la terminal.
- **Adjuntar imágenes y archivos**: se arrastran a la caja, o **se pega una captura con Ctrl+V**
  (sube con nombre por fecha y hora). Es la forma corta de mostrarle un error de pantalla.
- **Botones rápidos** "Continuá", "sí", "no" en la tarjeta, sólo cuando la sesión de verdad está
  esperando algo.
- La casilla **"avisarme cuando termine"** convierte el envío en delegación: manda el texto y crea
  la regla "cuando termine" hacia la coordinadora. Un gesto en vez de dos.
- **Copiar y pegar trabajo entre sesiones**: con una tarjeta elegida, Ctrl+C (o "Copiar trabajo"
  en su menú ⋯) arma un encargo con el último pedido, la última respuesta y los destacados de los
  últimos cinco turnos; Ctrl+V sobre otra tarjeta (o "Pegar trabajo") abre una vista previa
  editable. Hay un solo portapapeles para todo el tablero, y no se puede pegar en la misma sesión de
  origen ni en una que está esperando un permiso. Al enviar, la tarjeta destino **hereda el título
  con la marca "copycat"** y lleva la etiqueta ⧉ copycat en su fila de arriba; por defecto la de origen
  **recibe un Esc si está corriendo y pasa a "stopped"**, para que no hagan las dos lo mismo. La
  casilla **Duplicar** deja las dos trabajando: nadie se detiene, y cuando la copia termine le
  manda su informe a la de origen una sola vez. Es una conexión de un solo sentido a propósito:
  la ida y vuelta es el bucle A↔B que el server rechaza.
- **La llave "stopped"**: la etiqueta roja en la fila de arriba de la tarjeta. Prendida, la sesión
  **no recibe nada**: los envíos desde el tablero rebotan, las reglas "cuando termine" y las
  periódicas que la apuntan se saltean sin gastar el disparo, y no se le puede pegar trabajo. Al
  prenderse, el lienzo **avisa por su terminal a la coordinadora del repo y a toda sesión que
  tenga una conexión vigente con ella**, con el motivo (a qué copia se fue el trabajo, o que la
  detuvieron desde el tablero), para que no le manden nada ni cuenten con sus conexiones. Se
  prende desde el menú ⋯ ("Detener") o al pegar su trabajo en otra tarjeta; se apaga con un click
  en la etiqueta, desde el menú ("Habilitar"), o sola cuando llega un pedido nuevo por su terminal.

Las tres pestañas del panel: *Chat* (por turno: pedido, lo que fue diciendo, respuesta,
archivos, comandos, errores, preguntas), *Pantalla* (el buffer de la terminal) y *Conexiones* (lo
que recibió, lo que mandó y las conexiones activas).

### Conectar sesiones

Arrastrá una tarjeta **desde su fila de arriba, su título o el agarre ⇢** y soltala sobre otra. Se
escribe en una frase, que se interpreta mientras tipeás: "continuá a
las 16:00", "en 30 min seguí", "cada 30 min continuá hasta 6 veces", "cuando termine mandale a
MAPO", "cuando termine avisame". Enter confirma. Soltarla **sobre sí misma** es el bucle.

Cuatro modos: *Ahora* (le manda la última respuesta de la otra, con plantilla editable), *Cuando
termine* (su respuesta viaja al cerrar cada turno, una vez o hasta un tope), *Programar* (un texto
a una hora, o cada tanto con tope, y opcionalmente sólo si el destino está libre) y *Canal nativo*
sólo entre sesiones de Claude, que se hablan con `SendMessage` y se contestan entre ellas.

Toda regla tiene tope, y el server rechaza el bucle A↔B, la regla repetida y dos programadas al
mismo minuto hacia la misma sesión.

### Flechas

Cada conexión se dibuja entre las tarjetas: el último envío con ↪ (×N si hubo varios), las reglas
pendientes punteadas con ⏹, ⏰ o ↻, el canal nativo con una flecha doble. **La flecha de un envío
vive diez minutos** y después se va sola: el tablero muestra lo que está pasando ahora, y lo
mandado queda en la pestaña Conexiones. Un click en el glifo elige la flecha y explica qué hace;
el doble click abre el editor de la regla o los mensajes de ese par; Quitar vive adentro, con
confirmación. Un botón del menú las oculta, y en pantallas de menos de 900 px no se dibujan.

### Las dos automatizaciones

Las dos viven en el menú ⋯ y las dos vienen apagadas. Son lo único que corre sin que hagas nada, y
las dos tienen tope: un disparo por aviso.

- **Continuar solo tras límite de uso**: cuando una sesión avisa que llegó al límite con hora de
  vuelta, deja programada la regla "Continuar" un minuto después. Si borrás la regla, no la vuelve
  a crear.
- **Reintentar solo tras un error de API**: cuando un turno muere con "API Error: The response
  stopped arriving" (o un timeout, o un `overloaded_error`), programa "Continuar" diez segundos
  después —tiempo de sobra para quitarla si no querés—. Un límite de uso o un problema de crédito
  no entran acá: eso no se arregla reintentando.

## Delegar trabajo a varias sesiones

El flujo que le da sentido al tablero: abrís dos o tres terminales de Claude Code, y desde el
lienzo le mandás a cada una una tarea (texto largo, viaja como adjunto) con "avisarme cuando
termine" marcado. Cada consola trabaja en sus archivos, y su informe final llega solo a la
coordinadora al cerrar el turno. La coordinadora verifica, commitea y reparte la ronda
siguiente. Este repo se construyó así: la mayoría de los commits del 5 de septiembre los
hicieron otras sesiones de Claude a partir de encargos y revisiones repartidos desde el
propio lienzo, incluidos los planes de producto de `docs/plan-pm-2026-09-05.md` y
`docs/plan-pm-2026-09-06.md`, que salieron de probar el lienzo por la interfaz y repartir lo
encontrado a tres sesiones en paralelo.

Es manual a propósito: dos agentes vinculados en los dos sentidos se contestan hasta agotar
los créditos, por eso el server rechaza el bucle y cada regla tiene tope.

![Arrastrar una tarjeta sobre otra](docs/img/arrastre.png)

![Conectar escribiendo una frase](docs/img/conectar.png)

## Acceso desde el celular

**Opcional.** Para usar el lienzo en la propia PC no hace falta nada de esto: el server escucha en
`127.0.0.1:7321` y listo. El túnel es sólo si querés abrir el tablero desde afuera —tiene sentido
si el lienzo corre en una máquina que se queda trabajando en casa—.

```powershell
.\lienzo-server.cmd --remote
```

En la PC, botón **Acceso remoto**: genera una clave TOTP y muestra dos QR. El primero se
escanea desde adentro de Microsoft Authenticator (Agregar cuenta → Otra cuenta); el segundo,
con la cámara, abre el tablero en el teléfono. Desde afuera se entra con el código de 6
dígitos; en la PC no se pide login nunca.

Por debajo: túnel `cloudflared` con TLS (sin abrir puertos ni tocar el router), cookie de
sesión de 7 días, cinco intentos fallidos bloquean el login 15 minutos, y el server sólo
escucha en `127.0.0.1`. La URL del túnel rápido cambia en cada arranque; para una URL fija
hace falta un túnel con nombre y un dominio en Cloudflare.

![En el celular](docs/img/celular.png)

## API

Todo en `http://127.0.0.1:7321`, JSON. Las escrituras exigen el header `X-Lienzo: 1`; por el
túnel, además la cookie de sesión.

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/sessions` | todas las tarjetas, con `alive` recalculado |
| GET | `/sessions/<sid>/turns?n=10` | turnos completos de la transcripción, con las herramientas (el tablero ya no los muestra: la pestaña Chat usa `digest`) |
| GET | `/sessions/<sid>/digest?n=10` | destacados por turno |
| GET | `/sessions/<sid>/screen` | texto visible de la terminal |
| GET | `/sessions/<sid>/connections` | links y reglas donde esa sesión es origen o destino, con la otra punta resuelta a `{session_id, name}`; lo que mandó el usuario viene como "vos (lienzo)" |
| POST | `/sessions/<sid>/send` | `{text, attachments}`; con `from` y `link_to` registra el envío entre sesiones, con `native` lo marca como canal nativo. Con `from` y `copycat: true` es "pegar trabajo": la tarjeta hereda el título con la marca copycat (`copycat_of`) y, salvo `stop_origin: false`, la de origen recibe un Esc si corre y queda `stopped_by`; la respuesta trae `interrupted` |
| POST | `/sessions/<sid>/interrupt` | un Esc en su terminal: corta el turno que corre. 409 si la sesión no está corriendo (en una quieta el Esc borra la caja) |
| POST | `/sessions/<sid>/dialog` | `{choice: n}`; elige una opción del diálogo de la TUI que la tarjeta está mostrando (se teclea el número, sin Enter). 409 si esa sesión no está mostrando esa opción |
| POST | `/sessions/<sid>/attach` | sube un archivo (header `X-Filename`), devuelve la ruta |
| PUT | `/sessions/<sid>/title` | `{title}`; el título pasa a ser del usuario y no se recalcula |
| PUT | `/sessions/<sid>/stopped` | `{on: true\|false}`; la llave. Prender: Esc si corre, `stopped_by: "user"`, aviso a la coordinadora y a las conectadas por regla vigente (la respuesta trae `interrupted` y `notified`). Apagar: vuelve a recibir. Mientras está prendida, `/send`, `/dialog` e `/interrupt` devuelven 409 y las reglas hacia ella se saltean |
| PUT | `/sessions/<sid>/coordinator` | `{on: true\|false}`; una coordinadora por repo, prender una apaga la anterior |
| DELETE | `/sessions/<sid>` | saca la tarjeta |
| GET | `/links` | envíos hechos; `kind` es `send`, `rule`, `native` o `user` |
| GET | `/rules` | conexiones pendientes y cumplidas |
| POST | `/rules` | `{kind: on_stop\|at, from, to, text, at, repeat, max_fires}`; una `at` acepta además `every_s` (segundos, mínimo 60; periódica) y `skip_busy`; con `every_s`, `max_fires` vale 5 si no viene y `skip_busy` true; 409 si arma un bucle, si ya existe, o si una `at` cae a ±2 min de otra hacia la misma sesión (la respuesta trae `rule_id` y `replace: true`; repetir con `replace: true` en el body la reemplaza) |
| PUT | `/rules/<id>` | edita texto, hora (`at`), `repeat`, `max_fires`, y en una `at` también `every_s` (null la vuelve de un disparo) y `skip_busy`; reprogramar una `at` cumplida la reactiva |
| DELETE | `/links/<id>`, `/rules/<id>` | quita la flecha o la conexión |
| GET | `/pending` | permisos esperando respuesta |
| POST | `/pending/<id>` | `{decision: allow\|deny}` |
| GET | `/config` | `{auto_continue, auto_retry}` |
| PUT | `/config` | `{auto_continue: true\|false, auto_retry: true\|false}`; sólo esas claves, el resto de `config.json` no se toca |
| GET | `/events` | SSE con cada cambio de sesiones, pendientes, links, reglas |
| POST | `/rescan` | barrido de procesos ahora |
| GET | `/auth`, POST `/setup`, `/login`, `/logout`, GET `/enroll` | acceso remoto |

## Estructura

```
lienzo/
  hook.py          hook único para los dos agentes; espera de permisos con nonce
  procinfo.py      ctypes mínimo compartido: padre, imagen, vivo, agente
  transcripts.py   lectura por la cola de las transcripciones, digest por turno, hora del límite de uso, error de API reintentable
  procs.py         liveness, barrido de procesos, cwd por PEB
  send.py          inyección de teclas por PID; `--key escape` manda un Esc solo (interrumpir)
  screen.py        lectura del buffer de consola por PID: sugerencias y diálogos de la TUI
  auth.py          TOTP (RFC 6238), cookies, freno de intentos
  state.py         estado compartido: listas JSON (links, reglas), config, broadcast SSE
  sessions.py      registro de sesiones, máquina de estados, eventos de hooks, barrido, envío
  rules.py         reglas "cuando termine" y "a las HH:MM" (una vez o cada every_s con tope), las dos reglas automáticas "Continuar" (límite de uso, error de API), disparo y purga
  server.py        handler HTTP + SSE, túnel, arranque de los hilos
web/               interfaz (Vite + React + TypeScript); `npm run build` deja web/dist
  src/arrows-geometry.ts   geometría de las flechas y etiquetas de período, funciones puras con tests propios
  src/nl.ts                parser de frases ("cada 30 min continuá hasta 6 veces"), con tests propios
  src/names.ts             nombres cortos, etiquetas de reglas y texto plano, compartidos por tarjeta, panel y flechas
  src/hooks/               datos por SSE, avisos del navegador y flags guardados en el navegador
tests/             pytest: transcripciones reales, procesos vivos y la máquina de estados del server
install.py         alta y baja de los hooks
lienzo-server.cmd  arranque
```

```powershell
python -m pytest tests -q                                   # 132 tests
python -m ruff check lienzo tests install.py                # lint
python -m black lienzo tests install.py                     # formato
cd web; npm run build                                       # tsc + vite
cd web; npm run lint                                        # eslint (typescript-eslint + react-hooks); las reglas del compilador de React quedan como advertencia
cd web; node --experimental-strip-types src/arrows-geometry.test.ts   # 37 tests de las flechas
cd web; node --experimental-strip-types src/nl.test.ts                # 79 aserciones del parser de frases
cd web; npm run test:ui                                               # 35 pruebas de interfaz en el navegador (Playwright)
```

Las de interfaz miden el tablero pintado (alturas, subcolumnas, flechas, scroll, contraste) contra
un tablero fijo que interceptan, más una prueba de humo con los datos de verdad; piden el server
andando en el 7321 —no lo arrancan ni lo reinician—, la primera vez bajan Chromium solas y
`LIENZO_URL=http://otro:puerto` las apunta a otro lado.

## Qué es cada archivo de estado

```
~/.lienzo/
  events/        eventos de hooks (el server los consume y borra)
  pending/       permisos esperando respuesta
  answers/       respuestas a permisos
  adjuntos/      archivos y textos largos enviados a las sesiones
  sessions/      una tarjeta por sesión
  links.json     envíos hechos (flechas y pestaña Conexiones)
  rules.json     conexiones (cuando termine, a una hora), vigentes y cumplidas
  config.json    auto_continue, y lo que comparte con hook.py (espera de permisos, ejemplos)
  auth.json      clave TOTP del acceso remoto
  lienzo.log     una línea por hecho: fecha, etiqueta (envio, regla, sesion, permiso, error…) y mensaje; en consola sólo la hora, y los tracebacks en una línea
```

## Limitaciones conocidas

- La inyección escribe en la misma caja que tu teclado: si estás tipeando en esa terminal,
  los dos textos se mezclan. La tarjeta avisa cuando detecta tipeo; mandale a sesiones que no
  estés usando a mano en ese momento.
- El stream de eventos (SSE) no pasa por el túnel rápido de Cloudflare; desde el celular el
  tablero se actualiza por sondeo cada 4 segundos.
- Las sugerencias de prompt que muestra Claude Code no quedan en ningún archivo; se leen
  del buffer de la terminal cuando la sesión está ociosa. Si vos estás tipeando en esa
  terminal, lo que escribís se ve como sugerencia hasta que lo mandás.
- Los nombres internos con que las sesiones de Claude se ven entre sí (`lienzo-b7`) no se
  pueden mapear al `session_id` desde afuera; el canal nativo lo resuelve la propia sesión
  con `ListAgents`.
- Una sesión cuya terminal se cerró (el proceso sigue, el shell padre murió) se muestra pero
  no acepta mensajes: no hay consola donde escribir.
- Las flechas no se dibujan en pantallas de menos de 900 px; ahí el tablero es una columna
  por vez con selector arriba.

## Licencia

MIT. La lista de palabras `lienzo/eff_large_wordlist.txt` es de la
[EFF](https://www.eff.org/dice), licencia CC BY 3.0.
