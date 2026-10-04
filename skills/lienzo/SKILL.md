---
name: lienzo
description: Coordinar terminales de Claude Code y Codex en paralelo mediante el tablero Lienzo. Usar para lanzar sub-CLI, repartir frentes, comunicarse con otras sesiones y cerrar rondas de trabajo.
---

# lienzo · coordinar terminales en paralelo

El lienzo es el tablero de las sesiones de Claude Code y Codex que corren en terminales de
Windows. Server local en `127.0.0.1:7321`, se levanta con `lienzo-server.cmd`. Una tarjeta por
sesión, con su conversación, una caja para contestarle, y aprobación de permisos sin ir a la
terminal. **El README del repo es la referencia completa y está actualizado**: leerlo cuando algo de
acá no alcance.

**`coda` no es Claude Code.** Es un agente aparte (`coda.exe`, con su propia base en `~/.coda`), uno de
los cuatro que el lienzo conoce: `claude`, `codex`, `pi` y `coda`. Si el usuario pide "sesiones coda" o
"N CLI coda", se lanza con `agent: coda`; nunca se lo reemplaza por `claude` ni se lo interpreta como
"Claude Code". Si el pedido es ambiguo, se pregunta el agente antes de lanzar.

Cuando el usuario pide **"lanzá N sub CLI"** pide **terminales reales**, que son las que el tablero ve.
Los subagentes de la herramienta Agent no aparecen en el tablero: sirven para una consulta acotada,
no para repartir trabajo.

## Varias PCs

Con dos a cuatro PCs de la misma LAN emparejadas (`peers.json`), un solo tablero ve las tarjetas de
todas: `GET /sessions` mezcla lo local con lo espejado, sin que haga falta saber desde qué PC se
mira. La regla de fondo es **cada PC es dueña de lo suyo**: teclear en una consola, leer su
pantalla, sus hooks y sus recursos (memoria, CPU, temperatura) son siempre de la máquina donde
corre el proceso. Nunca se replican — se le piden a esa PC por la red (`/peer/*`, firmado), y
`server.py` lo hace transparente: `/sessions/<sid>/send` funciona igual sea local o remota.

**Buscar PCs en la LAN**: `coordinar.lan()` (o `GET /peers/lan`) devuelve las PCs con el lienzo
andando que todavía no están emparejadas, con su IP y puerto. `lienzo-server.cmd` ya arranca con
`--peers`, así que cada PC se anuncia sola; si una no aparece, falta `install.py --peer` en esa PC
(firewall) o no está en la misma red. Para emparejar hace falta la frase: eso lo hace el usuario en la
pantalla "🖥 Varias PCs", no la coordinadora.

Qué cambia para coordinar: la tira de PCs arriba del tablero (con menos de dos PCs no aparece), el
título de una tarjeta lleva `@<pc>` cuando hay más de una en el tablero, y **el canal nativo Claude
a Claude no cruza PCs** (`ListAgents` es de la máquina donde corre; entre frentes de PCs distintas
todo pasa por el lienzo). El resto de este skill (nombres, no pid; el patrón coordinadora/frentes;
las trampas) vale igual entre PCs, con los agregados que siguen en cada sección.

## La regla que más cuesta aprender: por nombre, nunca por pid

El lienzo tiene **copiar y pegar trabajo entre tarjetas** (Ctrl+C / Ctrl+V, o el menú ⋯). Al pegar,
la tarjeta destino **hereda el título con la marca copycat** y la de origen **queda detenida**
(`stopped_by`), salvo que se marque Duplicar. Y una sesión detenida **no recibe nada**: los envíos
rebotan con 409 y las reglas que la apuntan se saltean sin gastar el disparo.

O sea que **el tablero resuelve solo la ambigüedad**: si dos tarjetas comparten el nombre de un
frente, la que trabaja es la que no está detenida. El pid, en cambio, deja de servir apenas el usuario
mueve un encargo de una tarjeta a otra, porque apunta al proceso que ya no lo tiene.

Se busca por nombre, se descartan las detenidas, y si dos vivas comparten letra gana la copia, que
es la que se puso a trabajar último. Eso es lo que hace `coordinar.py`, al lado de este archivo.

## Cómo se lanzan

**No se lanzan directo desde una sesión de Claude Code.** La sesión exporta `CLAUDECODE`,
`CLAUDE_CODE_CHILD_SESSION` y compañía, y un `claude` hijo hereda esas variables, se cree una sesión
anidada y se apaga sola sin decir nada. Verificado, y `claude --version` anda igual, así que el
síntoma engaña.

La salida es `explorer.exe`, que desacopla el entorno:

```powershell
Start-Process explorer.exe -ArgumentList "C:\ruta\lanzar-1.cmd"
```

con un `.cmd` que hace `cd /d <repo>`, pone el título con `title`, y llama a `claude.exe` **por ruta
absoluta** (`%USERPROFILE%\.local\bin\claude.exe`; el PATH tampoco se hereda entero). El `.cmd` se
escribe en **cp1252 y con CRLF**, o los acentos salen rotos en la consola.

**El título de la tarjeta de un encargo es `<proyecto> - encargo <letra> - <descripción>`**, por
ejemplo `miapp - encargo A - describir la mitad 1 de las medidas del modelo`. El proyecto
primero, porque el tablero junta sesiones de varios repos; después `encargo A`, `encargo B`,
`encargo C`… en el orden en que se lanzan, y la descripción dice qué va a decidir o entregar, no
el estado. La coordinadora lleva `<proyecto> - coordinadora - <descripción>`. Se pone con
`PUT /sessions/<sid>/title` apenas aparece la tarjeta, y el mismo texto va en el `title` del
`.cmd`. Si a una sesión viva se le da un encargo nuevo, se renombra con la descripción nueva y
conserva la letra. **Con más de una PC en el tablero**, el título suma la PC:
`<proyecto> - encargo A @notebook - <descripción>`, para no confundir dos encargos A de PCs
distintas de un vistazo. Mejor todavía: **no repetir letra entre PCs**. Si se repite,
`coordinar.frentes()` no adivina cuál es: devuelve las dos como `A@<pc_id>` y no hay clave `A`
(el `pc_id` de `GET /peers`, no el `@` del título). Con `frentes(proyecto, pc=…)` se ve una sola PC
y vuelve a haber `A`.

### Lanzar en otra PC

Para una PC remota (ya emparejada) no se usa `explorer.exe` desde acá — eso sólo sirve en la propia
máquina. Se pide `POST /sessions/launch {pc: "<pc_id>", cwd, agent, title}`: la PC dueña escribe su
`.cmd` y lo lanza, igual que el mecanismo de arriba pero del otro lado. `cwd` tiene que caer dentro
de `launch_roots` de esa PC (`config.json`; vacía o ausente es *ninguna* carpeta, no todas) y el
`agent` es uno de los cuatro conocidos (`claude`, `codex`, `pi`, `coda`). La tarjeta nueva aparece
después de un barrido: pedir `GET /peers` para saber qué `pc_id` usar, y buscar la tarjeta nueva
por `title` (o por `pc` + orden de aparición) una vez que el barrido corrió.

### Mandar un encargo a otra PC y saber si llegó

Un `200` de `send` sólo dice que el server aceptó el pedido; para una tarjeta de otra PC no prueba
que se haya tecleado. Usar **`coordinar.enviar_seguro(s, texto, proyecto=…, letra=…)`**, que
devuelve `{ok, code, motivo, sid}` y hace lo que a mano se olvida:

- relee la tarjeta antes de mandar (la que se le pasa puede estar vieja) y verifica que lo tomó:
  que cambie su `last_prompt`, o que pase a `corriendo` si antes no lo estaba. **A una tarjeta que
  ya estaba `corriendo` el estado no le prueba nada** (puede estar ocupada, o pegada así tras un
  `/compact`): si su prompt no cambia, devuelve `ok: False` con «no hay prueba de que lo tomó».
  Puede haberle llegado igual, como mensaje intercalado: mirar su pantalla o su transcript antes
  de reenviar;
- un comando con barra (`/clear`, `/model`) a una tarjeta `corriendo` no se manda (409): en una
  consola ocupada queda encolado y se pierde. Si se sabe que está quieta, usar `enviar`;
- **404 con `gone`**: la otra PC ya no tiene esa tarjeta (la reinició, cerró la consola). El server
  la saca del tablero solo; con `proyecto` y `letra` se busca el frente por nombre **en esa misma
  PC** y se manda al id nuevo. Sin esos dos no adivina;
- **503 con `no_llego`** (la PC no está en la federación o rechazó la conexión): el pedido no salió,
  así que espera y reintenta, hasta dos veces. **Un timeout o un 503 sin esa marca no se
  reintenta**: el corte pudo ser después de teclear, y reintentar duplicaría el encargo. El
  `motivo` lo dice («pudo haberse tecleado igual»): mirar la tarjeta antes de reenviar. Con un
  server viejo en la otra PC (sin la marca) nunca reintenta;
- una tarjeta detenida (`stopped_by`) no se manda: devuelve por qué;
- un texto con caracteres de control se corta antes de mandar (400): casi siempre es una ruta de
  Windows en un string de Python sin escapar (`"D:\apps"` lleva un `\a`, que es BEL). Rutas con `/`
  o en *raw string*.

Si `ok` es falso, **no seguir como si el frente trabajara**: mirar `motivo`. El server deja el
rastro en `~/.lienzo/lienzo.log` (líneas `→ <pc> POST /sessions/…`); si no hay nada, el pedido no
salió de esta PC. Un envío a otra PC puede tardar hasta ~60 s (el timeout del reenvío ya lo
contempla).

### Repartir en otra PC: lo que ya salió mal una vez

- **Antes de abrir N sesiones, `coordinar.capacidad(pc, N)`**: mira la memoria libre de esa PC (cada
  sesión ocupa ~0,7 GB, y con menos de 1,5 GB de reserva Windows se arrastra). Si da `ok: False`,
  abrir menos y decírselo al usuario; no lanzar «a ver qué pasa».
- **Lanzar con `coordinar.lanzar_y_titular(pc, cwd, titulo, agent)`**: devuelve *la* tarjeta nueva y
  ya titulada. `lanzar` solo da el 200 y después hay que adivinar cuál de las tarjetas de esa carpeta
  es. **No lanzar una sesión de prueba**: queda abierta en la PC del usuario ocupando memoria.
- **Todo frente sale cableado, siempre.** Sin una regla `on_stop` hacia la coordinadora, el aviso de que
  un frente terminó (o se colgó) no llega solo y hay que consultarlo a mano. `lanzar_y_titular` ya crea
  esa regla por defecto (con `YO` fijado); para lo que ya estaba abierto, `coordinar.cablear(filtro=…)`.
  Al terminar la ronda, `borrar_reglas_hacia_mi()`. Antes de dar por andando un frente, comprobar que
  tiene su regla (`GET /rules` incluye las de otras PCs). Una tarjeta nace como `pid-N` y cambia a su id
  real al llegar el primer hook: el lienzo le traslada la regla solo.
- **Una sesión sin hooks (coda, o recién barrida) cambia de id**: nace `pid-NNNN` y al engancharse los
  hooks pasa a su UUID. Se la sigue con `coordinar.reubicar(s, sesiones())` (por pc + pid + cwd);
  `enviar_seguro` ya lo hace, y devuelve el `sid` vigente.
- **Un agente puede colgarse sin decir nada** (coda con el modelo del DGX quedó 5 min en «Waiting for
  model»). Mientras espera un encargo, `coordinar.estancada(s, minutos=5)` avisa si dice `corriendo`
  pero la pantalla no cambió. Entonces: interrumpir (`POST …/interrupt`) y reintentar, o pasar el
  trabajo a otro agente; no esperar indefinido.
- **A un coda no se le manda un mensaje largo.** Más de 500 caracteres o con saltos de línea el lienzo
  lo vuelve adjunto y el coda tiene que leerlo con su herramienta `read`, que se traba (medido: 4 codas,
  Qwen y GLM, más de una hora en «usando read»; uno ni respondía al `/exit`). Con un mensaje corto
  responde en 5 a 10 s y su herramienta de shell anda. Entonces: mensajes de menos de 500 caracteres y
  sin saltos de línea, y en el mismo mensaje «NO uses la herramienta read; leé con el shell (`type`),
  de a partes de 150 líneas». Un coda colgado que no responde al `/exit` se cierra pidiéndole a otro
  agente de esa PC un `taskkill /F /PID <pid>` de ese PID.
- **El modelo se elige al lanzar**: `coordinar.lanzar(pc, cwd, titulo, "coda", model="globant_dgx/GLM-5.3-Flash")`
  (también `lanzar_y_titular`). **Ojo: en coda el `--model` no vale solo para esa sesión: cambia el modelo
  por defecto de esa PC** (lo escribe en su `config.json`; medido el 2026-10-02: al lanzar un coda con
  GLM 5.3 Flash el default pasó de `Qwen3.8-27B` a GLM a las 00:52:18, y las sesiones lanzadas después
  «sin modelo» ya corrían GLM). Por eso no hay comparación de velocidad entre modelos que valga: si se
  quiere comparar, cada coda se lanza con su `model` explícito, y al terminar se vuelve a poner el
  default que tenía el usuario. Avisarle antes de cambiarlo.
- **El encargo largo a otra PC va por mensaje: el server lo vuelve adjunto solo.** Tecleado en una
  consola, un mensaje con saltos de línea o de más de 500 caracteres sería un Enter por línea; por eso
  el server lo guarda como `mensaje.md` en `~/.lienzo/adjuntos/<id>/` de la PC dueña y teclea una sola
  línea que apunta a él. Viaja por el lienzo, **sin git ni `pull`**. No hay límite de POST que lo
  impida (el cuerpo admite hasta 8 MB). Un archivo en el repo solo para lo que el agente de esa PC
  produce él mismo en su carpeta (p. ej. el `tasks.md` que escribió ahí): los demás lo leen sin pull.
  Un agente lento (coda) puede tardar en leer el adjunto: eso es el modelo, no la entrega.
- **Metodología SDD** (spec → clarificar → plan → tareas → análisis → código): un commit local por
  paso, y los módulos se reparten recién con `tasks.md` commiteado, cada uno en su carpeta.

**Los dos lienzos tienen que correr el mismo código.** Con `lienzo-server.cmd` el server se
reinicia solo cuando cambia un `.py` (un `git pull`), pero hay que haberlo levantado así una vez
en cada PC; un server viejo de la otra PC responde distinto y los envíos fallan sin explicación.

## Los dos canales, que son distintos

**El lienzo**, por su API JSON. Las escrituras piden el header `X-Lienzo: 1` y el JSON en **UTF-8
explícito**, o los acentos se rompen. Lo que se usa para repartir:

| | |
|---|---|
| `GET /sessions` | las tarjetas: `session_id`, `pid`, `title`, `state`, `alive`, `stopped_by`, `copycat_of`, `transcript_path`, y con más de una PC también `pc`, `repo_key`, `transcript_bytes`, `model` |
| `PUT /sessions/<sid>/title` | renombrarla |
| `PUT /sessions/<sid>/coordinator` | `{on: true, scope?: "pc"}`. Una coordinadora por repo en toda la federación; `scope: "pc"` la separa sólo para esta PC |
| `POST /sessions/<sid>/send` | escribirle, aunque esté oculta (local o remota, transparente). Con `from` y `link_to` dibuja la flecha |
| `POST /rules` | `{kind:"on_stop", from, to, text, repeat:true, max_fires:N}`: el informe viaja solo al cerrar cada turno |
| `GET /pending`, `POST /pending/<id>` | permisos, `{decision:"allow"\|"deny"}` |
| `POST /rescan` | barrido de procesos ahora |
| `GET /peers` | las PCs de la federación, la propia primero (`local: true`), con `alive` y `health` (memoria, CPU, temperatura) |
| `POST /sessions/launch` | `{pc?, cwd, agent, title}`: lanza una sesión nueva, local o en la PC `pc` |

**El canal nativo Claude a Claude** va por afuera: `ListAgents` lista las sesiones vivas de **esta
máquina** y `SendMessage` les habla. El lienzo lo dibuja como flecha doble pero no lo intermedia, y
**no cruza PCs**: no hay forma de mapear un nombre nativo (`app-1c`) a una sesión de otra PC, así
que entre frentes de PCs distintas todo pasa por el lienzo (por nombre y `session_id`, como
siempre), nunca por `ListAgents`.

**La coordinadora usa el lienzo para todo, también entre dos sesiones de Claude.** Medido el
2026-09-26 con seis sesiones de un mismo repo:

- **Los nombres nativos no dicen qué frente es cada uno.** `ListAgents` devolvió `app-77`,
  `app-48`, `app-37`, `app-3e`, con «busy» o «idle» y la hora de arranque, y ningún título. Mapear un
  nombre a un frente cuesta preguntarle a cada uno, y un error manda el encargo al frente equivocado.
  El lienzo direcciona por `session_id` con el título a la vista.
- **Hablarle a una sesión ocupada no necesita el canal nativo.** Un `POST /sessions/<sid>/send` a una
  sesión que está trabajando le llega igual en el turno en curso, como mensaje intercalado (salvo un
  comando con barra, ver trampas). Es lo mismo que daría `SendMessage`.
- **El lienzo deja rastro y el nativo no:** la flecha con `from` y `link_to`, el historial en
  `GET /links` y las reglas `on_stop` que traen los informes solos.

El canal nativo queda para cuando no hay lienzo (el server caído) o para una sesión que no está en el
tablero. Entre frentes no se abre ninguno de los dos: todo pasa por la coordinadora, que es lo que
evita los bucles.

## El patrón que funciona

Una sesión **coordinadora** (la ★ del repo) reparte, cablea una regla `on_stop` de cada frente hacia
sí misma, recibe los informes al cierre de cada turno, verifica y arma la ronda siguiente. El reparto
es manual a propósito: dos agentes vinculados en los dos sentidos se contestan hasta quemar los
créditos, y por eso el server rechaza el bucle A↔B y toda regla lleva tope.

Tres reglas que evitan el desastre con varias sesiones en un solo working tree:

- **Cada sesión toca un conjunto de archivos disjunto**, y lo que encuentra fuera lo anota en un
  archivo propio en vez de editarlo. Incluido el formateo: `ruff format` se corre **con la ruta
  propia, no con la del paquete compartido**, o le reformatea el código a la vecina.
- **Nadie hace `git commit` ni `git add` salvo la coordinadora.** Cuatro sesiones commiteando en un
  solo árbol es un conflicto de índice garantizado, y ramas separadas no sirven: hay un solo árbol.
  **Con varias PCs, la regla es un commiter por árbol**, no necesariamente la misma persona en cada
  una: en la PC remota los frentes tampoco commitean, y al cerrar la ronda la coordinadora le pide a
  una de esas sesiones, la **delegada de esa PC**, que commitee todo en una rama propia y haga push;
  la coordinadora hace `fetch`, verifica en un `git worktree` local (contra el árbol, nunca contra el
  informe) y mergea.
- **Las bases de datos de prueba llevan el número del frente y el pid en el nombre.** Dos suites que
  crean y destruyen la misma base se pisan, y produce fallas que después pasan solas y confunden.

## Cómo se arma una ronda

Un **encargo común** con las reglas del entorno, y **un encargo por frente** en archivos `.md` en el
scratchpad. El mensaje que se manda es corto y apunta a los dos archivos: los encargos largos por la
caja se cortan.

Un encargo bueno tiene, en este orden: **tu carpeta y solo esta**; **el insumo**, con los documentos
y las secciones exactas; **qué hacer**, numerado, con el orden cuando importa; **qué medir**, con el
número que se espera; **lo que no es tuyo**, nombrando de quién es. Y cierra pidiendo un informe con
qué quedó archivo por archivo con su prueba, qué se midió, qué se dejó afuera y por qué, y qué se vio
fuera de la carpeta propia.

Lo que más mejora el resultado: **escribir el criterio antes que el código** —"el reporte de tasa se
escribe antes que el parser"—, y pedir que cada número diga en qué condición se tomó. Con doce
sesiones en la máquina, la misma consulta puede medir 0,81 ms o 7,25 ms.

## Reusar, compactar, limpiar o cerrar

Antes de cada ronda nueva, la coordinadora decide sesión por sesión. Lo decide ella, no le pregunta
al usuario:

| Situación | Qué se hace | Por qué |
|---|---|---|
| Encargo que sigue directo lo que acaba de hacer, transcript chico | **reusar tal cual** | arranca sabiendo |
| Mismo tema, transcript cargado (varios megas) | **`/compact`** | conserva `session_id`, título y reglas; libera contexto |
| Tema nuevo, o transcript cerca de diez megas | **`/clear`** | arranca limpia; lo que necesita está en disco (su informe) |
| Terminó y no hay encargo para ella | **`/exit`** | cada sesión ocupa ~0,7 GB de RAM |

El tamaño se mira en `transcript_path` de `GET /sessions`.

**Después de un `/clear`, siempre estos pasos, en orden**, porque la sesión cambia de `session_id` y
la tarjeta vieja desaparece:

1. Mandar `/clear` sólo a una sesión quieta (`state` distinto de `corriendo`).
2. Esperar unos segundos, `POST /rescan`, y buscar la tarjeta nueva **por el mismo `pid`**.
3. Reponerle el título, el mismo con la letra del encargo.
4. Recablear su regla `on_stop` hacia la coordinadora (`repeat: true`), y borrar la vieja.
5. Recién entonces mandarle el encargo, **al id nuevo**, empezando por «leé `AGENTS.md`/`CLAUDE.md`
   y tu informe anterior; contestá en español». El `/clear` le saca el `CLAUDE.md` del contexto y
   vuelve contestando en inglés.

`/compact` no cambia nada de eso: se manda y después el encargo al mismo id. Igual se verifica el
efecto en el transcript, no el envío. `/exit` se verifica con que el proceso ya no exista y la
tarjeta quede `muerta`.

## Restaurar sesiones tras un reinicio

Al reiniciar la PC mueren todos los agentes y las tarjetas se borran a los 60 s. Cada PC guarda en
`~/.lienzo/restaurar.json` dónde estaba cada sesión (agente, carpeta, título, id) y las relanza
con el retomar de cada agente (`claude --resume <id>`, `codex resume <id>`, `pi --resume`,
`coda --lastsession`). Una sesión cerrada a propósito (`/exit`, logout) o borrada a mano no se
guarda; la que se cierra con la ventana o el apagado, sí.

```python
c.restaurables()                     # de esta PC y de los peers vivos, cada una con su `pc`
c.restaurar(session_id, pc=None)     # una; con `pc` se manda a esa PC
c.restaurar(todas=True, pc=None)     # todas las de esa PC, una por una (~2 s entre cada una)
```

- `todas` respeta la memoria de la PC dueña: hace falta 1,5 GB libres + 0,7 GB por sesión. Si no
  entran, rechaza (409) y dice cuántas sí; con `limit_by_memory=True` relanza solo esas.
- La respuesta es `{restored: [...], failed: [{session_id, error}]}`. Una relanzada sale del
  registro; una que falló queda para reintentar. La `cwd` tiene que seguir dentro de
  `launch_roots`.
- Antes de relanzar todas, mirar `restaurables()`: tras un `/clear` o un cierre raro puede haber
  entradas que ya no interesan; se descartan con `DELETE /sessions/<id>`.

## CPU, memoria y temperatura: la coordinadora los vigila

Con seis sesiones en una máquina de 15 GB la memoria se termina antes que la CPU. Medido el
2026-09-26 en un proyecto con base de datos en WSL: Windows bajó dos veces a menos de 50 MB libres, WSL se reinició solo de
noche y se cortaron mediciones a mitad. Las sesiones de Claude solas ocupaban 4,3 GB.

**Reglas que van en el encargo común de cada ronda:**

- **Una sola tarea pesada a la vez en toda la máquina**: una batería de pruebas, una consulta o un
  índice grande, un navegador con Playwright, o la API con el dev server levantados. Antes de
  lanzar, el frente mira que no haya otra corriendo y la memoria **del lado donde corre**:
  - adentro de WSL (pruebas, índices, consultas, API): `available` de `free -m` en WSL con al
    menos 3 GB, y Windows con al menos 1 GB;
  - del lado de Windows (Edge, Playwright): Windows con al menos 2 GB.

  **Un piso único de 2 GB en Windows traba la ronda entera**, medido el 2026-09-26: WSL tenía 8 GB
  libres adentro y Windows veía 1,8, porque WSL no devuelve enseguida lo que libera, y cinco
  frentes quedaron esperando una memoria que no necesitaban.
- **Con cinco o más frentes, el cupo lo cuenta la máquina, no cada frente.** Si cada uno mira
  `pgrep` antes de lanzar, dos miran a la vez, ven lugar y lanzan los dos: el 2026-09-26 con el cupo
  de dos la carga llegó a 19 sobre 12 procesadores y 95 °C. La salida es un semáforo con `flock` en
  WSL (por ejemplo `~/.cache/<proyecto>/pesada.sh`): dos archivos de turno, cada tarea pesada se
  lanza envuelta (`bash pesada.sh <comando>`), espera turno, chequea `MemAvailable` y suelta el
  turno al terminar aunque falle. Deja un registro de quién corrió qué y cuándo.
- Las consultas de medición van sin paralelismo del lado de la base (en Postgres,
  `SET max_parallel_workers_per_gather = 0`) y con `nice 19`.
- Al terminar, cada frente cierra lo que levantó: servidores, navegadores, motores.

**Lo que mide la coordinadora**, antes de lanzar algo pesado y cada vez que llega un informe:

```powershell
# memoria libre de Windows, en GB
[math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1MB,2)
# quién la tiene: memoria privada por nombre (el WS de vmmemWSL engaña)
Get-Process | Group-Object ProcessName | % { [pscustomobject]@{n=$_.Name; GB=[math]::Round((($_.Group | Measure-Object PrivateMemorySize64 -Sum).Sum)/1GB,2)} } | Sort-Object GB -Desc | Select -First 8
# temperatura sin administrador: HighPrecisionTemperature en deciKelvin
Get-CimInstance Win32_PerfFormattedData_Counters_ThermalZoneInformation | % { "$($_.Name) $([math]::Round($_.HighPrecisionTemperature/10-273.15,1)) °C" }
```

El sensor bueno es `\_TZ.THRM` (`\_TZ.TZ01` da 20 °C fijo). En el Ryzen 9 7940HS, 95 °C sostenidos
es su techo de diseño, no una alarma; 81 °C es la máquina descansando de un trabajo largo. La carga
de CPU sale de `\Processor(_Total)\% Processor Time` y, adentro de WSL, de `uptime`.
`Win32_Processor.CurrentClockSpeed` miente: da el máximo fijo.

**Con varias PCs, cada una vigila la suya y `GET /peers` trae el resumen** (memoria libre y
temperatura de cada chip de la tira). Para el detalle fino de una PC remota, `/peer/health` de esa
PC (mismos tres números que arriba, medidos del lado de allá); no hay forma de correr el
PowerShell de arriba contra una máquina que no es la propia. Mismo semáforo y mismos pisos que en
una sola PC: la memoria justa de una no se compensa con que sobre en la otra.

**Un monitor permanente mientras dure la ronda**: un `.ps1`
lanzado oculto (`Start-Process pwsh -WindowStyle Hidden -File monitor.ps1`) que cada minuto anota
temperatura, CPU, memoria libre de Windows y carga y memoria de WSL en un CSV, y que cuando algo
pasa su umbral le escribe a la coordinadora por `POST /sessions/<coordinadora>/send`, con 10
minutos de pausa entre avisos del mismo tipo. Umbrales: 96 °C (no menos: el 7940HS se queda en 95
por diseño y avisar antes es avisar siempre), Windows con menos de 0,5 GB, carga de WSL de 14 o más.
Conviene dejarlo en el scratchpad de la coordinadora como `monitor.ps1`.

**Cuando la memoria se termina**, en este orden y sin matar el trabajo de nadie:

1. Liberar la caché de disco de WSL, que se queda con lo que leyó y no lo devuelve sola:
   `sync; echo 1 | sudo -n tee /proc/sys/vm/drop_caches`. Windows lo recupera en unos 30 s.
   Con seis o más frentes conviene dejarlo **automático**: un lazo en WSL que cada 60 s mira
   `Buffers + Cached` de `/proc/meminfo` y, si pasa de 3 GB, hace ese mismo `drop_caches`. Se lanza
   una vez con `setsid nohup ... & disown` desde un `.sh`, y se busca con `pgrep -f "[v]igia"`: el
   nombre del guion no puede aparecer literal en la línea que lo busca, o `pgrep` se encuentra a sí
   mismo. **Y compactar**: `echo 1 | sudo -n tee /proc/sys/vm/compact_memory`, cada 5 minutos en
   el mismo lazo. WSL devuelve las páginas libres en bloques grandes, y con la memoria fragmentada
   no hay bloques que devolver: el 2026-09-26 Windows estaba en 0,06 GB con 7 GB disponibles
   adentro de WSL, y compactar lo llevó a 1,93 GB en segundos. `autoMemoryReclaim=gradual` en el `.wslconfig` ayuda, pero devuelve la caché más lento de
   lo que la llenan un índice o una subida grande (medido el 2026-09-26: Windows en 210 MB con
   `gradual` puesto).
2. Cerrar con `/exit` las sesiones que terminaron.
3. Postergar lo que no apura (mediciones de navegador) y decírselo al frente.

## Trampas medidas

- **Después de un `/compact` la tarjeta queda en `corriendo` aunque la sesión ya esté quieta**
  (medido el 2026-09-26: tres sesiones seguían «corriendo» minutos después de compactar y en la
  terminal se veían inactivas). No esperar a que el estado cambie: dar unos segundos y mandar el encargo; llega
  igual.
- **Un `cd /d` adentro de un comando de PowerShell hace que el guardián de comandos lo bloquee**
  («Remove-Item on system path '/d' is blocked»). Los `.cmd` de lanzamiento se escriben con la
  herramienta Write, no armados en un string de PowerShell. Y `printf` en Git Bash se come las
  barras invertidas de una ruta de Windows: los mensajes con rutas, también con Write.
- **`Invoke-RestMethod` sobre `GET /rules` o `GET /sessions` puede devolver el arreglo entero como un
  solo objeto**, y un `Select-Object` encima muestra una tabla vacía. Parece que las reglas se
  borraron y no. Para listarlas: `(Invoke-WebRequest <url> -UseBasicParsing).Content |
  ConvertFrom-Json | ForEach-Object { $_ }`.

- **Un comando con barra inyectado en una consola ocupada no se ejecuta.** Queda como texto encolado
  y se pierde. Mandar `/model` o `/clear` solo a sesiones que no están corriendo, y **verificar el
  efecto**, no el envío: para `/model`, el campo `model` de la última respuesta en el transcript.
- **Después de un `/clear` la sesión cambia de `session_id`** y la tarjeta vieja desaparece. Hay que
  volver a buscarla, esperando unos segundos y con un `/rescan` en el medio.
- **Las reglas `on_stop` necesitan `repeat: true`.** Sin eso disparan una vez y quedan apagadas, y
  los frentes que cierran dos veces avisan solo la primera.
- **Los ecos.** Cada vez que un frente cierra un turno la regla dispara, aunque no haya terminado su
  trabajo: muchos avisos son "cerré un turno", no "cerré el frente". Se distingue mirando si escribió
  su informe. Durante una pausa larga conviene **apagar las reglas** y volver a armarlas después.
- **El auto-continuar del tablero reactiva las sesiones detenidas** y les escribe "Continuar" en la
  caja. Si el usuario está tipeando en su terminal en ese momento, la palabra se le mete adentro de la
  frase. Está en `GET /config`.
- **Una pausa hay que pedirla explícita**: "terminá lo que tenés, no empieces nada, y si te llega
  Continuar respondé una línea". Sin eso siguen trabajando.
- Los permisos pendientes **vencen a los 60 segundos** y después el prompt aparece en la terminal.
- **Un peer caído no avisa activamente**: se nota porque su chip en la tira pasa a ○ (sin memoria ni
  temperatura, sería un dato viejo) y sus tarjetas quedan grises con los controles deshabilitados a
  los 45 s sin novedades de esa PC. No hay push de "se cayó fulano": hay que mirar la tira.
- **`/clear` en una sesión de otra PC se busca por `pid` *y* `pc`**, no sólo por `pid`: dos PCs
  distintas pueden tener el mismo número de PID sueltos por casualidad, y buscar sólo por `pid`
  después de un `/rescan` puede encontrar la tarjeta de la PC equivocada.
- **Nadie corre `git stash` en un árbol compartido, ni para "comparar contra HEAD"** (medido el
  2026-09-26, ronda 2: un `stash` para mirar un test viejo se llevó puesto el trabajo sin commitear
  de cuatro sesiones a la vez, y el `pop` posterior chocó con una edición concurrente y quedó sin
  aplicar). Para ver una versión vieja de un archivo sin tocar el árbol: `git show HEAD:<archivo> >
  <algo>`, nunca `stash`/`checkout`/`reset`.

## Secretos entre PCs (un token de git)

Nunca pegues un token en un mensaje: queda en claro en los adjuntos y en los transcripts. Para que otra
PC pueda pushear, `c.pasar_credencial_git(pc, "https://host/repo.git")` copia la credencial que ESTA PC
ya tiene guardada: viaja cifrada y la otra la guarda en su almacén de Windows, sin pasar por vos. Para
otro secreto: `c.enviar_secreto(pc, nombre, valor)` (queda 10 min) y `c.leer_secreto(id, pc=pc)` (una
sola vez, desde cualquier PC de la LAN). Si `/peers` muestra `git_auth: vencida` en una PC, arreglalo
antes de mandar un encargo que termine en push.

## Qué hace la coordinadora cuando llega un informe

Leé el informe con `c.informe(s)`, no con `s["last_reply"]` a secas: mientras una coda trabaja, el
lienzo deja ahí «usando bash» o «usando read», que no es una respuesta. `informe` devuelve None en
ese caso.

Si te autorizan a aprobar permisos de una coda, usá `aprobador.py` (en esta carpeta) con una
`Politica` mínima para esa tarea: verbos, carpetas, `rm` y pushes permitidos. Aprueba solo lo que
pasa la lista, frena lo truncado y lo peligroso, y cada freno te lo informa para que decidas vos.
Corre en segundo plano con `vigilar(...)` y se detiene cuando la tarea termina.

**Por defecto solo aprueba git de lectura** (`GIT_LECTURA`: `status`, `log`, `diff`, `show`…): ni
`add`, `commit`, `pull`, `checkout`, `switch`, `fetch` ni `push`. En un árbol compartido solo
commitea la coordinadora, y un `checkout` le cambia la rama a todas las sesiones. Una coda que
trabaja sola en su árbol (y commitea ella) los habilita explícitamente:
`Politica(git_ok=a.GIT_LECTURA + a.GIT_ESCRITURA, …)`, y aun así cada `push` tiene que estar en
`pushes`. Nunca a un frente de un árbol compartido.

Verificar contra el árbol, no contra el informe: `ruff check` y `ruff format --check` sobre esa
carpeta, las pruebas de esa carpeta, `git status` para ver si tocó algo ajeno, y si el frente dice
que dejó la máquina limpia, comprobarlo (`pgrep`, bases de prueba borradas). Después anotarlo en un
archivo de coordinación de la ronda, con lo medido y lo decidido, que es lo que hace que la ronda
siguiente no empiece de cero.

Y al cerrar la ronda: `ruff format` una sola vez sobre todo, las dependencias que los frentes
instalaron declaradas en el `pyproject.toml`, las correcciones que encontraron llevadas a los
documentos, el README con el estado real, y un commit por tema.
