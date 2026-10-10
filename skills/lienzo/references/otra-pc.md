# Lanzar, mandar y repartir en otra PC

Parte de la skill `lienzo` (se lee desde `SKILL.md` cuando hace falta).

### Lanzar en otra PC

Para una PC remota (ya emparejada) no se usa `explorer.exe` desde acá, eso sólo sirve en la propia
máquina. Se pide `POST /sessions/launch {pc: "<pc_id>", cwd, agent, title}`: la PC dueña escribe su
`.cmd` y lo lanza, igual que «Cómo se lanzan» de SKILL.md pero del otro lado. `cwd` tiene que caer dentro
de `launch_roots` de esa PC (`config.json`; vacía o ausente es *ninguna* carpeta, no todas) y el
`agent` es uno de los cuatro conocidos (`claude`, `codex`, `pi`, `coda`). La tarjeta nueva aparece
después de un barrido: pedir `GET /peers` para saber qué `pc_id` usar, y buscar la tarjeta nueva
por `title` (o por `pc` + orden de aparición) una vez que el barrido corrió.

**`400 cwd fuera de launch_roots` también quiere decir «la carpeta no existe»** (`_cwd_allowed`
pide `isdir`; medido el 2026-10-04 con `D:\apps\chess` sin clonar y `launch_roots: ["D:/apps"]`). En
una PC esclava, la que el usuario no toca, no se le pide que vaya: se lanza una sesión auxiliar en
una carpeta que esa PC ya admite (las `cwd` de `restaurables(pc)`) con un pedido corto —crear la
carpeta vacía y, si hace falta, sumarla a `launch_roots` sin tocar otra clave— y se le manda `/exit`
al terminar. `launch.py` relee `config.json` en cada lanzamiento: no hace falta reiniciar el server.
El primer frente clona adentro (`git clone … .`).

Una carpeta nueva abre el diálogo de confianza de Claude antes que cualquier hook. Antes de
mandarle el encargo a una tarjeta recién lanzada, mirar `GET /sessions/<sid>/screen`: si muestra el
diálogo y `dialog` vino vacío, el lienzo no lo reconoció y el Enter del encargo elige la opción
marcada, que es «No, exit»: la sesión muere como `pid-N`, sin `session_id` ni nada que restaurar
(medido el 2026-10-04 con la variante sin números, «> No, exit / Yes, I trust this folder»).

Lanzar, encargar y cablear, en ese orden y en el mismo turno (el usuario lo marcó el 2026-10-09:
«lanzaste el CLI pero no le mandaste el encargo»):

1. `POST /sessions/launch`. Para `claude` la respuesta trae `native_name`, que sale del `title`.
2. La tarjeta aparece en unos segundos con `title` vacío y en `termino`: buscarla por `pc`, `agent`
   y `started` posterior al lanzamiento.
3. Mirar su pantalla por el diálogo de confianza (arriba) y mandarle el encargo con `send`.
4. Recién entonces la regla `on_stop` con `{respuesta}` y `repeat: true`. Antes del encargo, el
   primer `Stop` puede ser el de la sesión vacía, y con `max_fires: 1` se gasta ahí.

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
- **409 con `dialog_open`**: la tarjeta muestra un diálogo (el de confianza de Claude en una carpeta
  nueva, por ejemplo) y lo tecleado lo contestaría. Ese diálogo lo decide el humano: avisale, no lo
  aceptes vos ni lo esquives;
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

Si `ok` es falso, no seguir como si el frente trabajara: mirar `motivo`. El server deja el
rastro en `~/.lienzo/lienzo.log` (líneas `→ <pc> POST /sessions/…`); si no hay nada, el pedido no
salió de esta PC. Un envío a otra PC puede tardar hasta ~60 s (el timeout del reenvío ya lo
contempla).

### Repartir en otra PC: lo que ya salió mal una vez

- **Antes de abrir N sesiones, `coordinar.capacidad(pc, N)`**: mira la memoria libre de esa PC (cada
  sesión ocupa ~0,7 GB, y con menos de 1,5 GB de reserva Windows se arrastra). Si da `ok: False`,
  abrir menos y decírselo al usuario; no lanzar «a ver qué pasa». Para codas, `capacidad(pc, N,
  agent="coda")` cuenta además el cupo del modelo (dos corriendo a la vez por PC): lo que no entra se
  escalona.
- **Lanzar con `coordinar.lanzar_y_titular(pc, cwd, titulo, agent)`**: devuelve *la* tarjeta nueva y
  ya titulada. `lanzar` solo da el 200 y después hay que adivinar cuál de las tarjetas de esa carpeta
  es. No lanzar una sesión de prueba: queda abierta en la PC del usuario ocupando memoria.
- Todo frente sale cableado, siempre. Sin una regla `on_stop` hacia la coordinadora, el aviso de que
  un frente terminó (o se colgó) no llega solo y hay que consultarlo a mano. `lanzar_y_titular` ya crea
  esa regla por defecto (con `YO` fijado); para lo que ya estaba abierto, `coordinar.cablear(filtro=…)`.
  Al terminar la ronda, `borrar_reglas_hacia_mi()`. Antes de dar por andando un frente, comprobar que
  tiene su regla (`GET /rules` incluye las de otras PCs). Una tarjeta nace como `pid-N` y cambia a su id
  real al llegar el primer hook: el lienzo le traslada la regla solo.
- Una sesión sin hooks (coda, o recién barrida) cambia de id: nace `pid-NNNN` y al engancharse los
  hooks pasa a su UUID. Se la sigue con `coordinar.reubicar(s, sesiones())` (por pc + pid + cwd);
  `enviar_seguro` ya lo hace, y devuelve el `sid` vigente.
- Un agente puede colgarse sin decir nada (coda con el modelo del DGX quedó 5 min en «Waiting for
  model»). Mientras espera un encargo, `coordinar.estancada(s, minutos=5)` avisa si dice `corriendo`
  pero la pantalla no cambió. Entonces: interrumpir (`POST …/interrupt`) y reintentar, o pasar el
  trabajo a otro agente; no esperar indefinido.
- A un coda no se le manda un mensaje largo. Más de 500 caracteres o con saltos de línea el lienzo
  lo vuelve adjunto y el coda tiene que leerlo con su herramienta `read`, que se traba (medido: 4 codas,
  Qwen y GLM, más de una hora en «usando read»; uno ni respondía al `/exit`). Con un mensaje corto
  responde en 5 a 10 s y su herramienta de shell anda. Entonces: mensajes de menos de 500 caracteres y
  sin saltos de línea, y en el mismo mensaje «NO uses la herramienta read; leé con el shell (`type`),
  de a partes de 150 líneas». Un coda colgado que no responde al `/exit` se cierra pidiéndole a otro
  agente de esa PC un `taskkill /F /PID <pid>` de ese PID.
- El modelo se elige al lanzar: `coordinar.lanzar(pc, cwd, titulo, "coda", model="globant_dgx/GLM-5.3-Flash")`
  (también `lanzar_y_titular`). **Ojo: en coda el `--model` no vale solo para esa sesión: cambia el modelo
  por defecto de esa PC** (lo escribe en su `config.json`; medido el 2026-10-02: al lanzar un coda con
  GLM 5.3 Flash el default pasó de `Qwen3.8-27B` a GLM a las 00:52:18, y las sesiones lanzadas después
  «sin modelo» ya corrían GLM). Por eso no hay comparación de velocidad entre modelos que valga: si se
  quiere comparar, cada coda se lanza con su `model` explícito, y al terminar se vuelve a poner el
  default que tenía el usuario. Avisarle antes de cambiarlo.
- El encargo largo a otra PC va por mensaje: el server lo vuelve adjunto solo. Tecleado en una
  consola, un mensaje con saltos de línea o de más de 500 caracteres sería un Enter por línea; por eso
  el server lo guarda como `mensaje.md` en `~/.lienzo/adjuntos/<id>/` de la PC dueña y teclea una sola
  línea que apunta a él. Viaja por el lienzo, **sin git ni `pull`**. No hay límite de POST que lo
  impida (el cuerpo admite hasta 8 MB). Un archivo en el repo solo para lo que el agente de esa PC
  produce él mismo en su carpeta (p. ej. el `tasks.md` que escribió ahí): los demás lo leen sin pull.
  Un agente lento (coda) puede tardar en leer el adjunto: eso es el modelo, no la entrega.
- Metodología SDD (spec → clarificar → plan → tareas → análisis → código): un commit local por
  paso, y los módulos se reparten recién con `tasks.md` commiteado, cada uno en su carpeta.

Los dos lienzos tienen que correr el mismo código. Con `lienzo-server.cmd` el server se
reinicia solo cuando cambia un `.py` (un `git pull`), pero hay que haberlo levantado así una vez
en cada PC; un server viejo de la otra PC responde distinto y los envíos fallan sin explicación.
