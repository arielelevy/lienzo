# Informe del frente A · ronda 3: documentación y skill (F4 docs y F5 entera)

Registro histórico de esta ronda. Los resultados corresponden al código revisado en ese momento.

## Que queda

- **`README.md`**: sección nueva "Varias PCs" (después de "Acceso desde el celular", antes de
  "API") con emparejar (frase de seis palabras, tope 4, revocar, verificado contra
  `web/src/components/Pairing.tsx`, que ya existe y usa `/peers/offer`, `/peers/join`,
  `DELETE /peers/<pc_id>`; el gesto real es el ítem 🖥 Varias PCs del menú ⋯, no "Emparejar PC"
  como pensé al principio, corregido tras leer `Header.tsx`), red y firewall (`install.py --peer`,
  con y sin `--dry-run`, verificado contra el código: `--dry-run` no pide admin), lanzar en otra PC
  (`POST /sessions/launch`, `launch_roots`), la tira de PCs y los chips de proyecto (el click
  elige proyectos, no oculta; ★ Coordinadoras se combina con lo elegido), la coordinadora entre
  PCs (`scope: "pc"`), el canal nativo que no cruza PCs, y seguridad en criollo. Tabla de API con
  las filas nuevas (`GET /peers`, `POST /peers/offer`, `POST /peers/join`,
  `DELETE /peers/<pc_id>`, `POST /sessions/launch`, `PUT .../coordinator` con `scope`) y una nota
  aparte de que `/peer/*` es otra API, en otro puerto, entre PCs, nunca del navegador. "Estructura"
  con los siete módulos nuevos (`identity`, `federation`, `pairing`, `beacon`, `health`, `mirror`,
  `launch`) y los dos componentes del front (`PcStrip`, `ProjectStrip`), `LIENZO_HOME`, los
  archivos de estado nuevos (`peer.json`, `peers.json`, `launch/`), una limitación nueva (peer
  caído no avisa activo) y el conteo de tests actualizado (380, corrido al final de la ronda).
- **`DISENO.es.md`**: §15 "Decisiones del 2026-09-26: varias PCs", por qué P2P y no Redis, cada PC
  dueña de lo suyo (con el mecanismo real: `mirror.forward`/503, no el genérico del plan), la
  coordinadora federada y `scope: "pc"` (con el matiz real: la separada gana siempre en su propia
  PC, la federada vale en el resto), un commiter por árbol, el incidente del `git stash` de la
  ronda 2 como lección (con el detalle medido: dos frentes vieron sus archivos volver solos a HEAD
  sin correr git, la causa se supo después), y un §15.6 de estado de implementación con lo que está
  en el árbol y lo que sigue abierto (el lock de la PC de menor `pc_id`, la prueba real con dos
  notebooks).
- **Skill `lienzo`** (`~\.agents\skills\lienzo\SKILL.md`):
  sección nueva "Varias PCs" arriba de todo (qué es de cada PC, qué cambia para coordinar);
  "Cómo se lanzan" sumó el título con `@<pc>` y una subsección "Lanzar en otra PC"
  (`POST /sessions/launch`); la tabla de API sumó `pc`/`repo_key`/`transcript_bytes`/`model` en
  `GET /sessions`, `scope` en `coordinator`, `GET /peers` y `POST /sessions/launch`; "Los dos
  canales" ahora dice explícito que el nativo no cruza PCs; "El patrón que funciona" sumó "un
  commiter por árbol" (la delegada por PC, `fetch` + `worktree` + merge); "CPU, memoria y
  temperatura" sumó cómo se ve la salud de una PC remota (`GET /peers` para el resumen,
  `/peer/health` para el detalle); "Trampas medidas" sumó tres: peer caído (se nota por la tira, no
  hay aviso activo), `/clear` en otra PC (buscar por `pid` y `pc`), y la trampa medida hoy: no
  correr `git stash` en un árbol compartido, ni para comparar contra HEAD (`git show HEAD:<archivo>`
  en su lugar).
- **`coordinar.py`** (mismo directorio, junto al SKILL.md): `frentes(ronda, prefijo, todas, pc=None)`
  y `tablero(ronda, prefijo, pc=None)` con filtro y columna `pc`; `modelo_de(s)` y
  `tamano_contexto_mb(s)` ahora leen `model`/`transcript_bytes` de la tarjeta (`GET /sessions`)
  primero, con el motivo explícito en el docstring: el transcript de una sesión remota vive en un
  disco que no es el nuestro, así que el `stat`/lectura local de antes sólo puede seguir siendo el
  respaldo para una sesión local en un server viejo sin esos campos. `lanzar(pc, cwd, titulo,
  agent="claude")` y `salud()` (`GET /peers`), nuevas. Sintaxis verificada con `py_compile`;
  probado contra el server real de 7321 sólo con lecturas (`salud()`, `sesiones()`,
  `modelo_de()`, `tamano_contexto_mb()`, `tablero()` con un prefijo inexistente para no imprimir
  nada real): las cuatro funciones devolvieron lo esperado (9 sesiones reales detectadas, `salud()`
  vacía porque esta PC no tiene peers emparejados).
- **`~\.claude\CLAUDE.md`**: la sección "Trabajar en equipo: el lienzo" (antes
  ~85 líneas con el detalle entero de emparejamiento, canales y patrón) quedó en 2 líneas más un
  puntero al skill. Verifiqué antes de cortar que las cuatro piezas que tenía (intro, cómo se
  lanzan, los dos canales, el patrón que funciona) ya están en el skill, incluso más completas con
  lo de esta ronda.
- **`~\.codex\AGENTS.md`**: no es un link (archivo regular, `Links: 1`, contenido
  casi idéntico a `CLAUDE.md` salvo el auto-referencia `AGENTS.md`/`CLAUDE.md` invertida) y **nunca
  había tenido** la sección "Trabajar en equipo: el lienzo", quedó desactualizado desde antes de
  que esa sección existiera en `CLAUDE.md`. Le agregué el mismo texto compacto, en el mismo lugar
  (el mismo que en `CLAUDE.md`), para que las dos puntas dejen de
  divergir en esto.

## Que medí

- `python -m pytest tests -q` (insumo para el número del README y de DISENO.es.md): **380 tests,
  20,2 s**, todos en verde, corrido sobre el árbol tal como lo dejó la ronda 2 ya commiteada
  (`4c111ce`) más lo que el frente C viene agregando en curso en `server.py`.
- `coordinar.py` contra el server real de 7321, sólo `GET` (`salud`, `sesiones`, `modelo_de`,
  `tamano_contexto_mb`, `tablero` con un prefijo que no matchea nada): sin errores, valores
  coherentes con el tablero real (9 sesiones, esta PC sin peers).
- No hice mediciones de red/beacon nuevas: son de la ronda 2 (`docs/ronda2/informe-A.md`) y siguen
  valiendo.

## Que dejé afuera y por qué

- No agregué una pantalla de emparejamiento al README como "pendiente": ya existe
  (`Pairing.tsx`), lo verifiqué leyendo el componente y su enganche en `Header.tsx`/`App.tsx` antes
  de escribir la sección, así que la documenté como lo que es, no como el ítem "pendiente" que
  todavía marca el checklist del plan (eso lo actualiza la coordinadora, no yo).
- No toqué `server.py`, `mirror.py`, `sessions.py`, `rules.py`, `launch.py` ni ningún módulo de
  código: mi encargo era documentación y skill. Para relevar las rutas y el enrutado reales usé un
  fork de investigación (solo lectura) en vez de cargarme todo `server.py` (1738 líneas) en el
  contexto.
- No marqué nada del checklist del plan, como pide el encargo común: eso lo hace la coordinadora
  después de verificar.
- `coordinar.py`: no agregué manejo de reintentos ni timeout distinto para `salud()`/`lanzar()`; usan
  el mismo `pedir()` de siempre (timeout 20s), consistente con el resto del módulo.

## Que vi fuera de mis archivos (y dónde lo anoté)

Todo en `docs/ronda3/notas-A.md`:

- El fork de investigación encontró una diferencia entre la interfaz de `federation.Transport` que
  documentaba yo en la ronda 2 (`get/post/put/delete` separados) y la que `server.py` usa hoy
  (`PeerConn` con un cuarto campo `self_pc_id`, un solo `.request()` que devuelve `(status, dict)`).
  No la usé para nada de lo que escribí esta ronda (no dependía de eso), pero lo anoto para quien
  actualice `federation.py` o su informe.
- `server.py` no lee todavía la variable `LIENZO_PEER_PORT` que documenté en la ronda 2 para
  `pairing._my_port()`: el listener real usa sólo `--peer-port` (argparse). No es un bug, son dos
  mecanismos de override para dos cosas ligeramente distintas (el listener real vs. dos instancias
  de prueba en una sola PC), pero si alguna vez hace falta que el listener real también respete la
  variable de entorno, falta enchufarla.
- `set_coordinator(s, on, scope=None)` y `rules.loop_conflict` ya están implementados en
  `sessions.py`/`rules.py` al momento de escribir esto (los vi con `grep`, no lo tenía confirmado
  al empezar): el `except TypeError` de compatibilidad que tiene `server.py` para el caso de que
  `scope` no existiera todavía es código defensivo que ya no hace falta, no un indicio de que algo
  esté a medio terminar. Lo documenté como si `scope` funcionara siempre, que es lo que vi.
