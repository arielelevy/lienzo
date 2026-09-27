# Plan: lienzo multi-PC (2026-09-26)

Que el lienzo funcione en 2 a 4 PCs de la misma LAN: si se levanta en una, se ve esa; si se
levanta en dos, cada tablero muestra las tarjetas de las dos y desde cualquiera se contesta,
se aprueba, se conecta y se coordina. En el front, una tira de PCs arriba del tablero.

Decisiones de Ariel (2026-09-26):

- **Red: LAN.** Sin Tailscale ni nada hospedado.
- **Coordinadora: una por repo en toda la federación**, salvo que se la separe explícitamente
  por PC.
- **Escala: 2 a 4 PCs como máximo.**
- **El skill `lienzo` se actualiza** como parte del trabajo.

---

## 1. Por qué P2P por HTTP y no Redis

Cada server ya tiene lo que hace falta para federarse: una API JSON completa y un stream de
eventos (`broadcast` en `state.py`, servido por `/events`). Federar es que cada server se
suscriba al stream del otro y le reenvíe los comandos.

Redis no aporta:

- **No tiene server nativo en Windows** (Memurai, WSL o Docker). Rompe el "solo stdlib, sin
  instalar nada" del proyecto.
- **Pone un punto central**: si se cae Redis, o la PC que lo corre, se cae la federación. Con P2P,
  si se apaga la notebook, la otra PC sigue exactamente como hoy.
- **No hay nada que persistir en el medio**: el estado de cada PC vive en su `~/.lienzo`; lo que
  viaja son eventos y comandos, sin cola.
- `DISENO.es.md` §7.6.3 ya llegó a lo mismo: "Redis no hace falta".

Con 4 PCs como máximo son 6 enlaces en malla completa: no hace falta hub.

El transporte queda detrás de una interfaz en `lienzo/federation.py`, para que un broker
(Redis pub/sub, Azure Web PubSub) se pueda enchufar después sin tocar el resto, si alguna vez
se pasa de 4 PCs o se sale de la LAN.

## 2. El principio: cada PC es dueña de lo suyo

La inyección de teclas (`WriteConsoleInputW`), la lectura de pantalla, los hooks, los permisos
y los recursos (memoria, CPU, temperatura) son de la máquina donde corre el proceso. **Nunca se
replican: se le piden a la PC dueña.**

```
PC-A lienzo :7321 (UI, solo 127.0.0.1)            PC-B lienzo :7321
      │  listener de peers :7322 ◀────────────────▶ listener de peers :7322
      │  (bind a la IP de LAN, solo /peer/*, firmado con HMAC)
      ├─ espejo en memoria de las sesiones de B     ├─ espejo de A
      └─ enruta send/pending/attach/launch → B      └─ ídem
```

- **Con una sola PC no cambia nada**: sin peers emparejados no se abre el 7322 ni aparece la
  tira de PCs.
- **Con dos o más**, cada tablero muestra todas las tarjetas, y todo se opera desde cualquiera.

## 3. Piezas

### 3.1 Identidad y emparejamiento

- `~/.lienzo/peer.json`: `pc_id` (aleatorio, estable), nombre ("oficina", "notebook") y color.
- Emparejar reusa el generador de frases de `auth.py` (wordlist EFF): la PC A muestra seis
  palabras, en la B se pegan, y de ahí sale una clave compartida por par, guardada en
  `~/.lienzo/peers.json` (con `pc_id`, nombre, última IP vista, `launch_roots`).
- Cada request entre peers va firmada: HMAC(clave, método + ruta + cuerpo + timestamp + nonce),
  con ventana de ±30 s y registro de nonces contra replay.
- Revocar un peer es borrarlo de `peers.json` (o desde la UI).
- Tope de 4 peers en el código.

### 3.2 Red (LAN)

- La UI sigue en `127.0.0.1:7321`, sin cambios.
- Se suma un segundo listener en `:7322`, bind a la IP de LAN (nunca `0.0.0.0`), que solo
  atiende `/peer/*`.
- **Descubrimiento por beacon UDP** en la LAN (stdlib `socket`, cada 10 s): cada PC anuncia
  `pc_id`, nombre y puerto. Solo se aceptan peers ya emparejados. Como se identifican por
  `pc_id` y no por IP, si el DHCP cambia la IP el beacon la actualiza sola.
- **Firewall**: `install.py --peer` agrega la regla de Windows para el 7322 **solo en el perfil
  Privado** (pide admin una vez). En una red pública el puerto no escucha.

### 3.3 Espejo (lo de solo lectura)

- Cada server abre un SSE saliente (`http.client`) contra `/peer/events` de cada peer y arma un
  espejo en memoria: sesiones, pendientes, links y reglas, marcadas con su `pc`.
- Al (re)conectar pide el snapshot completo. No se persiste.
- `GET /sessions` devuelve lo local más lo espejado, con `pc` y `pc_alive`.
- `digest`, `turns`, `screen` y `connections` de una sesión remota se piden a su dueña bajo
  demanda.
- `/sessions` suma `transcript_bytes` y `model`, para que nadie tenga que leer un
  `transcript_path` que está en otro disco.

### 3.4 Enrutado de comandos

- Los `session_id` son UUID globales. El server mantiene `sid → pc` y reenvía
  transparentemente: `send`, `interrupt`, `dialog`, `title`, `stopped`, `DELETE`,
  `POST /pending/<id>`, `attach`. El front sigue llamando a `/sessions/<sid>/...`.
- **Adjuntos**: tienen que quedar en el disco de la PC dueña, porque el agente los lee por ruta.
  Los bytes viajan proxeados y la ruta que se inserta es la de destino.
- **Permisos**: el pedido vence a los 60 s; la latencia de LAN no cambia nada.

### 3.5 Reglas y conexiones entre PCs

- Una regla `on_stop` vive en la PC del `from` (donde ocurre el Stop). `fire_rule` ya llama a
  `send_to_session`, que pasa a enrutar.
- **El chequeo de bucle A↔B pasa a ser global**: antes de guardar, se le pregunta a la PC del
  `to` si tiene la inversa. La carrera de crear las dos a la vez en PCs distintas se resuelve con
  un lock liviano en la PC de menor `pc_id`.
- Regla repetida y "dos programadas al mismo minuto hacia la misma sesión": el chequeo lo hace la
  PC dueña del destino.
- **El canal nativo Claude a Claude no cruza PCs** (`ListAgents` es de la máquina). La UI no
  ofrece la flecha doble entre tarjetas de PCs distintas.

### 3.6 Coordinadora federada

- **Por defecto, una ★ por repo en toda la federación**: los informes de los frentes de cualquier
  PC le llegan a ella. Prender una apaga la anterior en cualquier PC.
- **Separarla, explícito**: `PUT /sessions/<sid>/coordinator {on: true, scope: "pc"}`. Ese repo,
  en esa PC, pasa a tener su propia ★ y las reglas de esa PC apuntan a ella. En la UI: menú ⋯ →
  "Coordinadora solo de esta PC".
- **Identidad del repo**: el remote `origin` normalizado (sin `.git`, sin credenciales,
  minúsculas en el host). Si no hay remote, el nombre de la carpeta. El mismo repo puede estar
  en rutas distintas en cada PC, y dos carpetas con el mismo nombre pueden ser repos distintos.

### 3.7 Lanzar sesiones en otra PC

Hoy la coordinadora lanza con `Start-Process explorer.exe`, que solo sirve en su máquina.

- `POST /sessions/launch {pc, cwd, title, agent}`: la PC dueña escribe el `.cmd` (cp1252, CRLF,
  `cd /d`, `title`, `claude.exe` por ruta absoluta) y lo lanza por `explorer.exe`, igual que hoy.
- Seguridad: `cwd` tiene que caer dentro de `launch_roots` de esa PC (ej. `D:\Repos`), el
  ejecutable es fijo por `agent` (claude, codex, pi, coda) y el título no se interpreta.
- La respuesta trae el `pid` apenas aparece la tarjeta (con un rescan en el medio), para que la
  coordinadora le ponga título y regla.

### 3.8 Salud por PC

- `GET /peer/health` en cada server: memoria libre de Windows, CPU (`\Processor(_Total)\%
  Processor Time`), temperatura (`\_TZ.THRM`, deciKelvin), cantidad de sesiones.
- La tira de PCs lo muestra en cada chip.
- El `monitor.ps1` del skill corre en cada PC y avisa a la coordinadora aunque esté en otra PC:
  el send se enruta solo.

### 3.9 Front: la tira de PCs

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [Todas 8]  [● oficina 5 · 3,4 GB · 68 °C]  [● notebook 3 · 2,1 GB · 71 °C] │
├──────────────────────────────────────────────────────────────────────────┤
│  Trabajo          │  Te necesita        │  Muerta                        │
│  ▌oficina card    │  ▌notebook card     │                                │
```

- Aparece solo con al menos un peer emparejado.
- Cada chip filtra; click en el activo vuelve a *Todas*. Colapsada, queda una línea con los
  puntos de estado.
- Tarjetas con borde o badge del color de su PC.
- Flechas entre PCs igual que ahora: es un solo tablero.
- Peer caído: sus tarjetas grises con "sin conexión hace X", controles deshabilitados, y el chip
  en ○.
- El filtro de PC vive en el navegador, como las posiciones corridas.

## 4. Seguridad: lo que cambia

Hoy el server no escucha más allá de loopback. Con esto, un peer emparejado puede teclear en
los agentes de la otra PC y lanzar sesiones nuevas. Mismo nivel de riesgo que el acceso remoto,
mitigado igual:

- Listener aparte que solo atiende `/peer/*`; la UI sigue en 127.0.0.1.
- Bind a la IP de LAN, nunca `0.0.0.0`; firewall solo en perfil Privado.
- Toda request firmada, con timestamp y nonce.
- `launch` restringido a `launch_roots` y a ejecutables fijos.
- Peers revocables; tope de 4.
- Cada request de un peer va a `lienzo.log` con la etiqueta `peer`.

## 5. Varias PCs, varios árboles: cómo se commitea

La regla actual ("nadie commitea salvo la coordinadora: hay un solo árbol") se vuelve **un solo
commiter por árbol**:

- En la PC remota los frentes no commitean. Al cerrar la ronda, la coordinadora le pide a uno de
  ellos, la **delegada de esa PC**, que commitee todo en la rama `ronda-<N>/<pc>` y haga push.
- La coordinadora hace fetch, verifica en un `git worktree` local (ruff, pruebas, archivos fuera
  de cada frente) y mergea. "Verificar contra el árbol, no contra el informe" sigue valiendo.
- El repo tiene que estar clonado en la otra PC; el encargo común arranca con `git pull`.

## 6. Pruebas

- **Dos instancias en la misma PC**, con `LIENZO_HOME` distinto y puertos distintos (7321/7322 y
  7331/7332), simulan dos PCs: espejo, enrutado, reglas, bucle global, coordinadora, salud.
- pytest para: firma HMAC y replay, espejo con reconexión, enrutado de cada comando, bucle global
  con carrera, identidad de repo por remote, `launch_roots`, tope de 4.
- Playwright para la tira de PCs, el filtro, las tarjetas grises y las flechas entre PCs, contra
  un tablero fijo interceptado.
- **Prueba real con la notebook**, con terminales de prueba, nunca sesiones de trabajo: inyección,
  permiso, adjunto, launch y una regla `on_stop` cruzada.

---

## Checklist

### F0 · Base, sin cambio visible

- [x] `LIENZO_HOME` configurable (hoy `~/.lienzo` fijo), leído por server, hook e `install.py`
- [x] `peer.json` con `pc_id`, nombre y color, creado al arrancar si no existe
- [x] Campo `pc` en cada sesión, link, regla y pendiente
- [x] Identidad de repo por remote `origin` normalizado, con fallback a la carpeta
- [x] `transcript_bytes` y `model` en `GET /sessions`
- [x] `lienzo/federation.py` con la interfaz de transporte (vacía)
- [x] Tests verdes; dos instancias en una PC arrancan sin pisarse  *(`test_peer_server.py`: dos procesos reales en esta PC, con firma, espejo y enrutado)*

### F1 · Ver la otra PC

- [x] Listener `:7322` con bind a la IP de LAN, solo `/peer/*`
- [x] Emparejamiento por frase de seis palabras; `peers.json`; revocar
- [x] Firma HMAC con timestamp y nonce, y rechazo de replay
- [x] Beacon UDP en la LAN; actualización de IP por `pc_id`
- [x] Todas las PCs de la LAN se ven solas, emparejadas o no (anuncio sin firma, `GET /peers/lan`, «En esta red» en la pantalla, `coordinar.lan()` en el skill); `lienzo-server.cmd` arranca con `--peers`
- [ ] `install.py --peer`: regla de firewall en perfil Privado  *(código y `--dry-run` probados; la regla real no se corrió)*
- [x] `/peer/events` y cliente SSE saliente con reconexión y snapshot
- [x] Espejo en memoria; `/sessions` mezcla local y remoto con `pc_alive`  *(sin campo `pc_alive`: la PC caída sale del `alive` de `GET /peers`)*
- [x] `digest`, `turns`, `screen`, `connections` remotos bajo demanda
- [x] `GET /peer/health` (memoria, CPU, temperatura, sesiones)
- [x] Tope de 4 peers
- [ ] **Cierre:** desde A se ven en vivo las tarjetas y la salud de B  *(probado entre dos procesos en esta PC; falta con la notebook)*

### F2 · Operar la otra PC

- [x] Mapa `sid → pc` y enrutado transparente
- [x] `send`, `interrupt`, `dialog`, `title`, `stopped`, `DELETE`
- [x] `POST /pending/<id>` remoto
- [x] `attach` con bytes proxeados y ruta de destino
- [x] Errores del peer (409, 404, caído) devueltos tal cual al front
- [x] Log `peer` de cada request recibida
- [ ] **Cierre:** se aprueba un permiso de B desde el tablero de A  *(probado entre dos procesos en esta PC; falta con la notebook)*

### F3 · Coordinar entre PCs

- [x] Reglas `on_stop` y `at` con `to` en otra PC
- [x] Chequeo de bucle A↔B global, con lock en la PC de menor `pc_id`
- [x] Regla repetida y programadas a ±2 min chequeadas en la PC del destino
- [x] Coordinadora federada por repo
- [x] `scope: "pc"` para separarla, en API y en el menú ⋯
- [x] Sin flecha doble (canal nativo) entre PCs distintas
- [x] `POST /sessions/launch` con `launch_roots` y ejecutable fijo por agente
- [ ] **Cierre:** desde la ★ en A se lanza un frente en B y su informe vuelve solo

### F4 · Front y documentación

- [x] Tira de PCs arriba del tablero, solo con peers emparejados
- [x] Chips con conteo, memoria y temperatura; filtro; colapso
- [x] Borde o badge de color por PC en cada tarjeta
- [x] Tarjetas grises y controles deshabilitados con el peer caído
- [x] Pantalla de emparejamiento (mostrar frase, pegar frase, lista de peers, revocar)
- [x] Filtro por proyecto arriba (pedido 2026-09-26): un chip por repo para ver u ocultar, y  *(al final: el click elige proyectos, afuera del buscador, y ★ respeta lo elegido)*
      «★ Coordinadoras»; se combina con PCs, buscador y agentes; persiste en el navegador
- [x] Pruebas Playwright de la tira y las flechas entre PCs
- [x] README: sección "Varias PCs", API nueva, archivos de estado nuevos
- [x] `DISENO.es.md` §15 con las decisiones de este plan  *(el archivo está en `.gitignore`: queda en disco, no en el repo)*
- [ ] **Cierre:** prueba real con la notebook, con terminales de prueba

### F5 · Skill `lienzo`

`SKILL.md`:

- [x] Sección "Varias PCs": qué es de cada PC y qué es de la federación
- [x] "Cómo se lanzan": `POST /sessions/launch` para una PC remota; `explorer.exe` solo local
- [x] Título de tarjeta con la PC cuando hay más de una: `<proyecto> - encargo A @notebook - <descripción>`
- [x] Tabla de API: `pc`, `/peers`, `/peer/health`, `scope` de la coordinadora, `launch`
- [x] "Los dos canales": el nativo no cruza PCs
- [x] Working tree: "un commiter por árbol", la delegada por PC y el merge desde `ronda-<N>/<pc>`
- [x] CPU y memoria: pisos y semáforo por PC, lectura por `/peer/health`
- [x] Trampas nuevas: peer caído, `/clear` en PC remota (buscar por `pid` y `pc`)

`coordinar.py`:

- [x] Filtro y columna `pc` en `frentes()` y `tablero()`
- [x] `tamano_contexto_mb()` y `modelo_de()` leen `transcript_bytes` y `model` de la API, no del disco
- [x] `lanzar(pc, cwd, titulo)` y `salud()`

`CLAUDE.md` global:

- [x] La sección del lienzo queda en dos líneas y un puntero al skill, para no duplicarlo

- [ ] **Cierre:** una ronda real repartida entre dos PCs usando solo el skill, y el skill
      corregido contra lo medido
