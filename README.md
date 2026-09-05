# Lienzo

Tablero para las sesiones de **Claude Code** y **Codex CLI** que corren en terminales de
Windows: la integrada de VS Code, Windows Terminal, una PowerShell o un cmd sueltos. Una
tarjeta por sesión, agrupadas por estado (corriendo, te necesita, terminó, muerta), con la
conversación a un click, una caja para contestarles, aprobación de permisos sin ir a la
terminal, conexiones entre sesiones y acceso desde el celular con Microsoft Authenticator.

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

Además: reenvío de la respuesta de una sesión a otra con plantilla (arrastrando una tarjeta
sobre otra, o desde el botón), con una flecha entre las tarjetas por cada reenvío, y una
pestaña que muestra el texto visible de la terminal leído del buffer de consola.

![Panel de una sesión](docs/img/panel.png)

## Requisitos

- Windows 10/11. Todo lo de consola es Win32 (`ctypes`), no hay versión para Linux o Mac.
- Python 3.12 o más nuevo, sólo biblioteca estándar. Sin `psutil`, sin frameworks.
- Node 20 o más nuevo para compilar la interfaz (Vite + React + TypeScript).
- Claude Code 2.1 o más nuevo, Codex CLI 0.153 o más nuevo, o los dos.
- Para el acceso remoto: `cloudflared` (`winget install Cloudflare.cloudflared`).

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

- **Tablero**: cuatro columnas por estado; las vacías se colapsan. Click en una tarjeta abre
  el panel con *Destacados* (por turno: pedido, respuesta, archivos tocados, comandos,
  errores, preguntas, mensajes a otras sesiones), *Conversación* (la transcripción completa,
  con las herramientas colapsadas), *Pantalla* (el buffer de la terminal) y *Conexiones*
  (qué recibió, qué mandó, y las conexiones activas con su estado).
- **Tarjeta**: título (el que Claude le pone a la sesión, o la primera línea del pedido),
  último pedido, última respuesta, errores de límite de uso en rojo, un chip
  "✓ informe de X hace N min" cuando otra sesión le mandó algo, y la sugerencia 💡 que la
  terminal esté mostrando en ese momento.
- **Enviar**: caja de texto al pie del panel. Enter manda. Más de 500 caracteres o varias
  líneas viajan como un `.md` adjunto y el agente lo lee por ruta. Se pueden arrastrar
  archivos e imágenes. Si la terminal muestra una sugerencia, aparece en gris en la caja y
  Tab la escribe, igual que en Claude Code.
- **Permisos**: cuando una sesión pide permiso, la tarjeta muestra el comando y dos botones,
  Permitir y Denegar. Nunca "permitir siempre".
- **Conectar sesiones**: arrastrá una tarjeta y soltala sobre otra (o "Conectar…" en el
  panel). Se abre un diálogo chico donde podés escribirlo en una frase, y se interpreta
  mientras tipeás: "continuá a las 16:00", "en 30 min seguí", "cuando termine mandale a
  MAPO", "cada vez que termine pasale a Teorema hasta 3 veces". Enter confirma. Cuatro modos:
  - *Ahora*: manda la última respuesta de A a B, con plantilla editable
    (`{repo} {agente} {titulo} {pedido} {respuesta}`).
  - *Cuando A termine*: al cerrar cada turno, su respuesta va a B. Una vez o hasta un tope.
  - *A una hora*: un texto fijo (por defecto "Continuá") a una sesión, que puede ser la
    misma. Es el "seguí" para cuando vuelven los créditos.
  - *Canal nativo* (sólo Claude ↔ Claude): A ubica a B con `ListAgents` y le habla con
    `SendMessage`; los mensajes llegan aunque B esté trabajando y se responden por el mismo
    canal. Vos les das el tema; ellas conversan.

  Cada reenvío dibuja una flecha entre las tarjetas; las conexiones pendientes se ven
  punteadas con ⏹ o ⏰, el canal nativo con una flecha doble gruesa. Las flechas pasan por
  el canal entre columnas, se agrupan por par con un contador, las viejas se atenúan, y al
  pasar el mouse sobre una tarjeta se resaltan las suyas. Un botón las oculta. Esc cancela.

  El server rechaza una regla "cuando termine" que cierre un bucle A↔B, y no la dispara si
  el turno terminó con error o con una pregunta para vos.

## Delegar trabajo a varias sesiones

El flujo que le da sentido al tablero: abrís dos o tres terminales de Claude Code, y desde el
lienzo le mandás a cada una una tarea (texto largo, viaja como adjunto) conectada "cuando
termine" hacia la sesión que coordina. Cada consola trabaja en sus archivos, y su informe
final llega solo a la coordinadora al cerrar el turno. La coordinadora verifica, commitea y
reparte la ronda siguiente. Este repo se construyó así: la mitad de los commits del 5 de
septiembre los hicieron otras tres sesiones de Claude a partir de encargos y revisiones
repartidos desde el propio lienzo. Es manual a propósito: dos agentes vinculados en los dos sentidos se
  contestan hasta agotar los créditos.

![Arrastrar una tarjeta sobre otra](docs/img/arrastre.png)

![Conectar escribiendo una frase](docs/img/conectar.png)

## Acceso desde el celular

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

## Estructura

```
lienzo/
  hook.py          hook único para los dos agentes; espera de permisos con nonce
  procinfo.py      ctypes mínimo compartido: padre, imagen, vivo, agente
  transcripts.py   lectura por la cola de las transcripciones y digest por turno
  procs.py         liveness, barrido de procesos, cwd por PEB
  send.py          inyección de teclas por PID
  screen.py        lectura del buffer de consola por PID
  auth.py          TOTP (RFC 6238), cookies, freno de intentos
  server.py        watcher, registro, máquina de estados, reglas, HTTP + SSE, túnel
web/               interfaz (Vite + React + TypeScript); `npm run build` deja web/dist
tests/             pytest contra transcripciones reales y procesos vivos
install.py         alta y baja de los hooks
lienzo-server.cmd  arranque
```

```powershell
python -m pytest tests -q      # 12 tests
```

## Qué es cada archivo de estado

```
~/.lienzo/
  events/        eventos de hooks (el server los consume y borra)
  pending/       permisos esperando respuesta
  answers/       respuestas a permisos
  adjuntos/      archivos y textos largos enviados a las sesiones
  sessions/      una tarjeta por sesión
  links.json     reenvíos hechos (flechas)
  rules.json     conexiones pendientes (cuando termine, a una hora)
  auth.json      clave TOTP del acceso remoto
  lienzo.log
```

## Limitaciones conocidas

- La inyección escribe en la misma caja que tu teclado: si estás tipeando en esa terminal,
  los dos textos se mezclan. Mandale a sesiones que no estés usando a mano en ese momento.
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

## Licencia

MIT. La lista de palabras `lienzo/eff_large_wordlist.txt` es de la
[EFF](https://www.eff.org/dice), licencia CC BY 3.0.
