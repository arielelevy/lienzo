---
name: lienzo
description: Coordinar terminales de Claude Code, Codex, Pi y coda en paralelo con el tablero Lienzo, en una PC o entre varias. Usar para lanzar sub-CLI, repartir frentes, mandar encargos, abrir una consulta entre investigadores, comunicarse con otras sesiones, cerrar rondas y llevar la memoria del proyecto.
---

# lienzo · coordinar terminales en paralelo

El lienzo es el tablero de las sesiones de Claude Code y Codex que corren en terminales de
Windows. Server local en `127.0.0.1:7321`, se levanta con `lienzo-server.cmd`. Una tarjeta por
sesión, con su conversación, una caja para contestarle, y aprobación de permisos sin ir a la
terminal. El README del repo es la referencia completa y está actualizado: leerlo cuando algo de
acá no alcance.

**`coda` no es Claude Code.** Es un agente aparte (`coda.exe`, con su propia base en `~/.coda`), uno de
los cuatro que el lienzo conoce: `claude`, `codex`, `pi` y `coda`. Si el usuario pide "sesiones coda" o
"N CLI coda", se lanza con `agent: coda`; nunca se lo reemplaza por `claude` ni se lo interpreta como
"Claude Code". Si el pedido es ambiguo, se pregunta el agente antes de lanzar.

Cuando el usuario pide "lanzá N sub CLI" pide terminales reales, que son las que el tablero ve.
Los subagentes de la herramienta Agent no aparecen en el tablero: sirven para una consulta acotada,
no para repartir trabajo.

**Para hablarle a otra sesión, el lienzo siempre, también entre PCs.** Encargo con
`POST /sessions/<sid>/send` (con `from` y `link_to`, para que quede la flecha) y la vuelta con una
regla `on_stop` cuyo `text` lleve `{respuesta}`. `SendMessage` por el canal nativo no deja rastro en
el tablero: el usuario lo pidió explícito el 2026-10-09 («usá lienzo, armá la conexión»). Un
encargo a otra PC dice qué no tocar (git pull, reiniciar el server, configs de seguridad) y que lo
que pida permiso se lo informe al usuario en vez de forzarlo.

## Varias PCs

Con dos a cuatro PCs de la misma LAN emparejadas (`peers.json`), un solo tablero ve las tarjetas de
todas: `GET /sessions` mezcla lo local con lo espejado, sin que haga falta saber desde qué PC se
mira. La regla de fondo es cada PC es dueña de lo suyo: teclear en una consola, leer su
pantalla, sus hooks y sus recursos (memoria, CPU, temperatura) son siempre de la máquina donde
corre el proceso. Nunca se replican, se le piden a esa PC por la red (`/peer/*`, firmado), y
`server.py` lo hace transparente: `/sessions/<sid>/send` funciona igual sea local o remota.

Buscar PCs en la LAN: `coordinar.lan()` (o `GET /peers/lan`) devuelve las PCs con el lienzo
andando que todavía no están emparejadas, con su IP y puerto. `lienzo-server.cmd` ya arranca con
`--peers`, así que cada PC se anuncia sola; si una no aparece, falta `install.py --peer` en esa PC
(firewall) o no está en la misma red. Para emparejar hace falta la frase: eso lo hace el usuario en la
pantalla "🖥 Varias PCs", no la coordinadora.

Qué cambia para coordinar: la tira de PCs arriba del tablero (con menos de dos PCs no aparece), el
título de una tarjeta lleva `@<pc>` cuando hay más de una en el tablero, y el canal nativo Claude a
Claude cruza PCs solo con Remote Control (ver «El canal nativo», más abajo). El resto de este skill (nombres, no pid; el patrón coordinadora/frentes;
las trampas) vale igual entre PCs, con los agregados que siguen en cada sección.

## La regla que más cuesta aprender: por nombre, nunca por pid

El lienzo tiene copiar y pegar trabajo entre tarjetas (Ctrl+C / Ctrl+V, o el menú ⋯). Al pegar,
la tarjeta destino hereda el título con la marca copycat y la de origen queda detenida
(`stopped_by`), salvo que se marque Duplicar. Y una sesión detenida no recibe nada: los envíos
rebotan con 409 y las reglas que la apuntan se saltean sin gastar el disparo.

O sea que el tablero resuelve solo la ambigüedad: si dos tarjetas comparten el nombre de un
frente, la que trabaja es la que no está detenida. El pid, en cambio, deja de servir apenas el usuario
mueve un encargo de una tarjeta a otra, porque apunta al proceso que ya no lo tiene.

Se busca por nombre, se descartan las detenidas, y si dos vivas comparten letra gana la copia, que
es la que se puso a trabajar último. Eso es lo que hace `coordinar.py`, al lado de este archivo.

## Cómo se lanzan

No se lanzan directo desde una sesión de Claude Code. La sesión exporta `CLAUDECODE`,
`CLAUDE_CODE_CHILD_SESSION` y compañía, y un `claude` hijo hereda esas variables, se cree una sesión
anidada y se apaga sola sin decir nada. Verificado, y `claude --version` anda igual, así que el
síntoma engaña.

La salida es `explorer.exe`, que desacopla el entorno:

```powershell
Start-Process explorer.exe -ArgumentList "C:\ruta\lanzar-1.cmd"
```

con un `.cmd` que hace `cd /d <repo>`, pone el título con `title`, y llama a `claude.exe` **por ruta
absoluta** (`%USERPROFILE%\.local\bin\claude.exe`; el PATH tampoco se hereda entero). El `.cmd` se
escribe en cp1252 y con CRLF, o los acentos salen rotos en la consola.

**El título de la tarjeta de un encargo es `<proyecto> - encargo <letra> - <descripción>`**, por
ejemplo `miapp - encargo A - describir la mitad 1 de las medidas del modelo`. El proyecto
primero, porque el tablero junta sesiones de varios repos; después `encargo A`, `encargo B`,
`encargo C`… en el orden en que se lanzan, y la descripción dice qué va a decidir o entregar, no
el estado. La coordinadora lleva `<proyecto> - coordinadora - <descripción>`. Se pone con
`PUT /sessions/<sid>/title` apenas aparece la tarjeta, y el mismo texto va en el `title` del
`.cmd`. Si a una sesión viva se le da un encargo nuevo, se renombra con la descripción nueva y
conserva la letra. Con más de una PC en el tablero, el título suma la PC:
`<proyecto> - encargo A @notebook - <descripción>`, para no confundir dos encargos A de PCs
distintas de un vistazo. Mejor todavía: no repetir letra entre PCs. Si se repite,
`coordinar.frentes()` no adivina cuál es: devuelve las dos como `A@<pc_id>` y no hay clave `A`
(el `pc_id` de `GET /peers`, no el `@` del título). Con `frentes(proyecto, pc=…)` se ve una sola PC
y vuelve a haber `A`.

**Lanzar, mandar un encargo o repartir en otra PC:** leer `references/otra-pc.md` antes de hacerlo (cómo se lanza por `pc`, cómo saber si el encargo llegó y lo que ya salió mal al repartir).

## Los dos canales, que son distintos

El lienzo, por su API JSON. Las escrituras piden el header `X-Lienzo: 1` y el JSON en **UTF-8
explícito**, o los acentos se rompen. Lo que se usa para repartir:

| | |
|---|---|
| `GET /sessions` | las tarjetas: `session_id`, `pid`, `title`, `state`, `alive`, `stopped_by`, `copycat_of`, `transcript_path`, y con más de una PC también `pc`, `repo_key`, `transcript_bytes`, `model` |
| `PUT /sessions/<sid>/title` | renombrarla |
| `PUT /sessions/<sid>/coordinator` | `{on: true}`. Una coordinadora por repo en toda la federación, independientemente de la PC |
| `POST /sessions/<sid>/send` | escribirle, aunque esté oculta (local o remota, transparente). Con `from` y `link_to` dibuja la flecha |
| `POST /rules` | `{kind:"on_stop", from, to, text, repeat:true, max_fires:N}`: al cerrar cada turno le manda `text` a `to`. **El informe viaja solo si `text` lleva `{respuesta}`** (la última respuesta entera, de la transcripción); sin el marcador llega únicamente el encabezado (medido el 2026-10-09). Otros marcadores: `{pedido}`, `{titulo}`, `{repo}`, `{agente}` |
| `GET /pending`, `POST /pending/<id>` | permisos, `{decision:"allow"\|"deny"}` |
| `POST /rescan` | barrido de procesos ahora |
| `GET /peers` | las PCs de la federación, la propia primero (`local: true`), con `alive` y `health` (memoria, CPU, temperatura) |
| `POST /sessions/launch` | `{pc?, cwd, agent, title}`: lanza una sesión nueva, local o en la PC `pc` |

El canal nativo Claude a Claude va por afuera: `ListAgents` lista las sesiones vivas y
`SendMessage` les habla. El lienzo lo dibuja como flecha doble pero no lo intermedia. Ve las de
esta máquina y, de las otras PCs, solo las que tienen Remote Control prendido con la misma
cuenta de claude.ai (verificado el 2026-10-05: `chesstudia-I`, en otra PC, recibió y contestó).

- El lienzo las deja visibles y con nombre al lanzarlas: un Claude lanzado por el lienzo arranca
  con `-n <nombre> --remote-control <nombre>`, y el nombre sale del título (`chesstudia - encargo I
  - ...` da `chesstudia-I`; la coordinadora, `chesstudia-coordinadora`). La respuesta del launch lo
  trae en `native_name`.
- Una sesión que ya corre se nombra con `POST /sessions/<sid>/native` (`{name?}`; sin `name`
  sale del título): teclea `/rename` y `/remote-control` y contesta solo el diálogo de Remote
  Control. Solo con la sesión quieta (409 si está corriendo). Renombrar la tarjeta con ✎ en el
  tablero hace lo mismo.
- Sin eso, `ListAgents` muestra nombres automáticos (`chess-f6`) y no ve las sesiones de otra PC.
  En cada PC conviene `"remoteControlAtStartup": true` en `~/.claude/settings.json`, para que
  también las sesiones abiertas a mano queden publicadas; eso lo prende el usuario.

La coordinadora usa el lienzo para todo, también entre dos sesiones de Claude. Medido el
2026-09-26 con seis sesiones de un mismo repo:

- Los nombres nativos no decían qué frente era cada uno. `ListAgents` devolvió `app-77`,
  `app-48`, `app-37`, `app-3e`, sin título. Desde el 2026-10-05 el lienzo las nombra (ver arriba),
  pero una sesión abierta a mano sigue saliendo así hasta que se la nombra. El lienzo direcciona por
  `session_id` con el título a la vista.
- Hablarle a una sesión ocupada no necesita el canal nativo. Un `POST /sessions/<sid>/send` a una
  sesión que está trabajando le llega igual en el turno en curso, como mensaje intercalado (salvo un
  comando con barra, ver trampas). Es lo mismo que daría `SendMessage`.
- El lienzo deja rastro y el nativo no: la flecha con `from` y `link_to`, el historial en
  `GET /links` y las reglas `on_stop` que traen los informes solos.

El canal nativo queda para cuando no hay lienzo (el server caído) o para una sesión que no está en el
tablero. Entre frentes no se abre ninguno de los dos: todo pasa por la coordinadora, que es lo que
evita los bucles.

## Consulta entre investigadores

Para un problema difícil cuyas respuestas se pueden criticar (una conjetura, una decisión de
arquitectura, un bug que nadie entiende), no un trabajo con archivos (eso es SDD o un frente): dos o
tres investigadores de modelos de frontera, con esfuerzo alto, y un revisor.

```python
cid = c.consulta("¿…?", [sid_claude, sid_codex], vueltas=2, revisor=sid_revisor)
c.consulta_estado(cid)
c.consulta_replica(cid, para, de, vuelta)   # reenvía a `para` la respuesta de `de` que no le llegó
```

El lienzo manda la vuelta 1 a todos a la vez, después le pasa a cada uno las respuestas de los otros
(acepto / sostengo / refuto con evidencia, o `SIN CAMBIOS`), le pide la síntesis al revisor y que los
investigadores digan si los representa (`REPRESENTA BIEN` o su corrección). Todo por el envío de
siempre, con flechas violetas punteadas; las tarjetas muestran su papel y en qué vuelta va, y la tira
de consultas arriba del tablero abre la consulta entera. Nadie le escribe a nadie directo: no hay
bucle posible. La síntesis queda en `~/.lienzo/consultas/<id>/sintesis.md`, en la memoria del proyecto
y te llega a vos (`YO`). Los investigadores tienen que estar quietos al abrir (si no, 409).

## El patrón que funciona

Una sesión coordinadora (la ★ del repo) reparte, cablea una regla `on_stop` de cada frente hacia
sí misma, recibe los informes al cierre de cada turno, verifica y arma la ronda siguiente. El reparto
es manual a propósito: dos agentes vinculados en los dos sentidos se contestan hasta quemar los
créditos, y por eso el server rechaza el bucle A↔B y toda regla lleva tope.

Tres reglas que evitan el desastre con varias sesiones en un solo working tree:

- Cada sesión toca un conjunto de archivos disjunto, y lo que encuentra fuera lo anota en un
  archivo propio en vez de editarlo. Incluido el formateo: `ruff format` se corre **con la ruta
  propia, no con la del paquete compartido**, o le reformatea el código a la vecina.
- **Nadie hace `git commit` ni `git add` salvo la coordinadora.** Cuatro sesiones commiteando en un
  solo árbol es un conflicto de índice garantizado, y ramas separadas no sirven: hay un solo árbol.
  Con varias PCs, la regla es un commiter por árbol, no necesariamente la misma persona en cada
  una: en la PC remota los frentes tampoco commitean, y al cerrar la ronda la coordinadora le pide a
  una de esas sesiones, la delegada de esa PC, que commitee todo y haga push;
  la coordinadora hace `fetch`, verifica en un `git worktree` local (contra el árbol, nunca contra el
  informe) y mergea.
- Entre PCs se sincroniza por una sola rama temporal de la ronda (`ronda-<fecha>`), la misma
  para todas: cada commiter hace `pull --rebase` y `push` sobre ella, nunca `--force`. Al cerrar, la
  coordinadora la mergea en la rama principal local y la borra de `origin`. **Nunca se pushea la rama
  que despliega** ni se abre un PR (hay workflows que corren en `pull_request`): antes del primer
  push, leer los `on:` de `.github/workflows/`, y después comprobar con `gh run list --branch …` que
  la rama no disparó nada. Worktrees por frente, no: los guiones del repo suelen tener la ruta del
  árbol fija y cada worktree necesitaría sus propias dependencias.
- Las bases de datos de prueba llevan el número del frente y el pid en el nombre. Dos suites que
  crean y destruyen la misma base se pisan, y produce fallas que después pasan solas y confunden.

## Cómo se arma una ronda

Un encargo común con las reglas del entorno, y un encargo por frente en archivos `.md` en el
scratchpad. El mensaje que se manda es corto y apunta a los dos archivos: los encargos largos por la
caja se cortan.

Un encargo bueno tiene, en este orden: tu carpeta y solo esta; el insumo, con los documentos
y las secciones exactas; qué hacer, numerado, con el orden cuando importa; qué medir, con el
número que se espera; lo que no es tuyo, nombrando de quién es. Y cierra pidiendo un informe con
qué quedó archivo por archivo con su prueba, qué se midió, qué se dejó afuera y por qué, y qué se vio
fuera de la carpeta propia.

Lo que más mejora el resultado: escribir el criterio antes que el código —"el reporte de tasa se
escribe antes que el parser"—, y pedir que cada número diga en qué condición se tomó. Con doce
sesiones en la máquina, la misma consulta puede medir 0,81 ms o 7,25 ms.

## Reusar, compactar, limpiar o cerrar

Antes de cada ronda nueva, la coordinadora decide sesión por sesión. Lo decide ella, no le pregunta
al usuario:

| Situación | Qué se hace | Por qué |
|---|---|---|
| Encargo que sigue directo lo que acaba de hacer, transcript chico | reusar tal cual | arranca sabiendo |
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
5. Recién entonces mandarle el encargo, al id nuevo, empezando por «leé `AGENTS.md`
   y tu informe anterior; contestá en español». El `/clear` le saca el `AGENTS.md` del contexto y
   vuelve contestando en inglés. (No hay `CLAUDE.md`: ni de usuario ni en los repos, sólo `AGENTS.md`.)

`/compact` no cambia nada de eso: se manda y después el encargo al mismo id. Igual se verifica el
efecto en el transcript, no el envío. `/exit` se verifica con que el proceso ya no exista y la
tarjeta quede `muerta`.

**`/exit` no cierra un Pi** (medido el 2026-10-10, Pi con gpt-6.1-sol en modo build): lo tomó como
mensaje, contestó «Cierro» y el proceso siguió vivo, con el `send` en `ok: true`. Un Pi no se da por
cerrado por el envío: mirar que el `pid` ya no exista. Todavía no hay un comando de cierre de Pi
medido desde el lienzo; mientras tanto, pedirle al usuario que lo cierre o cerrar su consola
(`Stop-Process -Id <pid>`), sólo con la sesión quieta y su trabajo ya entregado.

## Restaurar sesiones tras un reinicio

Al reiniciar la PC mueren todos los agentes y las tarjetas se borran a los 60 s. Cada PC guarda en
`~/.lienzo/restaurar.json` dónde estaba cada sesión (agente, carpeta, título, id) y las relanza
con el retomar de cada agente (`claude --resume <id>`, `codex resume <id>`, `pi --resume`,
`coda --lastsession`). Una sesión cerrada a propósito (`/exit`, logout) o borrada a mano no se
guarda; la que se cierra con la ventana o el apagado, sí.

```python
c.restaurables()  # de esta PC y de los peers vivos, cada una con su `pc`
c.restaurar(session_id, pc=None)  # una; con `pc` se manda a esa PC
c.restaurar(todas=True, pc=None)  # todas las de esa PC, una por una (~2 s entre cada una)
```

- `todas` respeta la memoria de la PC dueña: hace falta 1,5 GB libres + 0,7 GB por sesión. Si no
  entran, rechaza (409) y dice cuántas sí; con `limit_by_memory=True` relanza solo esas.
- La respuesta es `{restored: [...], failed: [{session_id, error}]}`. Una relanzada sale del
  registro; una que falló queda para reintentar. La `cwd` tiene que seguir dentro de
  `launch_roots`.
- Antes de relanzar todas, mirar `restaurables()`: tras un `/clear` o un cierre raro puede haber
  entradas que ya no interesan; se descartan con `DELETE /sessions/<id>`.

## CPU, memoria y temperatura

La coordinadora los vigila antes de lanzar más frentes: con seis sesiones en 15 GB se termina antes la memoria que la CPU. Los comandos para medirlos y los umbrales están en `references/recursos.md`.

## Trampas medidas

Recursos compartidos entre frentes (puertos, bases, archivos) y el sistema donde corren (PowerShell, WSL, rutas): leer `references/trampas.md` al repartir frentes que comparten algo o cuando un frente falla de forma rara.

## Cuenta de GitHub, secretos y copias entre PCs

Un 403 de `gh`/`git push`, pasar un token a otra PC o copiar archivos entre PCs: leer `references/cuentas-y-copias.md`.

## Qué hace la coordinadora cuando llega un informe

Leé el informe con `c.informe(s)`, no con `s["last_reply"]` a secas: mientras una coda trabaja, el
lienzo deja ahí «usando bash» o «usando read», que no es una respuesta. `informe` devuelve None en
ese caso.

Si te autorizan a aprobar permisos de una coda, usá `aprobador.py` (en esta carpeta) con una
`Politica` mínima para esa tarea: verbos, carpetas, `rm` y pushes permitidos. Aprueba solo lo que
pasa la lista, frena lo truncado y lo peligroso, y cada freno te lo informa para que decidas vos.
Corre en segundo plano con `vigilar(...)` y se detiene cuando la tarea termina.

Por defecto solo aprueba git de lectura (`GIT_LECTURA`: `status`, `log`, `diff`, `show`…): ni
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

## Conocimiento por proyecto

Lo que pasa por el lienzo queda solo en la base del proyecto (encargos, informes, hallazgos, veredictos), replicada entre PCs. Nada pasa a `vigente` ni `confirmado` sin un veredicto. Para registrar un proyecto, dar veredictos, cerrar una ronda o escribir el bloque `conocimiento` de un informe: leer `references/conocimiento.md`.
