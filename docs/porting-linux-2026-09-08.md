# Porting a Linux / Mac / WSL — estado e investigación (2026-09-08)

Trabajo en curso para que lienzo corra fuera de Windows y para que **un solo board vea los dos
mundos** (agentes de Windows + agentes de WSL). Rama `porting-linux`. Este doc resume lo hecho,
la arquitectura y —sobre todo— **los límites que investigamos**, para no volver a chocar con ellos.

Complementa a `docs/plan-multiplataforma-2026-09-08.md` (el plan de diseño, con el análisis de
Redis: recomendación *no*, una costura `bus.py` con default archivos).

## Lo que está hecho y verificado

- **`procinfo.py` aislado por plataforma**: el bloque Win32 (`ctypes.WinDLL`) solo carga en Windows;
  en Mac/Linux/WSL el módulo importa igual y las funciones Win32 devuelven "nada" sin reventar.
  Con esto **el server levanta en WSL** (`/health`, UI, `/auth`) — verificado, sin instalar nada
  (stdlib puro).
- **Backend tmux (`tmux.py`)**, equivalente Unix de `send.py` + `screen.py` + descubrimiento:
  - `send` → `tmux send-keys -t <pane> -l -- <texto>` + Enter
  - `screen` → `tmux capture-pane -p` (con scrollback, que Windows no tiene)
  - discover → `tmux list-panes` + una foto de `ps`
  - **Portable Mac + Linux**: la inspección de procesos va por `ps -axo` (sintaxis BSD que Linux y
    macOS comparten) y `os.kill(pid,0)`, **no** por `/proc` (que no existe en macOS). El cwd sale
    del pane (`pane_current_path`). Verificado en WSL; el `ps` es la sintaxis compartida con Mac.
  - **Defensa del pane reciclado** (`target_valid`): antes de cada envío se revalida que el pid del
    agente siga viviendo en ese pane; si tmux reinició y `%0` es otro pane, se rechaza (evita
    teclear en la terminal equivocada). Verificado.
- **Backend multi-fuente (`backend.py`)**: de "elegí una" a "sumá varias".
  - Windows: `win32` (procesos de Windows) **+** `wsl-tmux` (panes de WSL vía `wsl.exe -d <distro>
    tmux …`).
  - Mac/Linux: `tmux` nativo.
  - Cada tarjeta lleva `backend` ("win32" | "tmux"); las funciones rutean por ese campo. Sin campo,
    el primario de la plataforma.
- **Un board de Windows ve los dos mundos**: `backend.sweep()` agrega win32 + wsl-tmux. Verificado
  con claude **y** codex reales corriendo en tmux dentro de WSL, apareciendo en el board de Windows
  junto a los agentes de Windows.
- **Envío cruzado Windows → WSL**: mandé desde el board de Windows a un claude real en tmux de WSL,
  y contestó (leído por `capture-pane` vía `wsl.exe`). Loop completo.
- **`lienzo-server.sh`** (launcher Unix, equivalente del `.cmd`; el `.cmd` queda para Windows).
- Windows sin regresión: 102 pytest, ruff, black; y las 28 Playwright. WSL: smoke + recycle + loop.

## Cómo lanzar un agente para que el board lo vea

En Unix el agente **tiene que nacer dentro de tmux** (ver el límite abajo):

    tmux new -s trabajo claude      # (o: tmux new -s cx codex)
    # Ctrl+b, d  para salir sin cerrarlo ; tmux attach -t trabajo  para volver

## El límite de fondo (y por qué)

En Windows, lienzo maneja agentes que corren normalmente porque `AttachConsole(pid)` deja que
cualquier proceso se enganche a la consola de otro por PID. **En Unix eso no existe**: un PTY es de
quien lo creó (la terminal), y no hay forma soportada de que otro proceso le escriba o le lea la
pantalla a un agente que ya corre suelto. Por eso, en Unix:

- **Escribirle** a un agente → tiene que estar en **tmux** (que sí da ese acceso, por diseño).
- **Leerlo** (conversación, estado) → **no** necesita tmux: sale del proceso (`ps`), su cwd
  (`/proc` en Linux/WSL, `lsof` en Mac) y su transcripción `.jsonl`. *(Esta "fuente de procesos
  sueltos, solo lectura" está diseñada pero todavía no cableada — ver Pendiente.)*

### TIOCSTI — investigado, descartado por defecto

El único mecanismo para inyectar en una terminal ajena (sin tmux) es el ioctl `TIOCSTI`. Medido en
este WSL2 (kernel `6.18.40.1-microsoft-standard-WSL2`): **`dev.tty.legacy_tiocsti = 0`**, o sea
**desactivado**. Lo apagaron por defecto en los kernels modernos por seguridad (CVE-2017-5226:
cualquier proceso podía inyectar comandos en cualquier terminal del usuario). Se puede reactivar
(`sudo sysctl -w dev.tty.legacy_tiocsti=1`), pero **es bajar una defensa**, no una solución nueva.

### El reemplazo seguro de TIOCSTI = ser dueño del PTY desde el arranque

No hay —ni va a haber— una forma *segura* de agarrar una terminal que ya corre: esa capacidad es
justo lo que se consideró inseguro y se sacó. Lo que la reemplaza no inyecta desde afuera,
**interpone** un PTY propio: correr el agente bajo un multiplexor (tmux/screen) o un PTY que uno
controla. Es la recomendación textual de los del kernel al sacar TIOCSTI. Opciones seguras:

1. **tmux** — ya hecho, probado, cero downgrade. Su único costo: el agente nace adentro.
2. Un **wrapper PTY propio** (`lienzo run claude`): mismo principio, sin instalar tmux, pero es
   **reimplementar tmux** (incluido un parser vt100 para la pantalla). Mucho laburo para rehacer lo
   que tmux ya hace bien. Recomendación: no reinventarlo; esconder tmux detrás de un `lienzo new`.

## Multi-distro de WSL

Cada distro es un mundo aparte (su tmux, su filesystem, su `~/.claude`, su espacio de PIDs). Hoy el
prefijo es `wsl.exe` (distro default, Ubuntu). Para ver **varios** distros: una fuente por distro
(`wsl.exe -d <distro> tmux …`), con la identidad = distro + pane (los PIDs no son únicos entre
distros). La arquitectura multi-fuente ya lo permite; no está armado porque hoy se usa un solo
distro.

## Transcripciones de WSL desde Windows (verificado)

`\\wsl.localhost\<distro>\home\<user>\.claude\projects\<slug>\*.jsonl` se lee desde Windows, y
`claude_slug(cwd)` de un cwd de WSL (`/mnt/d/Apps/lienzo` → `-mnt-d-Apps-lienzo`) coincide con el
nombre del directorio de proyecto. O sea el puente de conversación para los agentes de WSL es
factible (falta cablearlo).

## Pendiente

- **Fuente de procesos sueltos (solo lectura)**: mostrar los claude/codex de WSL/Mac que corren
  fuera de tmux, con su conversación (por `ps` + `\\wsl.localhost` / `~/.claude`), marcados "sin
  consola" (como las apps de escritorio). Diseñado, no cableado.
- **Puente de transcripciones de WSL** (B2): título y pestaña Conversación para las tarjetas de WSL.
- **Helper `lienzo new "<tarea>"`**: esconder tmux en un comando (agente visible + escribible).
- **Pantalla de codex**: usa pantalla alternativa; `capture-pane -p` la trae vacía (probar `-e`).
- **Mac real**: no verificable sin un Mac; el `ps` usado es la sintaxis compartida BSD/Linux.
