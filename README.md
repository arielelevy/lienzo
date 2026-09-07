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

Una sesión pasa a *Te necesita* cuando pide permiso, cuando su respuesta termina con una pregunta
para vos, o cuando está libre sin ningún pedido. Un informe entregado sin pregunta la deja en
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
hora de vuelta, aparece "Continuar a las HH:MM", que deja programado el "Continuá". Con *Detalles
técnicos* apagado (menú ⋯) no se ven PID, hooks ni ids.

### Contestar, aprobar, adjuntar

- **Contestarle**: la caja al pie del panel, Enter manda. Se le escribe en su terminal aunque esté
  oculta y sin robarte el foco. Más de 500 caracteres o varias líneas viajan como `.md` adjunto,
  que el agente lee por ruta. Si la terminal está mostrando una sugerencia, Tab la escribe.
- **Aprobar o denegar un permiso** sin ir a la terminal: la tarjeta muestra el comando con
  Permitir y Denegar. Nunca "permitir siempre". El pedido vence a los 60 segundos y ahí el prompt
  aparece en la terminal como siempre.
- **Adjuntar imágenes y archivos**: se arrastran a la caja, o **se pega una captura con Ctrl+V**
  (sube con nombre por fecha y hora). Es la forma corta de mostrarle un error de pantalla.
- **Botones rápidos** "Continuá", "sí", "no" en la tarjeta, sólo cuando la sesión de verdad está
  esperando algo.
- La casilla **"avisarme cuando termine"** convierte el envío en delegación: manda el texto y crea
  la regla "cuando termine" hacia la coordinadora. Un gesto en vez de dos.

Las cuatro pestañas del panel: *Destacados* (por turno: pedido, lo que fue diciendo, respuesta,
archivos, comandos, errores, preguntas), *Conversación* (la transcripción, con las herramientas
plegadas), *Pantalla* (el buffer de la terminal) y *Conexiones* (lo que recibió, lo que mandó y
las conexiones activas).

### Conectar sesiones

Arrastrá una tarjeta **desde su fila de arriba, su título o el agarre ⇢** y soltala sobre otra (o
"Conectar…" en el panel). Se escribe en una frase, que se interpreta mientras tipeás: "continuá a
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

### Continuar solo tras límite de uso

En el menú ⋯, apagado por defecto. Prendido, cuando una sesión avisa que llegó al límite con hora
de vuelta, deja programada la regla "Continuar" un minuto después, una sola vez por aviso; si
borrás la regla, no la vuelve a crear. Es la única automatización que corre sin que hagas nada.

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
| GET | `/sessions/<sid>/turns?n=10` | turnos de la transcripción, para la conversación |
| GET | `/sessions/<sid>/digest?n=10` | destacados por turno |
| GET | `/sessions/<sid>/screen` | texto visible de la terminal |
| GET | `/sessions/<sid>/connections` | links y reglas donde esa sesión es origen o destino, con la otra punta resuelta a `{session_id, name}`; lo que mandó el usuario viene como "vos (lienzo)" |
| POST | `/sessions/<sid>/send` | `{text, attachments}`; con `from` y `link_to` registra el envío entre sesiones, con `native` lo marca como canal nativo |
| POST | `/sessions/<sid>/attach` | sube un archivo (header `X-Filename`), devuelve la ruta |
| PUT | `/sessions/<sid>/title` | `{title}`; el título pasa a ser del usuario y no se recalcula |
| PUT | `/sessions/<sid>/coordinator` | `{on: true\|false}`; una coordinadora por repo, prender una apaga la anterior |
| DELETE | `/sessions/<sid>` | saca la tarjeta |
| GET | `/links` | envíos hechos; `kind` es `send`, `rule`, `native` o `user` |
| GET | `/rules` | conexiones pendientes y cumplidas |
| POST | `/rules` | `{kind: on_stop\|at, from, to, text, at, repeat, max_fires}`; una `at` acepta además `every_s` (segundos, mínimo 60; periódica) y `skip_busy`; con `every_s`, `max_fires` vale 5 si no viene y `skip_busy` true; 409 si arma un bucle, si ya existe, o si una `at` cae a ±2 min de otra hacia la misma sesión (la respuesta trae `rule_id` y `replace: true`; repetir con `replace: true` en el body la reemplaza) |
| PUT | `/rules/<id>` | edita texto, hora (`at`), `repeat`, `max_fires`, y en una `at` también `every_s` (null la vuelve de un disparo) y `skip_busy`; reprogramar una `at` cumplida la reactiva |
| DELETE | `/links/<id>`, `/rules/<id>` | quita la flecha o la conexión |
| GET | `/pending` | permisos esperando respuesta |
| POST | `/pending/<id>` | `{decision: allow\|deny}` |
| GET | `/config` | `{auto_continue}` |
| PUT | `/config` | `{auto_continue: true\|false}`; sólo esa clave, el resto de `config.json` no se toca |
| GET | `/events` | SSE con cada cambio de sesiones, pendientes, links, reglas |
| POST | `/rescan` | barrido de procesos ahora |
| GET | `/auth`, POST `/setup`, `/login`, `/logout`, GET `/enroll` | acceso remoto |

## Estructura

```
lienzo/
  hook.py          hook único para los dos agentes; espera de permisos con nonce
  procinfo.py      ctypes mínimo compartido: padre, imagen, vivo, agente
  transcripts.py   lectura por la cola de las transcripciones, digest por turno, hora del límite de uso
  procs.py         liveness, barrido de procesos, cwd por PEB
  send.py          inyección de teclas por PID
  screen.py        lectura del buffer de consola por PID
  auth.py          TOTP (RFC 6238), cookies, freno de intentos
  state.py         estado compartido: listas JSON (links, reglas), config, broadcast SSE
  sessions.py      registro de sesiones, máquina de estados, eventos de hooks, barrido, envío
  rules.py         reglas "cuando termine" y "a las HH:MM" (una vez o cada every_s con tope), regla automática "Continuar", disparo y purga
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
python -m pytest tests -q                                   # 97 tests
python -m ruff check lienzo tests install.py                # lint
python -m black lienzo tests install.py                     # formato
cd web; node --experimental-strip-types src/arrows-geometry.test.ts   # 37 tests de las flechas
cd web; node --experimental-strip-types src/nl.test.ts                # 79 aserciones del parser de frases
cd web; npm run test:ui                                               # 28 pruebas de interfaz en el navegador (Playwright)
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
