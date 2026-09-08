# Cómo hablarle a Codex/Claude: monitor vs orquestador, y qué técnica sirve para qué

Análisis de las formas de interactuar con las CLIs de agentes (Claude Code, Codex CLI) y cuál
encaja en lienzo, a raíz de la discusión sobre TIOCSTI. La conclusión corta: **hay dos productos
distintos, y la técnica correcta depende de cuál estés haciendo.** Confundirlos es el error que hace
parecer que a lienzo "le falta" usar `claude -p`, cuando en realidad eso resuelve otro problema.

## Los dos productos

1. **Monitor (lo que es lienzo).** Vos ya estás trabajando **interactivo** con claude/codex en tu
   terminal (VS Code, Windows Terminal, PowerShell): conversás, iterás, aprobás. Lienzo **mira esas
   sesiones vivas y te deja empujarlas** desde un board o el celular. El humano maneja; lienzo
   observa y contesta. **No lanza los agentes: adopta los que ya corren.**

2. **Orquestador (otro proyecto).** Un programa que **corre** Codex y Claude en modo headless y los
   encadena por su salida JSON, sin TUI y sin humano interactivo en el medio (Claude genera → Codex
   revisa → Claude corrige → …). El programa **lanza** los agentes y los maneja como una API.

La distinción que ordena todo es **adoptar lo que ya corre** (monitor) vs **lanzar y controlar**
(orquestador). Casi toda la confusión viene de mezclar las dos.

## Las técnicas, y qué hace cada una

| Técnica | ¿Adopta un proceso YA corriendo? | ¿Lee pantalla? | ¿Escribe input? | SO |
|---|---|---|---|---|
| **`AttachConsole` (Win32)** | **Sí** (por PID) | sí | sí | Windows |
| **tmux** | no — el agente **nace** adentro | sí (`capture-pane`) | sí (`send-keys`) | Unix (Mac/Linux/WSL) |
| **TIOCSTI** | sí (tty ajena) | no | sí (1 char a la vez) | Unix, **apagado por seguridad** |
| **PTY spawn** (`openpty`/`forkpty`/`pexpect`/`node-pty`/**ConPTY**) | **no** — controla lo que **vos** spawneás | sí | sí | todos (ConPTY = Windows) |
| **Headless** (`claude -p`, `codex exec` + `--json`/`stream-json`) | **no** — corrida **nueva** | N/A (salida estructurada) | prompt de entrada | todos |
| **`--resume` / `-c` / `codex exec resume`** | **no** — continúa una sesión en una invocación **nueva** | N/A | prompt | todos |
| **Transcripción `.jsonl` + hooks** | **sí** (solo lectura) | — (contenido, no pantalla) | no | todos |

Dos hechos que se derivan de la tabla y que son la clave:

- **Leer** el contenido de una sesión viva (conversación, estado) es **fácil y agnóstico del SO**:
  sale de la transcripción `.jsonl`, los hooks y —si se quiere la pantalla— del buffer. Sirve para
  cualquier agente corriendo, esté o no en tmux. Es el camino de lectura de lienzo, y ya anda en los
  tres sistemas.
- **Escribirle** a una sesión viva es lo difícil, porque hay que **alcanzar su entrada**. Y ahí solo
  hay tres palancas: `AttachConsole` (Windows), tmux (Unix, si nació adentro) o TIOCSTI (Unix
  suelto, inseguro). **Ninguna de las técnicas de "lanzar" (PTY spawn, `-p`, `--resume`) sirve para
  esto**, porque todas arrancan un proceso nuevo en vez de adoptar el que ya está vivo.

## Por qué `claude -p` / `codex exec` / node-pty NO son el fix de lienzo

Son excelentes —y el consejo que los propone tiene razón— **para el orquestador**. Para el monitor
no aplican al núcleo:

- **`claude -p` / `codex exec`** spawnean una corrida **nueva y aparte**: no es *tu* sesión
  interactiva, la que estás mirando. Sería otro proceso, con otra pantalla y otro `session_id`.
- **`--resume` / `codex exec resume`** continúan una sesión en una invocación **nueva**; no se
  enganchan a la interactiva que ya está viva. Una sesión tiene **un solo dueño**: dos procesos
  sobre el mismo `session_id` chocan, y la TUI del usuario no vería el mensaje inyectado por el
  headless. Así que no sirve para "hablarle a la que tenés abierta".
- **node-pty / ConPTY** controlan un proceso que **ellos** spawnean; no adoptan el claude que ya
  abriste en VS Code. Es exactamente el límite del PTY: podés ser dueño desde el arranque, no
  después.

O sea: para el trabajo de lienzo (empujar **la sesión viva que estás mirando**), el consejo no abre
una palanca nueva, porque todo lo suyo es **spawnear**, no **adoptar**.

## Dónde SÍ encaja cada cosa en lienzo

- **Adoptar tu sesión interactiva (el núcleo):** Windows → `AttachConsole` (ya está). Unix → tmux si
  el agente nació adentro; suelto, solo lectura. TIOCSTI queda como opción insegura, apagada por
  defecto (ver el README). No hay atajo headless para esto.
- **`lienzo new` (lanzar bajo control):** acá sí vale un PTY propio. tmux es el elegido (multiplexor
  hecho y probado, con pantalla/scrollback/detach gratis). **node-pty/openpty es una alternativa
  legítima** si algún día no se quiere exigir tmux, a costa de reimplementar el parser de pantalla.
- **Automatizar sin humano:** eso ya es el orquestador, no lienzo.

## El orquestador, si se hace, es otro proyecto

Si el objetivo fuera hacer que Codex y Claude se hablen **automáticamente**, la arquitectura correcta
es la que dice el consejo —y no toca TUIs ni TIOCSTI—:

```
Orquestador (TS/Python)
  ├─ claude -p --output-format stream-json  "…"     # o --resume <id> para mantener contexto
  └─ codex exec --json                       "…"     # o  codex exec resume --last
        ↓  eventos JSON/JSONL
   encadenar: Claude genera → Codex revisa → Claude corrige → Codex tests → DONE
```

Ventajas: usa el login actual de las dos CLIs (sin API keys), mantiene sesiones con `--resume`, y es
una API de facto sobre las propias CLIs. **Pero no es lienzo**: es "IA que le habla a IA por corridas
headless", sin la sesión interactiva del humano en el medio. Son herramientas distintas y las dos son
válidas; conviene no pedirle a una que sea la otra.

## Recomendación

- **Lienzo** se queda con su premisa (monitor de sesiones vivas) y sus palancas: `AttachConsole` en
  Windows, tmux en Unix, lectura para todo lo demás. TIOCSTI documentado como opción que baja una
  defensa, no como algo que lienzo use.
- Si aparece la necesidad de **automatizar** Codex↔Claude, armarlo como **proyecto aparte** con
  `exec`/`-p` + JSON. Ahí el consejo es la guía correcta, palabra por palabra.
