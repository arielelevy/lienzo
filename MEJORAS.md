# Mejoras del lienzo, anotadas a medida que se usa

Registro vivo: cada vez que repartir trabajo con el lienzo (sobre todo entre PCs) muestra un
tropiezo o una idea, se anota acá con la evidencia, y cuando se arregla pasa a «Hecho». La fuente
de cada punto es una sesión real, no una suposición. Última actualización: 2026-10-02.

## Hecho

| Fecha | Mejora | Evidencia / motivo |
|---|---|---|
| 2026-10-01 | **Recarga automática del server**: `lienzo-server.cmd` lo relanza (salida 75) cuando cambia un `.py`; no relanza sobre código que no compila | había que parar y levantar el `.cmd` a mano tras cada `git pull`; la otra PC quedaba con código viejo |
| 2026-10-01 | **Timeout de 70 s** para `send`/`launch`/`attach` entre PCs (antes 5 s) | un envío tarda hasta 60 s en teclear; con 5 s aparecía como «sin conexión» aunque se hubiera tecleado |
| 2026-10-01 | **Tarjeta fantasma**: si la otra PC dice «sesion desconocida», el server la saca del tablero y pide el estado de nuevo | los envíos a una tarjeta que ya no existía rebotaban para siempre |
| 2026-10-01 | **Reintento solo si el pedido no llegó** (conexión rechazada); un timeout NO se reintenta | reintentar tras un corte a mitad podría teclear el texto dos veces |
| 2026-10-01 | **Log de reenvíos que fallan** (`→ <pc> POST …`) | no quedaba rastro de nada en el origen; no se podía saber si el pedido había salido |
| 2026-10-01 | `coordinar.enviar_seguro`: verifica que la tarjeta tomó el encargo y se recupera de 404/503 | un `200` solo dice que el server aceptó, no que se tecleó |
| 2026-10-02 | `enviar_seguro` **rechaza caracteres de control** en el texto | una ruta `D:\apps` sin escapar llegó como `D:<BEL>pps` y el server borró el carácter sin avisar: 4 codas buscaron rutas que no existían |
| 2026-10-01 | `coordinar.reubicar`: sigue a una tarjeta cuando cambia de id (`pid-NNN` → UUID) | `enviar_seguro` dio un falso negativo con el coda, que cambió de id al engancharse los hooks |
| 2026-10-01 | `coordinar.estancada(s, minutos)`: detecta un agente colgado (pantalla sin cambios y `corriendo`) | el coda quedó 5 min en «Waiting for model» y nadie lo vio |
| 2026-10-01 | `coordinar.capacidad(pc, n)`: mira la memoria libre antes de abrir sesiones | la otra PC tenía 0,76 GB libres con 6 codas abiertos |
| 2026-10-01 | `coordinar.lanzar_y_titular`: devuelve la tarjeta nueva, ya titulada | `lanzar` solo da el 200; hay que adivinar cuál tarjeta es la nueva |
| 2026-10-02 | **Cableado entre PCs**: reglas `on_stop` de los frentes de la otra PC hacia la coordinadora (5 reglas, cruzan PC) | no había nada cableado: la coordinadora tenía que consultar cada frente a mano |
| 2026-10-01 | `SKILL.md`: secciones «Mandar un encargo a otra PC…» y «Repartir en otra PC: lo que ya salió mal una vez» | todo lo anterior, para que la próxima ronda no repita los tropiezos |
| 2026-10-02 | **Selección múltiple con Ctrl** en el tablero: Ctrl+click suma o saca tarjetas; en los chips de proyecto y de PC suma o saca del filtro (varios a la vez); barra con «Marcar las visibles», «Enviar a todas», «Interrumpir» y «Limpiar»; Esc pela una capa por vez | pedido del usuario; 20 pruebas Playwright nuevas |
| 2026-10-02 | Las pruebas de interfaz **ya no dependen del server real**: sin `peers` simulados, `/peers` devuelve lista vacía (antes caía al server, que ahora tiene un peer emparejado) | `pcs.spec.ts:58` fallaba solo porque la PC tiene un peer; la de emparejamiento esperaba la frase vieja de 6 palabras |
| 2026-10-02 | **A un coda, el adjunto se lee con el shell**: el aviso del mensaje largo le pide leerlo con `type` y no con `read` (que se traba en coda) | 4 codas colgados más de una hora en «usando read»; con mensajes cortos y lectura por shell las mismas revisiones terminaron en 2 min |
| 2026-10-02 | **Las reglas pasan de la tarjeta provisional `pid-N` a la real**: antes solo se trasladaban en `continue_session` | un agente recién lanzado y cableado perdía su regla al llegar su primer hook |
| 2026-10-02 | **`lanzar_y_titular` cablea por defecto** la tarjeta nueva a la coordinadora | tres codas lanzados sin regla: no avisaban al terminar |
| 2026-10-02 | Elegir el modelo al lanzar (`--model`, coda, claude y codex) | usar GLM 5.3 Flash en la otra PC (ojo: en coda el `--model` cambia el modelo por defecto de esa PC, ver Pendiente) |
| 2026-10-02 | **Firma sin query**: `signed_headers` firma la ruta sin `?…`, como la verifica el receptor | `/turns` y `/digest` de una tarjeta de otra PC daban 401 «firma invalida» porque el emisor firmaba `?n=…` |
| 2026-10-02 | **El aviso `on_stop` de coda espera 15 s y se cancela si la tarjeta volvió a trabajar** (la coda sí manda hooks: el Stop llega en medio de un turno) (`ON_STOP_SETTLE_S` en `lienzo/rules.py`) | la regla avisó «terminó» de B y de E cuando seguían trabajando (Stop intermedio: compactación o hueco entre herramientas; causa exacta sin confirmar) y la coordinadora leyó un `last_reply` viejo |
| 2026-10-02 | **Compactación de coda**: `install.py` registra `PreCompact` y `PostCompact`; la tarjeta queda marcada «compactando» (vence a los 10 min) y ni el `Stop` ni `on_stop` cuentan como fin de turno | B y E mostraron «terminó» mientras compactaban; el doc de coda (`hooks.md`) lista esos dos eventos |
| 2026-10-03 | **Los botones Permitir/Denegar de coda vuelven** si el permiso sigue abierto 20 s después de contestar (`CODA_SENT_RETRY_S`): la marca `where: "enviado"` los escondía para siempre | la tarjeta de D tuvo un permiso real abierto horas sin botones; el usuario: «no me aparecen los yes en lienzo» |
| 2026-10-03 | `coordinar.cablear` y `regla_informe` **fallan claro si `YO` está vacío** | con `YO` vacío el server contestaba 404 «sesion destino desconocida» y parecía que la tarjeta nueva no existía |
| 2026-10-03 | **Un 401 entre PCs dice el motivo y qué hacer**: `federation.causa_401` mide el reloj contra el `Date` de `/peer/hello` y el error queda «la otra PC no acepta mi firma (…). Reiniciá su lienzo; si sigue, reemparejá» | a las 20:02 todo dio «firma invalida» pelado y el tablero quedó mudo |
| 2026-10-03 | **El encargo largo a una coda se ejecuta**: el aviso del adjunto le pide ejecutar sin resumir ni pedir confirmación | las codas de las sesiones 3 y 4 resumieron el encargo y esperaron un segundo «arrancá» |
| 2026-10-03 | `coordinar.informe(s)`: el `last_reply` solo si es un informe (None con «usando bash» o mientras corre) | la coordinadora confundía el estado de herramienta con el informe |
| 2026-10-03 | **Aprobador oficial con lista permitida** (`skills/lienzo/aprobador.py`, `Politica` + `vigilar`): frena lo truncado, lo peligroso, rutas, `rm` y pushes no autorizados | los permisos largos se revisaban a mano y dos aprobadores sueltos en Temp tuvieron bugs (tramo vacío, `rm` de varios destinos) |
| 2026-10-03 | **Temperatura en cualquier PC**: `health` lee todas las zonas térmicas (y `MSAcpi` si hay permisos) y elige `\_TZ.THRM` o, si no está, la zona plausible más caliente (25–120 °C) | la otra PC no tiene `\_TZ.THRM` y su `temp_c` quedaba siempre en None; esta PC marcó 95 °C |

## Pendiente (con evidencia)

- **La tarjeta se queda en «Te necesita» con un permiso que ya no existe** (medido el 2026-10-02): la tarjeta del Claude del gestor
  mostró durante unas 16 horas «Pide permiso» con el comando de un ruff de un subagente, desde un aviso (Notification) de las 05:06,
  aunque en su terminal no había ningún cartel. Ese permiso lo había aprobado yo hacía horas y la marca no se limpió. Confunde a
  quien mira el tablero y a la coordinadora, que gasta consultas en revisar. Los permisos de los subagentes (forks) de Claude Code
  salen en la terminal del Claude principal y el tablero no los distingue. Idea: cuando el estado dice permiso en la terminal
  y la pantalla ya no muestra el cartel («Do you want to proceed?» o «Enter confirm»), limpiar `needs` y volver al estado real.
- **Coda: `stop_reason` del Stop sin mirar** (medido el 2026-10-02): el `Stop` trae `stop_reason` y el doc solo muestra
  `turn_complete`; ver qué otros valores existen (respuesta cortada que continúa, error) y usarlos en vez de adivinar.
- **Probar `PreCompact`/`PostCompact` con una coda real**: solo hay prueba con eventos simulados, y falta correr
  `install.py` en las dos PCs para que coda los mande (toca `~/.coda/config.json`).
- **`--coda-home DIR` aísla la configuración de coda** (está en `coda --help`): sirve para lanzar con `--model` sin pisar el
  modelo por defecto de la PC (ver el punto de `--model`). Falta ver cómo conserva el login.
- **Reiniciar lienzo en la otra PC cierra las codas que corren** (medido el 2026-10-03): la coda de la sesión 3 quedó
  `ended_at` en el mismo segundo del reinicio y hubo que restaurarla (`restaurar`, con contexto). Además, con la causa sin
  resolver, todo lo que sale hacia esa PC dio `401 firma invalida` de repente (sin cambios de reloj ni de claves) y solo se
  arregló reiniciando su lienzo. Ideas: que las codas no cuelguen del proceso del server, y que ante un 401 el lienzo
  intente el reinicio del peer o avise con el motivo («su server no valida mi firma»), en vez de dejar el tablero mudo.
- **La herramienta `read` de coda se traba** (medido el 2026-10-02): se evita (el adjunto a un coda se lee con
  el shell y los mensajes cortos se tipean directo), pero la causa sigue en coda: avisar a quien lo mantiene.
- **`--model` en coda cambia el modelo por defecto de la PC** (medido el 2026-10-02): `coda --model X` se
  documenta como «para esta corrida», pero el `config.json` de esa PC pasó de `globant_dgx/Qwen3.8-27B` a
  `globant_dgx/GLM-5.3-Flash` a las 00:52:18, justo al lanzar el primer coda con GLM, y las sesiones
  lanzadas después sin modelo ya mostraban GLM. Efectos: se pisa el default del usuario sin que lo sepa
  y las comparaciones entre modelos no valen (la medición «Qwen contra GLM» de esa noche fue GLM contra
  GLM). Ideas: que `lanzar` con `model` avise si el agente es coda, que el lienzo lea el default antes
  y lo restaure al terminar el lote, o lanzar con un `--coda-home` propio para aislar la configuración
  (hay que ver cómo conserva el login).
- **El lienzo no puede cerrar un agente colgado de otra PC**: `/exit` queda en cola y `interrupt` no
  alcanza si el proceso está clavado. Hoy hubo que pedirle a otro coda un `taskkill` por PID. Idea:
  `POST /sessions/<sid>/kill` que la PC dueña ejecute sobre su propio PID (con la misma
  confirmación que las demás acciones destructivas).
- **Latencia entre PCs**: un pedido mínimo a la otra PC tarda ~86 ms (mediana, p95 136 ms) contra 2,5 ms
  local; la pantalla de una tarjeta remota, ~470 ms. Cada pedido abre una conexión TCP nueva y firma
  con HMAC. Idea: conexión persistente (keep-alive) por peer y cachear `screen` unos 500 ms.
- **El SSE del peer se corta y reconecta cada ~15 s** (`peer GET /peer/events` en el log cada 15 s).
  Funciona, porque cada reconexión trae el snapshot entero, pero es tráfico de más y una ventana en
  la que el espejo se reemplaza. Hay que ver si el server corta el stream a propósito.
- **`launch_roots` no se ve desde la otra PC**: `peers.json` no lo trae y no hay forma de saber qué
  carpetas permite un peer sin intentar lanzar. Mostrarlo en `GET /peers`.
- **Log de los reenvíos que andan bien**: hoy solo se loguean los que fallan. Sumar la latencia
  (ms) de cada reenvío ayudaría a ver una PC que se vuelve lenta.
- **(Revisar: desactualizado) «Coda no tiene hooks»**: el 2026-10-02 las codas figuran `hooked=True`; antes nacía como tarjeta de barrido (`pid-NNNN`, sin título ni
  transcripción), cambia de id, y su estado no refleja que está trabajando. Un hook de coda daría
  título, estado y `last_reply` confiables.
- **Un solo modelo para todos los codas**: Qwen en el DGX atiende de a poco; con 5 codas a la vez
  todos quedan en «Waiting for model». El coordinador tiene que escalonar el trabajo, no repartirlo
  en paralelo sin límite. `capacidad` mide RAM, no el cupo del modelo.
- **Traspasar un encargo entre PCs**: copiar y pegar trabajo entre tarjetas funciona dentro de una
  PC; entre PCs no hay forma de mover un encargo a una tarjeta de la otra.
- **Persistir las reglas cruzadas si la otra PC reinicia**: una regla vive en la PC del `from`; si
  esa PC reinicia el lienzo, hay que ver que sobreviva (hoy se guardan en `~/.lienzo`, falta probarlo
  con un reinicio real).
- **Pruebas reales pendientes** (solo se probaron con transportes simulados): recuperación cuando una
  tarjeta remota ya no existe, y el reintento ante conexión rechazada.
- **Capacidad de memoria duplicada**: `restore_capacity` en `lienzo/server.py` (1,5 GB de reserva, 0,7
  por sesión) y `coordinar.capacidad` en `skills/lienzo/coordinar.py` (`reserva_gb=1.5`,
  `gb_por_sesion=0.7`) repiten las mismas constantes. Que el skill se las pida al server.
- **Detectar el lienzo viejo de la otra PC por capacidades**: hoy se reconoce por el texto «ruta
  desconocida» de la respuesta (`cablear` y el reenvío). Un campo de capacidades en el handshake
  (`/peer/health` o el emparejado) sería un contrato; el texto cambia sin avisar.
- **`xpc` + `purge_stale_xpc` con hilo y reloj fijo**: la purga corre en un hilo con un reloj fijo y
  una regla hacia otra PC solo guarda el flag `xpc`. Guardar `to_pc` en la regla y conciliar por peer
  al aplicar su snapshot: hoy un peer apagado frena la purga de las reglas hacia los demás.
- **El espejo se reconcilia por rebote**: una tarjeta fantasma se detecta cuando un envío vuelve con
  `unknown_session` (`mirror.forward` → `_tarjeta_fantasma`). Debería reconciliarse con un snapshot
  periódico o una secuencia en el SSE, no esperar a que alguien escriba.
- **`drop_session(sid, reason)` usa el texto como protocolo**: `restore_on_drop` hace
  `reason.startswith("muerta")` (`lienzo/sessions.py`). Pasar a un parámetro o un enum.
- **`ended_on_purpose` es una lista negra de razones** (`lienzo/restore.py`, `_NOT_ON_PURPOSE`): una
  razón nueva de SessionEnd de Claude Code se tomaría como salida voluntaria y la sesión no se
  restauraría. Invertir a lista blanca de las razones conocidas de salida voluntaria.
- **El enrutado owner→forward está repetido en ~10 handlers de `lienzo/server.py`** (`_route_session`
  + `mirror.MIRROR.forward` en cada ruta de `/sessions/<id>/...`): una sola función `route_or_local`.
- **`restorables_all` y `cablear` consultan en serie**: una PC lenta o caída suma su timeout al de las
  demás. Paralelizar las consultas por peer.
- **Timeout de acciones lentas por sufijo de ruta** (`SLOW_ACTIONS`, `RESTORE_ACTION` y
  `_timeout_para` en `lienzo/federation.py`): una ruta nueva lenta se olvida y cae en los 5 s.
  Pasar el timeout como parámetro de `forward`.

## Ideas

- Un panel «PCs» con la latencia y la memoria libre de cada una en vivo, y la cola del DGX.
- `coordinar.repartir(proyecto, modulos, pcs)`: reparto automático según `capacidad`.
- Aviso en el tablero cuando una tarjeta lleva N minutos `corriendo` sin que cambie su pantalla.
