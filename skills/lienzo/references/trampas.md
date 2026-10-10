# Trampas medidas

Parte de la skill `lienzo` (se lee desde `SKILL.md` cuando hace falta).

## Trampas medidas

### Recursos compartidos entre frentes

Varios frentes en una máquina comparten candados, semáforos, puertos, bases y números correlativos
(migraciones, versiones). Lo que salió mal, en general:

- **Un candado o turno no se pide desde adentro de otro del mismo tipo.** Un comando que ya pide su
  turno, envuelto en otro pedido del mismo semáforo, espera un turno que nunca se libera si el
  dueño de los demás es él mismo, y con el candado tomado traba a todos los que esperan detrás. El
  semáforo tiene que negarse a anidar (marcar el turno en el entorno y cortar si ya está), y el
  encargo común lo dice: «no envuelvas en el semáforo un guion que ya lo usa».
- **Un servidor de larga vida no se queda con un turno.** Un servicio levantado adentro de un turno
  lo retiene mientras viva; con pocos turnos, dos servidores de frentes distintos dejan a la
  máquina sin ninguno para las pruebas. El servidor va fuera del semáforo, con sus puertos propios.
- **«Esperando el candado» dos veces seguidas es para mirar, no para esperar.** La coordinadora
  revisa quién lo tiene (`fuser -v <candado>`, `pstree -ap <pid>`) y desde cuándo; un dueño dormido
  con el candado tomado es un bloqueo, no una cola.
- **Un número correlativo se asigna al frente que lo va a usar, cuando lo pide.** Reservar uno para
  un frente que todavía no arrancó deja un hueco en la cadena, y el siguiente que lo use apunta a
  algo que no existe; en migraciones eso rompe la base de prueba de todos. La coordinadora lleva la
  lista y contesta el número al que lo pide.
- **Un frente que muta archivos compartidos para probar (mutaciones) avisa antes y pide el árbol
  quieto**; la coordinadora no commitea ni edita hasta que el frente confirme los archivos
  restaurados por huella. Los demás frentes, mientras tanto, no lanzan pruebas que copien el árbol.
- **Un archivo de referencia de una prueba que cambia un solo dígito** sin que nadie lo explique es
  una mutación que no se restauró: se vuelve a la versión del último commit antes de buscar el bug.

### El sistema donde corren los frentes

- **WSL apaga la distro cuando no queda ninguna sesión `wsl.exe` abierta**, y con ella caen las
  bases, las APIs y los servidores de desarrollo de todos los frentes; adentro se ve como un
  reinicio (`last -x`: shutdown y boot) y los procesos lanzados con `nohup` mueren sin dejar rastro.
  Mientras dure una ronda, la coordinadora deja abierta una sesión oculta:
  `Start-Process wsl.exe -ArgumentList '-d','<distro>','--','sleep','infinity' -WindowStyle Hidden`.
- **El nombre de la distro cambia entre PCs** (`Ubuntu`, `Ubuntu-24.04`): un encargo a otra PC no lo
  da por sentado; se mira con `wsl -l -q`.
- **Un comando con `!` corre en la PC de la sesión donde se escribe.** Para que el usuario corra
  algo en otra PC, se lo escribe en la terminal o la tarjeta de un frente de esa PC.
- **El clasificador de permisos frena por su cuenta lo destructivo y lo que toca secretos** (borrar
  una rama sin mergear, reescribir un archivo de claves), aunque el usuario lo haya autorizado en el
  chat. No se rodea ni se le teclea a otra sesión: se le pide al usuario que lo corra con `!` en la
  terminal de esa PC.

- **Las preguntas de CODA (`ask_user`) no se veían en el tablero** hasta el 2026-10-09: con
  auto-aprobar prendido el hook las dejaba pasar como un permiso más y la tarjeta seguía en
  `corriendo`. Ahora la tarjeta pasa a «Te hace una pregunta» con el texto, y se contesta en la
  terminal. Una PC con el lienzo anterior sigue sin mostrarlas: actualizarla (`git pull` y reinicio).
- **«Lanzar CLI» solo ofrece carpetas dentro de `launch_roots` de la PC elegida**, porque el server
  rechaza las demás. Con `launch_roots` puntuales (una por proyecto) la lista «Usadas estos días»
  casi no tiene nada que agregar; con una raíz amplia (`D:/apps`) muestra cada proyecto usado.
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

- Un comando con barra inyectado en una consola ocupada no se ejecuta. Queda como texto encolado
  y se pierde. Mandar `/model` o `/clear` solo a sesiones que no están corriendo, y **verificar el
  efecto**, no el envío: para `/model`, el campo `model` de la última respuesta en el transcript.
- **Después de un `/clear` la sesión cambia de `session_id`** y la tarjeta vieja desaparece. Hay que
  volver a buscarla, esperando unos segundos y con un `/rescan` en el medio.
- **Las reglas `on_stop` necesitan `repeat: true`.** Sin eso disparan una vez y quedan apagadas, y
  los frentes que cierran dos veces avisan solo la primera.
- Los ecos. Cada vez que un frente cierra un turno la regla dispara, aunque no haya terminado su
  trabajo: muchos avisos son "cerré un turno", no "cerré el frente". Se distingue mirando si escribió
  su informe. Durante una pausa larga conviene apagar las reglas y volver a armarlas después.
- El auto-continuar del tablero reactiva las sesiones detenidas y les escribe "Continuar" en la
  caja. Si el usuario está tipeando en su terminal en ese momento, la palabra se le mete adentro de la
  frase. Está en `GET /config`.
- Una pausa hay que pedirla explícita: "terminá lo que tenés, no empieces nada, y si te llega
  Continuar respondé una línea". Sin eso siguen trabajando.
- Los permisos pendientes vencen a los 60 segundos y después el prompt aparece en la terminal.
- Un peer caído no avisa activamente: se nota porque su chip en la tira pasa a ○ (sin memoria ni
  temperatura, sería un dato viejo) y sus tarjetas quedan grises con los controles deshabilitados a
  los 45 s sin novedades de esa PC. No hay push de "se cayó fulano": hay que mirar la tira.
  El chip caído dice por qué (`diagnostico` en `GET /peers`): «sin ARP» es que la PC no aparece en
  la red: apagada, dormida, en otra red, o un Wi-Fi público con aislamiento de clientes (medido el
  2026-10-05 en «YPF Clientes 2»: ni el broadcast ni el barrido unicast lo saltan). Primero
  preguntar si la otra PC está prendida y en la misma red (el 2026-10-07 lo era: casa, sin
  aislamiento). Solo si lo está, el aislamiento: Tailscale en las dos PCs (misma cuenta) o un
  hotspot. Si las dos están en la misma LAN, Tailscale sobra: el espejo prefiere la LAN. Con Tailscale el
  lienzo encuentra la IP 100.x solo y cambia de dirección sin hacer nada; hace falta
  `install.py --peer` de nuevo, como administrador, para la regla de firewall de la tailnet.
  «el puerto está cerrado» es que no corre el lienzo allá; «no contesta el puerto» es el firewall.
  Si una PC entra a esta por Tailscale (el log tiene `peer GET /peer/events de <pc_id>`) pero esta no
  llega a la otra, a la otra le falta el código nuevo: `git pull`, `install.py --peer` como
  administrador y reiniciar el lienzo (ya hecho en las dos PCs; los pasos quedaron en el historial de git como `docs/tailscale-otra-pc.md`). `tailscale status`
  muestra la 100.x de cada PC. Por Tailscale solo va el tráfico a las IP 100.x; lo demás sigue igual.
  En una PC del trabajo, que el usuario le pregunte a IT antes de instalarlo y apague MagicDNS
  ahí: no decidirlo por él.
- **`/clear` en una sesión de otra PC se busca por `pid` *y* `pc`**, no sólo por `pid`: dos PCs
  distintas pueden tener el mismo número de PID sueltos por casualidad, y buscar sólo por `pid`
  después de un `/rescan` puede encontrar la tarjeta de la PC equivocada.
- **Nadie corre `git stash` en un árbol compartido, ni para "comparar contra HEAD"** (medido el
  2026-09-26, ronda 2: un `stash` para mirar un test viejo se llevó puesto el trabajo sin commitear
  de cuatro sesiones a la vez, y el `pop` posterior chocó con una edición concurrente y quedó sin
  aplicar). Para ver una versión vieja de un archivo sin tocar el árbol: `git show HEAD:<archivo> >
  <algo>`, nunca `stash`/`checkout`/`reset`.
- **Una tarjeta en `te_necesita` sin nada en `GET /pending` tiene el permiso en la pantalla.** Una
  regla `ask` de Claude Code (por ejemplo `Bash(rm -r*)`, «Ask rule … overrides auto mode») no pasa
  por el hook de permisos: aparece como diálogo numerado en la terminal, y `/pending` sigue
  mostrando sólo lo vencido. Se lee con `GET /sessions/<sid>/screen` (el comando completo está en
  `dialog.detail`) y se contesta con `POST /sessions/<sid>/dialog {choice}`. **Leer el comando antes
  de contestar**: el 2026-10-04 un frente pidió así `rm -rf /d/Users` en la PC esclava (desde Git
  Bash, `D:\Users` entero) para limpiar una carpeta que había creado por error; la respuesta fue «No» y
  un mensaje con la ruta exacta a borrar después de listarla.
