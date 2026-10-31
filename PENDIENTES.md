# Pendientes del lienzo

Esta es la única lista de trabajo. El [historial importado de MEJORAS.md](#historial-mejoras)
conserva hechos y decisiones con su fecha; DISENO.es.md describe la arquitectura y
docs/PRODUCTO.md las decisiones de producto.

Fecha: 2026-10-10. Última actualización: 2026-10-22.

- [ ] **2026-10-30 · FDD no aparece al arrancar una sesión.** *Implementado, sin integrar (encargo F, 2026-10-30): creencia propuesta `e3f51fc7ec064c0aa14ed8ad00d3385c` en `lienzo` (alcance proceso_lienzo; falta el veredicto de Ariel para que llegue al SessionStart y a `c.encargo`), y SKILL.md y `references/fdd.md` lo dicen.* El skill dice que el proceso es FDD (leer
  `references/fdd.md` y `docs/dominio.md` antes de repartir), pero en una coordinadora de openSeec que leyó `SKILL.md`
  a mano para lanzar frentes se pasó por alto: las creencias que inyecta el hook SessionStart no lo recuerdan y el
  `AGENTS.md` del proyecto no lo menciona. Propuesta: una creencia vigente «antes de repartir una feature: ficha FDD,
  dominio y dueños» y que `c.encargo` la pegue. Origen: ronda 0.19.0 de openSeec.
- [ ] **2026-10-30 · Verificar que el encargo llegó después de lanzar.** *Implementado, sin integrar (encargo F): `enviar_seguro(confirmar=True)` y `lanzar_y_titular(texto=…)`; ficha `.temp/coordinacion/2026-10-30/fdd-confirmar-que-el-encargo-entro.md`.* Un coda lanzado a mano recibió el `send`
  (200) antes de terminar de arrancar y se quedó 30 min en su portada con la entrada vacía hasta el aviso de «sin
  avance». Propuesta: `lanzar_y_titular` (o un `c.enviar_seguro`) confirma en el transcript o la pantalla que el texto
  del encargo entró, y si no lo reenvía una vez. Origen: ronda de cierre 0.18.0 de openSeec.
- [ ] **2026-10-30 · Evidencia citada antes de limpiar `.temp/coordinacion/`.** *Implementado, sin integrar (encargo F): `c.limpiar_coordinacion(repo, dias)`; ficha `.temp/coordinacion/2026-10-30/fdd-limpiar-coordinacion-sin-borrar-evidencia.md`.* La coordinadora de openSeec borró días
  viejos de `.temp/coordinacion/` y con ellos el arnés y la evidencia de una prueba de localidad citada por un contrato.
  Propuesta: una ayuda `c.limpiar_coordinacion(dias)` que antes busque esas rutas citadas en el repo (contratos,
  fichas, informes) y se niegue a borrarlas sin confirmación.
- [ ] **2026-10-30 · `POST /sessions/launch` con `agent: coda` no encuentra `coda.exe`.** *Implementado, sin integrar (encargo F): `_exe_path` busca `~/.coda/bin`; necesita reiniciar el server.* Contesta 400
  `no encuentro coda.exe en esta PC` aunque existe `~/.coda/bin/coda.exe` (donde lo deja el instalador).
  `lienzo/launch.py:230` `_exe_path` busca `~/.local/bin` y el PATH del server, no `~/.coda/bin`. Reproducir:
  `coordinar.lanzar_y_titular(None, "D:/Globant/source-analisis", "x", agent="coda")`. Salió de la ronda
  de compilación de source-analisis (Globant); se lanzó a mano con `explorer.exe` + `.cmd`.
- [ ] **2026-10-30 · Buscador del encabezado móvil recortado.** A 390 px, el placeholder
  `buscar /` de `web/src/components/Header.tsx:92` se ve como `bus…`, con Chrome remoto y
  Authenticator visibles. Reproducir con `CAPTURAS=1`, caso `capturas.spec.ts` → `celular`;
  evidencia en `docs/img/celular.png`. Visto al renovar las capturas públicas; revisar el ancho
  del buscador y la distribución del encabezado sin esconder controles. Pendiente de cambio de UI.

### Release 0.6.18 (2026-10-27)

Notas en [docs/releases/0.6.18.md](docs/releases/0.6.18.md). Suite completa en ar-it33940: 3898 en verde, 27
omitidas y 8 fallas, ninguna nueva (seis también en 0.6.17, dos inestables que pasan aisladas).

**Condición para 0.6.19 (pedido de Ariel, 2026-10-27):** estas ocho se corrigen antes; la 0.6.19 no sale con la
suite completa en rojo.

- [ ] **Guardar un nodo de memoria tarda 70-94 ms** (`test_conocimiento_prolog_commit::test_hook_encola_sin_exportar_en_hilo_de_escritura`,
  límite 50 ms). Mide `crear_nodo` hasta su retorno: escritura, commit y aviso al worker de Prolog. Frena la
  cola de captura, no a los agentes. Medir primero dónde se va el tiempo y después recortar.
- [ ] **`briefing` y `preguntar` con 200 nodos y 400 vínculos tardan 500-660 ms** contra 200
  (`test_veredictos::test_rendimiento_briefing_y_preguntar_con_200_nodos_y_400_vinculos`). Ya en 0.6.17.
- [ ] **`test_prolog_servicio::test_deadline_cubre_write_con_hijo_que_no_lee`**: el `stdin.write` bloquea fuera
  del plazo de 0,15 s en ar-it33940. Ya en 0.6.17.
- [ ] **Tres pruebas de xfer quedan en «copiando» en ar-it33940** (`test_copia_arbol_y_la_segunda_vez_no_manda_nada`,
  `test_solo_viaja_el_bloque_que_cambio`, `test_mismo_tamano_y_fecha_no_alcanzan_para_saltear`), también en
  0.6.17; una reproducción tardó 1216 s sin respetar el tope de 150 s. Acá pasan. Y dos (`test_espejo_lista_antes_y_borra_solo_con_confirmacion`,
  `test_sin_espejo_nunca_borra`) fallan sólo dentro de la suite completa. Investigar qué deja la copia sin terminar.

### Propuesta FTD, constitución y OKF (2026-10-26)

Decisión de Ariel del 2026-10-26: FTD reemplaza a SDD y, el mismo día, FDD (skill `fdd`) reemplaza a
FTD; conservar la exigencia proporcional al alcance, sin imponer una ficha a cada cambio puntual. Regla
operativa en [FDD](skills/lienzo/references/fdd.md) y mapa en [docs/dominio.md](docs/dominio.md). No se
cerraron tareas por esta decisión.

- [ ] Evaluar constitución + FTD por feature, memoria con procedencia y versión,
  herramientas reutilizables e intercambio OKF como mejoras de Lienzo. Relevar primero
  las capacidades existentes y definir una feature piloto.
  **Evaluado el 2026-10-26** contra el código en 9646336, propuesta por propuesta:
  constitución + ficha por feature, cubierta por FDD (`references/fdd.md`, piloto medido);
  revisión separada, cubierta (code review obligatorio y el revisor de `consulta`); medición de
  intervención y retrabajo, en parte (`c.trabajo`, `turn_usage.py` y la medición del piloto FDD).
  Quedan como mejoras nuevas, abajo: memoria con versión del código, ficha enlazada al encargo,
  exportación OKF y catálogo de herramientas. Investigación y fuentes en
  `PROPUESTA-FTD-OKF-RSC.md` (raíz local de cada PC, fuera de Git a pedido de Ariel). Sin implementación
  ni cierres automáticos.
- [ ] **Memoria con la versión del código.** Las evidencias y creencias de `conocimiento.sqlite` no
  guardan el commit (los «commit» del módulo son de SQLite): una sesión puede tomar como integrado algo
  de una rama sin integrar. Agregar HEAD y rama a cada evidencia que habla de código, y que la consulta
  distinga propuesto, en una rama e integrado. Sale de la evaluación RSC/OKF del 2026-10-26.
- [ ] **Ficha FDD enlazada al encargo.** `coordinar.encargo(...)` registra el encargo en la memoria pero
  no sabe de la ficha `fdd-<nombre>.md`; sumarle la ruta de la ficha para que la sucesora la encuentre
  desde la tarjeta. Sale de la evaluación RSC/OKF del 2026-10-26.
  Implementado el 2026-10-26 por el frente B en ar-it33940 (Codex) e integrado por la coordinadora:
  `c.encargo(..., ficha=".temp/coordinacion/<fecha>/fdd-x.md")` la guarda en `datos.ficha` y la
  devuelve al leer el nodo; las rutas fuera de `.temp/coordinacion/` dan 400. 98 pruebas de conocimiento,
  coordinación y memoria en verde. Ficha: `.temp/coordinacion/2026-10-26/fdd-enlazar-ficha-al-encargo.md`.
  Falta mostrarla en la tarjeta del tablero. Sin cerrar: lo cierra Ariel.
- [ ] **Exportación OKF de prueba.** No hay ninguna exportación a OKF (Markdown con frontmatter YAML,
  `index.md`, `log.md`). Piloto: exportar las creencias vigentes de un proyecto, con versión explícita,
  y comprobar que un lector independiente (Obsidian o un script) las interpreta. Sin migrar el
  almacenamiento. Sale de la evaluación RSC/OKF del 2026-10-26.
- [ ] **Catálogo de herramientas reutilizables.** Hoy están dispersas (`coordinar.py`, `run_allowlist`,
  los scripts de `pruebas-agenticas/`); una lista consultable por proyecto evitaría rehacer scripts.
  Sale de la evaluación RSC/OKF del 2026-10-26.
- [x] **FDD para IA: sumar a FTD piezas de Feature-Driven Development y publicarla como skill propia**
  Cerrado por Ariel el 2026-10-26: publicada en https://github.com/arielelevy/fdd (v0.1, MIT); Lienzo la
  sigue desde becc90e; piloto medido (43 % menos tokens de entrada con el mapa, 5/5 en ambas).
  (pedido de Ariel, 2026-10-26). Mapa del dominio vivo, features con nombre de resultado, avance por
  hitos (diseñado, implementado, verificado, integrado; el último lo marca Ariel) y archivos con dueño
  en la ficha. Piloto en una feature real de Lienzo midiendo cuánto contexto necesita una sesión nueva
  para retomar, con y sin mapa. Después del piloto: repo nuevo en `arielelevy`, MIT, citando RSC como
  fuente de FTD. Ficha: `.temp/coordinacion/2026-10-26/ftd-fdd-ia.md`.

Actualización documental: 2026-10-16. No se cerraron casillas al consolidar las specs.

### Bug reportado desde opensyync-K (2026-10-25, pedido de Ariel)

- [x] **Un borrado rechazado apaga la regla en silencio y se pierden los informes siguientes.**
  Cerrado por Ariel el 2026-10-26 (b35f0e8, opción A, piloto de `fdd`): el 409 sigue con `conservada` y suma
  `desactivada` y `pendientes`; `coordinar.borrar_reglas_hacia_mi()` avisa las desactivadas,
  `reglas_apagadas_hacia_mi()` las lista y `regla_informe` dice por qué rechaza y cuál es la regla que ya existe.
  El punto (c) sigue abierto como pendiente aparte (abajo). Ficha:
  `.temp/coordinacion/2026-10-26/fdd-avisar-regla-apagada.md`.
  `DELETE /rules/<id>` con un informe sin acuse responde 409 `{"error": "No se puede borrar: hay informes
  pendientes de integrar.", "conservada": true}`. Pero `rules.retirar_regla` deja la regla en `enabled: false`
  (`disabled_reason: "borrado rechazado: …"`). La coordinadora lee «conservada» como «no cambió nada» y ningún
  `on_stop` posterior sale. Medido en opensyync: la regla L→K `86e3c2375798` quedó apagada de 22:42 a 23:57,
  y el informe final de L (`ESTADO: L3 entregado…`) nunca llegó. Ariel lo detectó a mano.
  Arreglo propuesto: (a) si el borrado se rechaza, no deshabilitar y seguir entregando; o, si se deshabilita,
  responder 200/202 con `{"desactivada": true, "pendientes": [...]}` y que el texto lo diga. (b) `coordinar.py`
  debería avisar cuando una regla hacia `YO` queda `enabled: false`. (c) La auditoría de sesiones ociosas
  («idle_evitable») podría cruzar el último turno con `ESTADO:` contra las reglas apagadas y avisar «informe no
  entregado».
  Relacionado: `regla_informe(..., solo_si=…)` sobre un par que ya tiene regla devuelve 409 sin decir cuál es
  la existente ni ofrecer actualizarla (`PUT /rules/<id>` con `solo_si` sí funciona).
- [ ] **Avisar desde la auditoría cuando un informe no se entregó** (punto (c) del anterior): en
  `lienzo/auditoria.py`, cruzar `idle_evitable` y el último turno con `ESTADO:` contra las reglas apagadas
  hacia la coordinadora (`coordinar.reglas_apagadas_hacia_mi()` ya las lista).
  Implementado el 2026-10-26 como hallazgo `informe_no_entregado`: respeta el `solo_si` de la regla, no
  avisa si el informe se entregó antes de que la regla se apagara, ve reglas que quedaron en una
  coordinadora anterior y deja pasar un bloqueo declarado. 29 pruebas de auditoría y E2E contra el lienzo
  real (`pruebas-agenticas/fdd-hoy.json`) en verde; falta baseline y aprobar las mutaciones propuestas.
  Sin cerrar: lo cierra Ariel.
- [ ] **`/exit` con trabajo en segundo plano no se puede cerrar desde el lienzo.** Claude muestra «Background
  work is running… 1. Exit and stop tasks / 2. Move to background / 3. Stay». `GET /screen` lo detecta como
  `dialog` y la tarjeta queda `te_necesita`, pero `POST /sessions/<sid>/responder {opcion:1}` contesta 409 «la
  pregunta ya no está abierta» y `send` también da 409. Visto en opensyync, sesión N (Sonnet), con un monitor de
  turno vivo. Arreglo: que `responder` acepte los diálogos de pantalla (Enter u opción) y no sólo los permisos.

### Ronda 0.6.17 (2026-10-25, coordinadora a480da47 en ar-it33940)

- [ ] **Prolog en ar-it33940**: `test_prolog_checklist` y `test_prolog_ciclo` fallan también sobre las fuentes de
  0.6.16 (`git archive c02061c`, 9 fallas focales). Causa: `prolog_servicio` lee la salida del motor en WSL como
  UTF-8 y llega una tilde en otra codificación (`'utf-8' codec can't decode byte 0xf3`). Ver la locale del WSL o
  leer con el encoding que declara el motor.
- [ ] **Frente huérfano** (pedido de Ariel): si desaparece la sesión que lanzó o coordinaba a un frente, el frente
  tiene que tomar el control: marcarse coordinadora, ponerse el título y recablear las reglas de los otros.
- [ ] **Sugerir la marca de coordinadora**: «opensyync | sesión» mandó 36 encargos a 6 sesiones y recibió 28
  informes sin estar marcada. Proponer la marca cuando una sesión es destino de 2 o más reglas `on_stop` y origen
  de envíos a 2 o más sesiones del repo.
- [ ] **Tokens por turno en la memoria**: la captura de `respuesta` no guarda el `usage`; para comparar consumo
  entre CLIs hay que leer los transcripts de cada PC (`D:/apps/bench-clis/2026-10-25/analisis_logs.py`).
- [ ] **Headless y memoria del proyecto**: un `claude -p` de un benchmark dispara los hooks y crea proyectos
  `sin_remote` por carpeta temporal. Ignorar las carpetas bajo `%TEMP%`.

### Revisión total de V (2026-10-22, `review/2026-10-22/code-review-total.md`)

Corregidos: T1, T2, T4, T5, T6, T8, T9 y T10 (0.6.14), T3 y T11 (0.6.15) y T7 (eventos que fallan al aplicarse van a `events/cuarentena` en vez de borrarse).

Otros abiertos de esta ronda:
- **La regla `on_stop` de una sesión Kiro no avisa** (reportado por OpenSyync, 2026-10-22). La sesión
  `sess_0f7b8931` (encargo J) tiene la regla `57e6f928c13d`, con `fired` en 0 aunque terminó dos veces con
  informe. El log dice «salteado: el turno respondía un envío sin_aviso» a las 22:33 y a las 22:34. Esa noche se
  corrigió la causa en Claude: un acuse a mitad de turno pisaba `last_prompt` y callaba la entrega, y ahora no
  arma `sin_aviso` (`review/2026-10-22/code-review-on-stop-sin-aviso.md`). Falta confirmar que Kiro tenía la
  misma causa: los envíos de las 22:31:32 y las 22:34:17 pudieron empezar su propio turno. Hace falta una
  prueba con dos turnos Kiro seguidos.
  Verificado el 2026-10-23 (encargo B): con dos turnos Kiro y un acuse intermedio avisan los dos; la guarda
  de `accion_send` (no arma `sin_aviso` con turno en curso) cubre también a Kiro, y sin ella falla igual que
  en Claude. Prueba en `tests/test_optimizacion_trabajo.py`. Queda sólo si se repite con una Kiro real.
- **`pedir_turno` de una sesión coda contesta 404 «sesion desconocida»** (reportado por OpenSyync, 2026-10-22).
  `c.pedir_turno("motores", "31108cdc-b4ec-43b3-bf6c-468df377c2d2")`, desde el encargo H de OpenSyync, dio 404.
  Antes, con el mismo patrón, la misma sesión había obtenido el turno (200). Hipótesis: después de un reinicio del
  server o un cambio de id, el registro de turnos no la encuentra por el id que tiene ahora.
  Diagnóstico del 2026-10-22 a las 23:40: la coda `31108cdc` recibió un envío de 5 caracteres a las 23:14:38,
  murió y su tarjeta se borró a las 23:15:40 («muerta hace mas de 60 s»). Su pid 32212 hoy es otro proceso.
  Con la sesión muerta, el 404 es correcto. Queda abierto sólo si se repite con una coda viva.

### Consultas a la coordinadora del repo (2026-10-24, encargo F)

- [x] Una pregunta de trabajo de un frente (`ask_user` de coda, `AskUserQuestion` de Claude, diálogo de opciones
  que no es permiso, confianza ni cambio de modelo) va a la ★ viva de su repo, una vez por pregunta, con la flecha
  desde la tarjeta; la ★ contesta con `POST /sessions/<sid>/responder {opcion|texto}` (`c.responder`), que relee
  la pantalla antes de teclear y también se reenvía a la PC dueña. `responder` llamado a propósito contesta
  cualquier diálogo abierto, y el 409 `dialog_open` nombra la ruta. Medido con codas reales. Dos revisiones de
  código (20 hallazgos) corregidas. Pedido de Ariel: «sólo la coordinadora de ese repo puede saber».
- [ ] Avisar en la salud si hay un `codex.exe` en `~/.local/bin` más viejo que el del instalador
  (`%LOCALAPPDATA%/Programs/OpenAI/Codex/bin`): esa copia arranca un Codex sin `codex-code-mode-host.exe` (cart, 2026-10-24).

### Ola del 2026-10-23 (sólo codas)

- [ ] `tests/test_aprendizaje_proyecto.py::test_sin_sesion_elegida_toma_la_viva_mas_reciente_del_proyecto` falla a
  veces en la suite completa con **404** (no encuentra el proyecto `q-sugerido`), no por el orden de sesiones; pasa
  20/20 sola (coda D). Falta ver qué prueba anterior deja el registro de proyectos o la base en otro estado.
- [ ] `tests/test_downloads.py::test_lista_recientes_no_incluye_incompletos_y_rechaza_token_alterado`: intermitente,
  20/20 sola; sin causa encontrada.
- [x] `POST /rules/<id>/informes/<inf>/acuse` sólo busca reglas locales: para una regla de otra PC (un frente
  lanzado allá y cableado hacia acá) contesta 404 «conexion desconocida» y no se reenvía, así que la regla no se
  puede borrar (409 «informes pendientes»). Visto con `d7cfef6a7b18` y `f47a87fc9ef4` el 2026-10-23.
  Hecho el 2026-10-23: el tablero lo reenvía a la PC dueña (`/peer/rules/<id>/informes/<inf>/acuse`); hace
  falta que esa PC corra la 0.6.16.
- [ ] La suite completa en ar-it33940 dio 3551 passed y 65 failed (`test_research_creencias`, `test_veredictos`,
  `test_xfer`, entre otras) con el mismo `HEAD` que acá pasa: falta el log completo para ver si es el entorno.

### Decisiones de Ariel del 2026-10-22 que agregan trabajo

Fuente: `.temp/coordinacion/2026-10-22/decisiones-ariel.md`.

- [ ] ar-it33940 siempre disponible (decisión 11): Lienzo arranca al iniciar sesión y la PC no se suspende
  enchufada; sin inicio de sesión automático. Ver la medición del 2026-10-23 más abajo.
- [ ] Cierres del plan multi-PC con ar-it33940 real (decisión 21): aprobar un permiso de allá desde acá,
  lanzar un frente con la ★ y que el informe vuelva solo, regla real de firewall de `install.py --peer`.
  Medido el 2026-10-23 (`.temp/coordinacion/2026-10-23/encargo-A-multipc.md`):
  - Lanzar en ar-it33940 desde acá y que el informe vuelva solo por la regla `on_stop`: anda.
  - Firewall: en ar-it33940 no existe ninguna de las 4 reglas de `install.py --peer`. El peer anda por 4
    reglas genéricas de `python.exe` (entrada, públicas y privadas, cualquier puerto): falta correr
    `install.py --peer` como administrador allá y después revisar si sobran las genéricas.
  - Aprobar un permiso de allá desde acá: sin probar (la sesión corría en auto mode y no pidió ninguno).
  - Bug: el nombre nativo de una sesión de ar-it33940 llegó como `11/rename lienzo-A-ar-it33940`. Quedaron
    dos «1» tecleados en el prompt (¿el auto-aprobar o un diálogo contestado dos veces?) y el `/rename` se
    tomó como texto. Hecho el 2026-10-23: `answer_dialog` relee la pantalla también con el número (antes
    podía teclear «1» con el permiso ya cerrado), `/native` difiere si la caja no está vacía, y la caja de
    una sesión renombrada (la raya de arriba lleva su nombre) ahora se reconoce (`screen.es_regla`).
- [ ] ar-it33940: el lienzo no arranca solo (ni carpeta Inicio, ni tarea, ni Run); el server de hoy se lanzó
  a mano. No se suspende enchufada (STANDBYIDLE 0 en CA). Decisión 11 pendiente de aplicar. Además el server
  escucha en la IP del Wi-Fi (192.168.1.63): si DHCP la cambia hay que reiniciarlo.
- [x] Chrome de Globant en ar-it33940 (decisión 25): misma receta que el Chrome de Ariel (bandera de oclusión
  en accesos directos y «Allow remote debugging») y verificar la vista por pestañas.
  Hecho según Ariel (2026-10-22): ese Chrome ya tiene la bandera y la vista anda.
- [ ] Investigación semanal de herramientas de la comunidad (decisión 8), con Claude y propuestas para decidir.
- [ ] coda real de Globant (decisión 14): `PreCompact`/`PostCompact` y la herramienta `read`.
- [ ] Lista de comprobación de uso real (decisión 16): puntero, checkbox de descargas, flujo nativo,
  portapapeles de la ventana completa, clics con la PC bloqueada, `marcas` entre las dos PCs.
- [ ] Revisar las 3 propuestas del investigador (G) y los 60 candidatos del contraste lógico.
- [ ] Confirmar si `ledsage` y `gmi-global` son proyectos propios (Azure sólo para propios).
- [x] Limpiar las marcas «headless» que quedaron en tarjetas vivas antes de 19747a2 (la de J siguió dando 409
  a `/send`; el arreglo evita marcas nuevas, no borra las viejas).
  Hecho en 2936cde (2026-10-22): el barrido le saca la marca a una TUI viva con consola.
- [ ] El espejo toma como dirección de un par la IP de origen del beacon, no las IPs que el par anuncia firmadas
  (hallazgo 5 del code review de K, cambio de diseño en la federación).
  Diseño entregado el 2026-10-23, sin código: `review/2026-10-23/diseno-B-beacon-firmado.md` (beacon
  extensible compatible con el viejo, migración por etapas). Falta medir el modo mixto y DHCP en las dos PCs.
- [x] El acceso de emergencia (3dbe685) no aparece para ar-it33940 caída: `/peers` trae `emergencia: null`
  aunque el diagnóstico dice «cambió de red» y su nodo Tailchrome `ar-it33940-lienzo` existe (offline). Medido el
  2026-10-22 ~16:00. Además, el ayudante de Tailchrome de ar-it33940 no se reconectó solo tras cambiar de red.
  Hecho en 2936cde (2026-10-22): el par caído recibe su canal con lo último que se supo de él. Sigue abierto
  aparte que el ayudante de Tailchrome de ar-it33940 no se reconecta solo tras cambiar de red.
- [x] El nombre nativo del CLI no sigue al título de la tarjeta: una tarjeta que nace de copiar y pegar (copycat) o a
  la que se le cambia el título con `PUT /sessions/<sid>/title` queda con `native_name: None` y la consola con el
  nombre viejo. Esperado: al heredar o cambiar el título, hacer `/rename` + `/remote-control` (lo de `/native`) apenas
  la sesión quede quieta. Visto por Ariel en la coordinadora de OpenSyync (sid 56cfac40), 2026-10-22.
  Hecho en 73399de (2026-10-22, frente Y): `native_follow.py` lo publica con la sesión quieta; verificado en
  vivo el 2026-10-23.
- [x] Cerrar una sesión con la acción «cerrar» del tablero (`POST /sessions/<sid>/kill` con confirmación) dispara
  el aviso «murió sin terminar su encargo… restaurala». Un cierre pedido por una persona o la coordinadora no tiene que
  avisar como muerte inesperada. Visto con U y X, 2026-10-22.
  Hecho el 2026-10-23: la tarjeta queda `cerrada_a_mano` y su muerte no se avisa.
- [ ] Benchmark de CLIs (claude, codex, coda, pi, kiro) por costo y por tipo de tarea, para elegir el agente de
  cada encargo (decisión vigente en la memoria de `lienzo`, nodo 89ab95ed). Primero, medir o estimar el tamaño de
  cada tarea (archivos y líneas tocadas, tipo de trabajo, criterio de aceptación); sin eso comparar costos no dice nada.
  Pedido de Ariel vía la coordinadora de OpenSyync, 2026-10-22; no urgente.
  - Dato de OpenSyync (2026-10-22). Coda (GLM-5.3-Flash vía DGX):
    - **Rindió bien** en 9 encargos cortos de código o artefactos con criterio explícito: bump de versión,
      oráculos, tope de suite, redacción 17, 5 arreglos de G y la UI de la tabla. Todos verificados contra el árbol.
    - **Falló en investigación abierta en internet.** Tres turnos seguidos cerró diciendo «voy a buscar» sin buscar
      ni escribir nada, aunque se le partió la tarea; la investigación pasó a un subagente.
    - **Commiteó una vez** en un árbol compartido, contra lo que decía el encargo.
- [ ] Una coordinadora reabierta a mano sin el mismo título no recupera sus reglas (efecto buscado de 19747a2):
  evaluar un «adoptar reglas de…» explícito en la tarjeta.

### Ronda nocturna del 2026-10-21/22 (cerrada el 2026-10-22)

Pedido de Ariel: «terminá todo lo pendiente», con la otra PC prendida. Frentes A–F y R, todos Claude
(Codex al 89 % semanal). Commits en `main` desde `ddc5d49`; release 0.6.8 publicada y aplicada en las
dos PCs. Coordinación y evidencia: `.temp/coordinacion/2026-10-21/ronda-noche/coordinacion.md` y
`.temp/resultados/noche-*/`; revisiones en `review/2026-10-21/code-review-noche-*.md`.

- Cerradas con evidencia: reimportación legacy, sincronización de memoria por `marcas`, Codex tras
  `/new`/`/clear`, cola de Codex al cerrar, contrato de plugins, latencia LAN del canal Chrome, panel de
  PCs (sin cola DGX), aviso de tarjeta quieta.
- Hecho sin casilla previa: vista por pestañas de Chrome con screencast (25 c/s, anda con la PC
  bloqueada sobre el Chrome real), tablero al ~81 %, auto-aprobar como pestaña sin confirmación,
  cuadros de error de Windows apagados para los hijos del server, borrado del espejo por handle,
  falla WSL atribuida a `systemd-tmpfiles` sobre `/tmp`, título del launch en la tarjeta, limpieza de
  `~/.lienzo/launch`, partición de `sessions.py` (`hooks_eventos.py`) y código muerto borrado.
- Error de la coordinadora: `64fb252` salió con `launch.py` importando un módulo no commiteado;
  corregido en `4014c88` antes de que alguna PC actualizara.

### Estado de la ronda del 2026-10-20 (consolidado el 2026-10-21)

Retoma del 21/10 después del reinicio: correcciones locales de xfer para firmar
después de conectar y para interrumpir la espera del límite de red/disco al
pausar, devolviendo el presupuesto reservado. Cuatro regresiones finales aprobadas,
incluido el caso de reanudación sincronizado tras confirmar un archivo real.
La corrida amplia previa a la segunda corrección dio 2977 backend aprobadas,
una fallida (pausa/reanudación) y diez omitidas; frontend lint/build/unitarias
y 139 recorridos UI aprobados. La causa de esa falla concreta no está acreditada.
La focal posterior dio 176 aprobadas, dos fallidas y seis omitidas: repitió la
pausa/reanudación antes de corregir la precondición del caso y el fallo WSL de
bloque aceptado/cierre 409 con ceros. El experimento WSL no confirmó truncate
como causa; la sonda nativa posterior pasó tres casos sin capturar el fallo.
Se conserva toda la evidencia; WSL sigue abierto. No hay PASS global,
despliegue, reinicio, reanudación de copias ni casillas cerradas.
[Revisión y límites](review/2026-10-21/code-review-estabilidad-retoma.md).

Actualización del 21/10, 12:13: 0.6.4 está publicada. Las dos PCs informaron
`phase=current`, `busy=false` y `running=eb3ee09c5f45b02efb5dffba310b4eac314e9578`.
Incluye la foto transaccional del importador SQLite y el diagnóstico de posición
del mouse; no acredita que el incidente remoto esté resuelto. La observación
posterior del visor quedó sin ejecutar por timeout del controlador del navegador.
Evidencia: `.temp/coordinacion/2026-10-21/release-0.6.4-actualizacion-verificada.json`.

La sonda WSL de limpieza/conservación terminó con rc 0: 8/8 precursores,
8/8 objetivos y 4/4 limpiezas, sin reproducción. No se activó la observación
Linux condicionada al primer fallo. Conserva abiertos los fallos históricos de
`NtCreateFile`, `NtSetInformationFile` y `GetFileInformationByHandle`; no es PASS global.
Evidencia: `.temp/resultados/E-wsl-frio/linux-c882cb8bf7c5487b99bc14145421a800/informe.md`.

El 2026-10-21 Ariel autorizó publicar 0.6.0 con el fallo WSL conocido y continuar su
diagnóstico después. No acredita PASS global ni cierra los pendientes. La focal posterior
al arreglo de reanudación dio 50 aprobadas, 1 fallida y 6 omitidas: bloque 200/cierre 409
y 38 bytes cero en el parcial. El cierre rechazado y el WinError 2 anterior siguen abiertos.

Actualización del 21/10: 0.6.1 está publicada y ambas PCs informaron `current`,
`running=b62a9a78cb8cd216ae533bfe7c3549ca7859dc6e`, sin actualización en curso.
La PC remota volvió a responder después de que Ariel la conectó mediante Tailchrome.
Esto acredita versión y conexión, no la corrección del puntero en uso real.
La nueva focal WSL sin instrumentación dio 1 fallida y 2 aprobadas: cierre 200,
lectura del archivo final disponible y posterior `GetFileInformationByHandle` con
`WinError 2`. Una sonda posterior dio 3 aprobadas sin reproducirlo; no sustituye el fallo.
Evidencia: `.temp/coordinacion/2026-10-21/wsl-retoma/informe.md`.

Estos avances no cierran casillas ni acreditan aceptación, activación o PASS global.
Las notas anteriores conservan su fecha; este corte actualiza sus límites para esta ronda.

- **Chrome:** 0.5.5 remoto verificado según el encargo y la coordinación; el parpadeo persistía.
  El contrato nuevo sin emulación está probado localmente y con Chrome real aislado:
  104 backend, 25 Node y 37 UI; no está publicado ni probado con visor remoto real.
  Zoom/pinch sigue sin medir. UI y remota deben publicarse juntas por el cambio de dimensiones.
  Evidencia: `.temp/coordinacion/2026-10-20/A-chrome/entrega-final.md` y
  `.temp/coordinacion/2026-10-20/coordinacion.md`. La prueba remota de 0.5.5 no certifica el contrato nuevo.
- **Antigravity:** lector parcial probado: 258 backend (56 del lector), 6 UI y lectura real
  de 36 pasos, 3 turnos, 3 bloques de texto y 14 de herramientas del único agy 20088.
  Historial parcial, `history_only: true`, `ended: false`; `terminalOnly`, fin y `on_stop`
  siguen bloqueados. Lectura inicial anterior a la activación: no se persistieron respuestas.
  Evidencia: `review/2026-10-20/code-review-2026-10-20-antigravity-reader.md`.
  El 2026-10-21 se activó el código local sin publicar y se verificó una nueva prueba única:
  pantalla/API/Chat con respuesta exacta, turnos 4→5, cero herramientas y PID estable.
  Sigue `history_only`, sin cierre acreditado. Evidencia: `.temp/coordinacion/2026-10-20/E-verificacion/AGY-informe.md`.
- **Prolog:** 102 backend con SWI-Prolog 9.0.4 real en WSL, 0 salteos y 12 UI con fixtures.
  El contraste real dio 0 diferencias y no cambió las huellas del grafo. Los 60 candidatos
  carecen de evidencia de una persona; eso no acredita utilidad general ni aceptación.
  Falta release coordinado y gate global. Evidencia: `review/2026-10-20/code-review-2026-10-20-prolog-contraste.md`.
- **Memoria:** foto fija con token implementada y probada en el lote 8: 256 focales y 27 UI;
  runner parcial rc=0, igual al baseline existente, sin fijar uno nuevo. Las fotos vencen a
  los 600 s y se pierden al reiniciar; 410 pide repetir la búsqueda. No hay activación acreditada.
  Evidencia: `review/2026-10-20/code-review-2026-10-20-memoria.md`.
- **Cancelación del investigador:** revisión independiente y 228 pruebas `test_optimization_*`
  aprobadas, incluidas 9 de carreras. No se usó la cola real ni se midieron procesos reales.
  Evidencia: `.temp/coordinacion/2026-10-20/C-memoria/review-cancelacion-raiz.md`.
- **Dot:** faltan contexto real, comando, PID y error exacto reproducible. Las sondas desde shell
  no prueban acceso desde Dot. No se cambiaron permisos, exenciones, cuentas ni proxy.
  Evidencia: `.temp/coordinacion/2026-10-20/D-antigravity/dot/diagnostico-dot.md`.
- **Azure:** deployment `gpt-6.1-sol` creado, versión 2026-09-29, GlobalStandard 50K TPM,
  `arielfoundry`, suscripción `f056467d-cfb4-4c52-b115-21123ef7f888`.
  El diseño registra una llamada mínima que respondió `OK`; el adaptador pagado del investigador
  no está activado. Presupuesto, credencial, alcances y ledger requieren decisión explícita.
  Se respeta el rechazo de persistencia de key, sin bypass ni nuevas llamadas pagas.
  Evidencia: `.temp/coordinacion/2026-10-20/D-antigravity/azure/diseno-azure-aprendizaje.md`.

### Brechas actuales de integración y aceptación

- [ ] Verificar el control de flujo nativo preparado para0.6.3 en uso remoto:
  ACK real, un hover en vuelo y última posición pendiente, IDs crecientes,
  bloqueo sin replay y liberación al blur/cambio. Cinco casos nuevos y44UI
  de producción aprobados; revisión independiente sin bloqueantes nuevos.
  No acredita resolución del puntero ni del clic físico del checkbox.
  [Revisión](review/2026-10-21/code-review-flujo-ventana-nativa.md).

- [ ] Verificar selección de descargas desde ar-it33940 al traer archivos de ariel.
  Ariel informa que no puede marcar el checkbox. Se midió un blanco de13×13px;
  cambio local: casilla24×24px y selección por nombre con label nativo.
  Regresión roja previa y4 recorridos UI verdes; ESLint y build aprobados.
  Sigue sin atribuirse el fallo remoto: se observó además rechazo de foco de Windows.
  No hay copia real nueva ni despliegue remoto de este delta acreditado.
  [Revisión](review/2026-10-21/code-review-seleccion-descargas.md).
  En0.6.3 se observó selección por nombre desde la otra PC; el clic directo
  no quedó acreditado. Prueba posterior:6ACK y1rechazo de posición Windows,
  un solo hover en vuelo; entrada bloqueada sin replay. Diagnóstico local nuevo
  distingue lectura fallida y mismatch, añade coordenadas/límites sin modificar
  restricciones:68pruebas aprobadas. Falta observarlo desplegado.
  [Revisión del diagnóstico](review/2026-10-21/code-review-diagnostico-cursor.md).

- [ ] Verificar en uso remoto la corrección de seguimiento del puntero del 21/10, publicada en 0.6.1:
  la UI mantiene hasta cuatro pedidos de hover en vuelo; el receptor reemplaza sólo la última
  posición pendiente compatible, sin cruzar teclas, botones o generaciones. Regresiones:
  57 backend y 39 UI sobre bundle de producción aprobadas, con rojo previo. El incidente
  real de seguimiento todavía no está verificado como resuelto. No es PASS global.
  [Revisión y límites](review/2026-10-21/code-review-puntero-remoto.md).

- [x] Diagnosticar el inicio intermitente de Git con `0xc0000142`. Windows registra siete
  avisos entre el 19 y el 21 de octubre: seis de `git-remote-https.exe` y uno de `git.exe`.
  El helper inicia en el control del 21/10 y su firma es válida. Lienzo consulta HTTPS cada
  300 s; todavía no se acreditó el proceso padre del fallo ni la DLL causante. La RAM libre
  medida fue de 90 a 669 MB, pero el compromiso estaba al 47%: no demuestra agotamiento.
  Sólo el último aviso quedó a 21 s de despertar; la suspensión no explica todos los avisos.
  Evidencia: `.temp/coordinacion/2026-10-21/git-popup-wake-correlation.json`.
  Avance 2026-10-22: el cartel modal ya no sale (89ec553, SetErrorMode heredado por los hijos del server) y el código queda en el log con la URL. Lanzadores observados: health cada 300 s, codex.exe y claude.exe de sesiones. Coincidió con RAM al límite; la DLL causante sigue sin atribuir.
  **Cerrado el 2026-10-23 sin causa demostrada:** 11 carteles del 19 al 21/10 (todos git o git-remote-https, el último el 21/10 21:57) y ninguno desde 89ec553: ni en el registro de Windows (Application Popup) ni en el log del lienzo, que ahora lo anota con la URL. Coinciden con las rondas de 4 a 7 frentes; la causa más probable es el desktop heap de la sesión con muchas consolas (`SharedSection=1024,20480,768`, el estándar), no demostrada. Si vuelve, reabrir con trazas del cargador (loader snaps) en ese momento.

- [ ] Verificar y corregir los ocho hallazgos de la [auditoría Codex total](review/2026-10-21/code-review-codex-total.md)
  antes de cerrar la release: B01 auxiliares de transferencia fuera de raíz; B02 rehabilitación
  de bucles; B03 hashes obsoletos con caché caliente; B04 réplica que reactiva retiradas nuevas;
  B05 contención física de launch; B06 reintentos múltiples duplicados; B07 build pendiente
  tras pull fallido; B08 geometría Chrome obsoleta al ingresar. Correcciones focales verificadas, sin
  aceptación de riesgo ni casillas cerradas. B05/B07 tienen rojo/verde y 102 pruebas aprobadas,
  1 symlink omitido por privilegios; junction real cubierta. Falta integración global final.
  Backend previo a estas correcciones: 2867 aprobadas, 3 omitidas; memoria focal153 aprobadas.
  Es evidencia selectiva, no sustituye la compuerta global anterior FAIL ni acepta baseline.
  B02 incluye ahora API y migración de arranque: 136 focales y 13 del estado final aprobadas;
  con topología remota no acreditada se conserva deshabilitada con motivo. B06/B08: 22 UI y
  25 Node aprobadas con rojas previas. Transferencias B01/B03:47 aprobadas y6 omitidas por
  privilegios de symlink Windows; incluye10/10 cierres WSL inmediatos y6 symlinks POSIX por
  UNC. Hashes de entrega iguales antes/después; falta la global del conjunto. El primer409
  WSL se conserva sin causa confirmada; no se ejecutó el receptor POSIX en Linux.
  La global de239b0f5 dio6/7:2939 backend aprobadas/10 omitidas,138 UI aprobadas/1 fallida
  por salto de altura al enviar. Ajuste posterior:47 UI focales aprobadas; requiere otra global.
  La global ded319d6b pasó139 UI y6/7 casos, pero falló el primer bloque de la tanda WSL
  con500/FileNotFoundError WinError2:2938 backend aprobadas,1 fallida y10 omitidas. Los verdes
  previos no acreditan compatibilidad estable. Publicación autorizada con fallo conocido:
  0.6.0 y 0.6.1 publicadas; mutación global sin ejecutar y diagnóstico WSL abierto.

- [ ] Cerrar el contrato de turno de Antigravity con transiciones reales de pausa, cancelación,
  error, auto-continue, herramienta y finalización. Mantener bloqueados fin y `on_stop` hasta
  evidencia autoritativa; lectura parcial no confirma cierre. Medir rotación concurrente,
  junctions reales, upgrades y entorno remoto sin adoptar IDs ni activar por deducción.
- [ ] Probar el contrato Chrome sin emulación con visor remoto real después de la publicación
  conjunta de UI y remota autorizada. Medir parpadeo, zoom/pinch, dimensiones y entrada con
  `basis` vigente; conservar rechazo 409 ante tamaño viejo. Complementa la latencia LAN pendiente.
  Avance 2026-10-22: vista por pestañas usada por Ariel desde ar-it33940 sobre su Chrome real; con la PC bloqueada ~14,5 c/s sin cortes (bandera de oclusión en sus accesos directos). Falta zoom/pinch y clics con la PC bloqueada.
- [x] Diseñar autenticación humana para `persona:` y `coordinadora:` y credenciales con alcances
  Cerrado 2026-10-22 como riesgo aceptado (decisión 4 de Ariel): la LAN de casa es de confianza.
  externos para nivel 3. El rechazo del actor `server` no impide la suplantación de esos actores;
  los conteos de `externo()` no constituyen un token limitado. Vinculado a los tres niveles de registro.
- [x] Resolver la reimportación legacy: `_importar_una` usa `INSERT OR IGNORE` y puede dejar
  Hecho 2026-10-22 (ca6c073): procedencia por fila, CAS, conflictos visibles, filas inválidas omitidas y anotadas; 31 pruebas nuevas, sólo bases sintéticas.
  nodos y vínculos viejos aunque entren cambios de una base que siguió creciendo. Diseñar
  actualización, procedencia e idempotencia sin importar bases reales por esta consolidación.
  Fuente: `.temp/coordinacion/2026-10-20/C-memoria/diseno-importador-legacy.md`.
  Avance local21/10: lectura del origen en una transacción coherente; carreraWAL
  reproducida y corregida,154 pruebas del caso memoria-focal aprobadas por runner.
  No resuelve todavía la aplicación de actualizaciones con procedencia/CAS.
  Inventario local sólo lectura:0basesviejasactivas y1registroimportado; remota sin contar.
  [Revisión](review/2026-10-21/code-review-foto-importacion-legacy.md).
- [ ] Ejecutar auditoría global y gate del runner sobre una foto conjunta estable de Chrome,
  Antigravity, memoria, cancelación y Prolog; después preparar release conjunta y activación
  coordinada. Reutiliza el pendiente transversal de circuito integrado y batería global.
  Conservar logs, fallos exploratorios y límites de sandbox. No sumar focales solapadas como
  cobertura global ni aceptar tareas, propuestas, mutaciones o baselines por pasar pruebas.
- [x] Obtener contexto y error reproducible de Dot antes de proponer un arreglo.
  Cerrado 2026-10-22 (decisión 2): queda el registro de rechazos (d9aa9bb, `GET /rechazos`) para capturar la próxima falla.
- [x] Decidir presupuesto, credencial, proyectos permitidos, alcance externo y ledger del
  Hecho 2026-10-22 (decisión 1, 34d3799): Azure sólo a pedido, proyectos propios, tope duro USD 5/mes con ledger. Falta que Ariel cargue la key con `py ops/importar-azure.py`.
  adaptador Azure antes de implementarlo o activarlo. No sustituir automáticamente Codex.


### Observación del 2026-10-19: aprendizaje y limpieza

Sin cerrar tareas. En la API viva de `lienzo` se contaron 0 creencias y 5 encargos,
todos sin clasificación, con 0 patrones. El scheduler estaba habilitado pero en pausa
por actividad; el investigador no había evaluado casos desde el reinicio.
El alta normal de encargos no transportaba `contexto_desarrollo` ni
`controles_declarados`: ahora el cliente, la API y el almacenamiento admiten esos
campos opcionales y los validan antes de escribir. Los controles siguen siendo
declaraciones; no se convierten en evidencia ejecutada. No se clasificaron encargos
históricos ni se promovieron creencias.

Propuesta recuperada de [ChatGPT](https://chatgpt.com/c/6ad6148d-db70-83e9-bb64-f3b8fe93e468):
Python conserva creencias, procedencia e historial; SWI-Prolog podría aportar
inferencia con reglas `.pl` y una interfaz pequeña. La charla se refiere principalmente
a Chesstudia. Ariel propuso evaluar un motor separado reutilizable por Chesstudia,
Lienzo y otras apps, con reglas por dominio. No está implementado ni se instaló un
runtime; queda pendiente definir y medir un primer caso por consumidor.

La CLI Codex con daemon compartido puede asociarse para lectura mediante el nombre
completo del pie visible, si coincide con un único hilo TUI en la misma carpeta real.
Esto no acredita identidad para `queue`, ni cierra la P0 de `/new` y `/clear`.
El PID 9100 se vinculó en vivo al hilo `01a15639-8f32-7ed2-97f9-a56b81c865e3`.

Validación y límites: `code-review-2026-10-19-clean-code.md`. La primera global alcanzó
su timeout de 450 s; se amplió el presupuesto a 900 s, sin cambiar el baseline ni los
oráculos. La evidencia de la siguiente corrida y su compuerta quedan en los resultados
del runner. No se aprueban automáticamente referencias ni mutaciones.

Se retiró de la suite la suplantación de `cmd.exe` como `claude.exe`, identificada al
revisar el antecedente de GIST. La prueba de rechazo usa ahora un Python original,
con su nombre real. La reconexión positiva con ascendencia Claude real queda
pendiente de medición en un entorno autorizado; no se reproduce mediante binarios
del sistema renombrados. No se borraron artefactos anteriores del incidente.

## Producto, aprendizaje y extensiones (2026-10-16)

Checklist único de esta conversación. Todo queda pendiente; el estado técnico no cierra una tarea.
**Prioridad indicada por Ariel: primero el evaluador que usa Codex en segundo plano.**

### Cinco CLI Codex — cierre de integración 0.3.1 (2026-10-17)

Se lanzaron cinco CLI reales A–E por Lienzo, con archivos separados y reglas de retorno a
`01a14bf6-70e4-7c03-b9ae-7f3ad2bb5c0c`. Entregas, inventarios y logs completos en
`.temp/coordinacion/2026-10-17/ronda-cinco-final/`. La integración corrige cuota corta agotada,
retroceso de informes entregados, recorridos repetidos en memoria, tipo inválido de manifiesto
y validación/liberación de cuadros en Chrome remoto. La P0 de identidad recibe mitigación:
los handles no habilitan envío CLI; Desktop conserva su contrato. No es reidentificación resuelta.

Focales de raíz: 64 identidad, 94 cuota/informes y 83 memoria/plugins aprobadas; 18 UI en copia
aislada de E. Los conjuntos se solapan; la verificación global se documenta en
`code-review-2026-10-17-cinco.md`. No se cerraron casillas ni se aprobaron referencias. A–E
entregaron y se cerraron sus procesos propios; se conservaron informes pendientes y reglas
retiradas. Reinicio y mediciones reales siguen sujetos a las dependencias indicadas debajo.

### Ronda de cuatro Codex — avance y P0 reproducida (2026-10-17)

Cierre Desktop para 0.3.0: reconexión explícita de adaptador inactivo del mismo proceso,
caducidad visible del comando, descarte de respuesta tardía al cambiar de tarjeta y retiro
de coordinación aunque se pierda el canal. Claude y Codex Desktop mantienen las restricciones
de control de consola. Focal Desktop: 116 backend y 21 UI; contratos adicionales: 44 backend;
movimiento/autorización después de aislar avisos del servidor real: 15 UI. Los conjuntos se
solapan. Primera global fallida conservada; validación final y límites en
`code-review-2026-10-17-desktop.md`. Sin reconexión real nueva confirmada ni reinicio del backend
durante este cierre. No se cerraron casillas ni se aceptaron referencias.

Cuatro CLI propias recibieron encargos y reglas de retorno a la coordinadora
`01a14bf6-70e4-7c03-b9ae-7f3ad2bb5c0c`. Inventario de todos los tramos y evidencia en
`.temp/coordinacion/2026-10-17/ronda-cuatro/`. No se cerraron casillas ni se aprobaron referencias.

Cambios locales nuevos: UUID canónico y segunda observación de proceso/rollout en identidad
Codex (154 pruebas focales); evidencia ejecutada/verificada por lote en patrones (89 focales);
rechazo de aviso hacia la propia coordinadora mediante su ID anterior/restaurado (25 focales);
cliente de lanzamiento que no confunde el cambio de ID de una tarjeta previa con proceso nuevo
(20 focales). Las cifras son conjuntos focales con solapamiento, no una suma de cobertura global.
Los módulos nuevos posteriores al reinicio de 19:43 requieren activación coordinada; no se
reinició el backend durante esta ronda.

**P0 /new reproducida en CLI propia:** el 17 a las 19:53, después de `/new` y elegir
«Use current Git worktree», la consola quedó vacía pero el proceso conservó el único handle
del rollout anterior `01a14c08-d12a-7282-9801-a7a40719158d`. Incluso el probe corregido lo
dio por verificado. `/send` marcó entregado en ese hilo; se contaron un mensaje de usuario y
un ACK exacto en el rollout anterior, sin aparecer en la consola nueva. Un handle abierto y
dos snapshots estables no prueban que el hilo sea el visible. La P0 sigue abierta: se necesita
una fuente autoritativa del hilo actual o un transporte que no dirija al hilo abandonado.
No reinterpretar ese ACK como continuidad de la TUI. `/clear` real sigue sin medir.
Evidencia: `raiz/new-envio.json`, `new-verificacion.json` y `new-conteo.json` de la ronda.

Costo medido del probe nuevo: 372,83–489,63 ms por PID, una muestra en cada una de las cuatro
CLI propias bajo carga concurrente; no es benchmark en reposo ni justifica caché de identidad
para autorizar envíos. La medición dentro del sandbox no pudo abrir procesos; se midió afuera
con autorización. A/B fueron cerradas tras entregar y se comprobó que sus PID dejaron de existir.

UI integrada: Memoria del proyecto permite consultar creencias, checklist contextual y patrones
con estado y respaldo; sólo GET, contexto explícito y descarte de respuestas tardías. Se corrigió
el fixture de catálogo para que la recuperación dependa del gesto de reintento, no del número
de peticiones de montaje de React. La integración focal final `2026-10-17T22-57-09.839Z-33400`
dio 247 backend y 16 UI aprobados, más ESLint, build y unitarias con código 0. Runner y compuerta
salieron 1 por baseline ausente en la configuración aislada: no es PASS global ni aceptación.
La revisión está en `code-review-2026-10-17-ronda4.md`. Las cuatro CLI propias entregaron,
se cerraron y se comprobó la ausencia de sus PID. Sus reglas quedaron desactivadas, con
informes pendientes conservados; no se acusaron como integradas ni se completaron tareas.

### Ronda de cinco Codex — integración activada (2026-10-17, 19:43)

Se integraron identidad Codex por proceso/FILETIME/rollout abierto; conservación y acuses de informes;
guardias de cuota, decisión y cancelación del investigador; pasos de herramientas y vista externa
agregada; refutaciones y evidencia de controles separada por nivel. Codex Desktop puede ser
coordinadora si tiene transporte disponible. Este chat quedó con `coordinator: true` en la API viva.

Corrida global `2026-10-17T22-32-46.991Z-37680`: 7 de 7 casos con código 0,
2244 pruebas backend aprobadas y 3 omitidas, 136 recorridos UI aprobados; lint/build/unitarias y
memoria focal/e2e con código 0. El recorrido UI nuevo de recepción → integración pasó por separado.
Los 32 archivos de código/pruebas inventariados no cambiaron durante la medición.
Compuerta **ESCALAR (3)**: las mutaciones del 10/10 son de otro estado, no certifican este corte.
No se fijaron baselines ni se aceptaron propuestas nuevas. Revisión en `code-review-2026-10-17.md`.

Reinicio supervisado verificado: los siete PID de otras CLI presentes antes seguían vivos y con
tarjeta después. Lectura viva de `/conocimiento/lienzo/registro-externo`: nivel 3, 18 grupos,
sólo campos `nivel`, `proyecto`, `actividad`. Las cinco CLI de esta ronda entregaron y se cerraron.
Esta activación sustituye las notas históricas de «falta reiniciar» para estos módulos; no cierra casillas.

Siguen pendientes: `/new` y `/clear` reales y su carrera con encolado; medición de costo del sondeo
de handles; continuidad formal de coordinadora ocupada/quieta con dos frentes y reinicio; mutaciones
vigentes y aceptación de propuestas; primera investigación real y calidad causal; narrativa externa
curada, duración individual de herramientas, integración de productores/UI de controles y los
pendientes de hardware, otras PCs, presupuesto y decisiones humanas de las secciones siguientes.

API incorporada: acuse humano desde PC/LAN en `/rules/<r>/informes/<i>/acuse` (`recibido` antes de
`integrado`); `/conocimiento/<p>/registro-externo`; `/conocimiento/<p>/encargos/<id>/controles`.
El acuse no autentica una CLI mediante su UUID ni acredita por sí mismo calidad del trabajo.

### Release 0.2.0 — estado observado y pendientes (2026-10-17)

Publicado por pedido explícito de Ariel: `main` y tag `v0.2.0`, commit `98e65f7`.
Build, ESLint global y pruebas Node terminaron con código 0. Correcciones de diseño:
367 backend +13 UI; clasificación/respuestas tardías: 68 focales; bridge/bootstrap: 8 +6.
La prueba real por API principal a Claude Desktop contó un peer y un ACK exacto, y la API
publicó el mismo UUID como entregado con confirmación final. No se confunde con el self-test.
El servidor se reinició a las 13:44 con PID nuevo, conservando transcripciones e informes.
Sesiones de trabajo D/F cerradas después de leer sus entregas; reglas de retorno retiradas.
La sesión Desktop y las sesiones de otros proyectos no se cerraron.

La corrida global larga se interrumpió por pedido de simplificar el cierre; no tiene resultado
completo y no se declara aprobada. Baselines y mutaciones no se aprobaron automáticamente.
Detalle: [notas 0.2.0](docs/releases/0.2.0.md) y `code-review-2026-10-17.md`.

- [x] Reconectar el adaptador de Claude Desktop después del reinicio del servidor: generar
  un bootstrap nuevo en la tarjeta y autorizar ese comando directamente en esa conversación.
  La conexión anterior probada caduca al cerrar el servidor; no reutilizar comandos vencidos.
  Conectado el adaptador, no hay autorización por cada mensaje.
  Obsoleto (verificado el 2026-10-23): desde 0.4.0 el adaptador recupera el canal tras reiniciar sin otro bootstrap (lienzo/claude_pipe_reconnect.py); la app Desktop sólo con procesos sintéticos.
- [ ] Retomar, si se prioriza, la automatización de conexión de sesiones Desktop nuevas o
  evaluar Claude Code como puente. Prototipo y pruebas conservados íntegros fuera del release
  en `.temp/coordinacion/2026-10-17/automatizacion-diferida`; sin cambiar hooks instalados,
  permisos ni modos para eludir rechazos. Exige una prueba real de sesión nueva.
- [ ] Ejecutar una batería global completa cuando se retome esa validación; aceptar baseline
  y mutaciones sólo tras revisión humana. Las pruebas focales no se publican como globales.
- [x] Arrancar habitualmente mediante `lienzo-server.cmd` para disponer del relanzamiento.
  Pasa a práctica (decisión 19): regla vigente en `~/.codex/AGENTS.md`.
  El proceso iniciado directamente con Python rechaza POST /restart de forma segura; este
  reinicio requirió detener el PID identificado y levantar un proceso nuevo.
- [x] Revisar continuidad de mensajes Codex encolados al cerrar una CLI, y la sucesión de
  Hecho 2026-10-22 (encargo D, uso real): la CLI ya no usa la cola; cerrar tras un envío deja el acuse visible en la tarjeta muerta, otra CLI en la misma carpeta no lo hereda y un envío a la muerta se rechaza con motivo.
  títulos/reglas cuando una sesión Desktop nueva comparte repo con un encargo CLI cerrado.
  No reutilizar el proceso ni el nombre de un emisor auxiliar como identidad de sesión.
- [x] Evaluar handles fijados en copias si se necesita resistir sustituciones hostiles de
  rutas entre validación y uso; el rechazo actual de junctions existentes no elimina TOCTOU.
  Avance 2026-10-22 (db944d5): `r_borrar` ya borra por el handle del padre fijado. Queda para decidir: el emisor (`Trabajo._leer`) lee el origen por nombre; fijarlo obliga a decidir qué hacer con hardlinks de origen.
  **Cerrado el 2026-10-23:** el emisor lee el origen por `_abrir_seguro` (carpetas fijadas sin enlaces, handle dentro de copy_roots), como el destino. Decisión sobre hardlinks: en el origen se admiten (sólo se leen y son del usuario; `enlaces_ok`); en los auxiliares se siguen rechazando. Pruebas: `tests/test_xfer.py::test_el_origen_se_lee_confinado_y_admite_hardlinks` y `::test_el_origen_cambiado_por_un_junction_no_se_manda`.

### P0 — Falla grave de continuidad de la coordinadora (2026-10-17)

- [x] **Reidentificar el hilo activo de una Codex CLI después de `/new` o `/clear`, y rechazar
  Hecho 2026-10-22 (f785c61, 272e850; uso real con PID propio): la tarjeta pasa al hilo nuevo con el primer turno tras `/new` y `/clear`; `/status` se vuelve a teclear con cada rollout nuevo.
  el envío por cola si no puede vincularse al proceso actual.** Reportado por la coordinadora
  de opensyync `48befe79`, después de publicar 0.2.0. No se reprodujo todavía en una CLI propia.
  Caso reportado: PID31904 conservó tarjeta `01a14774-aa3f-7062-b3f3-aa996a33ff35` y rollout
  del 2026-10-16, aunque `/new` abrió `01a14a6b-1acc-7db2-9dbb-b7faf4033e22` el 17 a las 12:11.
  POST /send siguió aceptando codex_queue como encolado, sin recepción en la terminal actual;
  referencia de ejemplo `01a14ab6-ef97-73d2-a019-2f067e87f26d`, 13:34. Se confundió aceptación
  con trabajo efectivo durante unos 30 minutos. Mitigación de esa coordinadora: cerrar sólo su
  PID afectado y lanzar otra CLI; no repetir esa intervención sobre sus sesiones desde Lienzo.
  La guardia leída en codex_queue verifica UUID, rollout existente y PID vivo; eso no demuestra
  que el hilo siga siendo el activo de ese PID. No elegir simplemente el rollout más nuevo por cwd.
  Repro pendiente: CLI propia → `/new` → «Use current Git worktree» → POST /send; también /clear,
  dos CLI del mismo repo, codex exec paralelo y PID reciclado. Exigir nueva identidad comprobada
  o rechazo con motivo, preservando reglas/estado y sin reenviar automáticamente los mensajes
  inciertos del hilo anterior. La prueba anterior de entrega de 0.2.0 no cubre esta transición.
  Actualización 2026-10-17: el envío de Codex CLI pasa a su consola visible, con PID/FILETIME fijados
  durante la escritura; Desktop conserva la cola. La CLI descartable de prueba cambió de hilo tras
  `/new` y `/clear`, y `/status` siguió llegando a la consola actual sin invocar al modelo. La
  identidad autoritativa del hilo para `queue` sigue sin acreditarse. Esta casilla permanece pendiente.

- [x] **Garantizar que la entrega de un frente reanude la coordinación hasta integrar y verificar,
  sin esperar a que Ariel pregunte por el avance.** Pedido explícito de Ariel tras esta ronda.
  Evidencia en vivo: B entregó y su regla `c887b7b25512` registró `fired: 1`,
  `last_result: ok`, `last_fired: 2026-10-16T23:49:50.814-03:00`; el aviso llegó a esta
  conversación, pero la coordinadora respondió con estado y no continuó la integración autorizada.
  A también entregó con `ESTADO:` visible en `last_reply`, pero su regla `2054b0dd7f28`
  seguía en `fired: 0`, con `last_result: salteado: la respuesta no trae «ESTADO:» (turno intermedio)`.
  Investigar por separado la entrega fiable del informe final y la continuidad tras recibirlo;
  no atribuir ambos síntomas a una causa todavía no comprobada.
  Criterio: probar entrega mientras la coordinadora está ocupada y quieta, entrega simultánea de
  dos frentes, respuesta intermedia seguida de final y recuperación tras reinicio. Conservar
  informe pendiente hasta acuse de recepción y procesamiento; recuperar avisos perdidos sin
  duplicar encargos ni generar bucles. Mostrar entregado, recibido e integrado por separado.
  Registrar evidencia de que la coordinadora retoma revisión/integración/pruebas o comunica un
  bloqueo concreto, sin completar tareas ni aprobar baselines automáticamente.
  Estado (2026-10-17): causa de A comprobada con la transcripción y el log. Una `<task-notification>`
  reabrió el trabajo sin UserPromptSubmit; transcripts.py lo dio por terminado (23:55:20) con la
  respuesta intermedia y el Stop real con «ESTADO:» (23:56:13) no cambió el estado, así que la regla
  nunca evaluó la entrega. Corregido en local: la notificación reabre el turno (transcripts.py) y
  rules.py reconcilia turnos cerrados sin evaluar (marca persistida, sin duplicados ni bucles).
  Pruebas: tests/test_rules.py y test_transcripts.py, más la transcripción real de A cortada en
  02:55:20 (abierto) y 02:56:14 (cerrado con ESTADO:). Falta reinicio del backend, aceptación,
  la vista entregado/recibido/integrado y la continuidad de la coordinadora (síntoma de B, aparte).
  **Cerrado el 2026-10-24 (encargo E, Codex):** pruebas del criterio (coordinadora ocupada y quieta, dos frentes a la vez, intermedia y final, reinicio sin perder ni duplicar) en `tests/test_encargo_E_informes.py`; síntoma B: un informe «entregado» sin acuse 20 min (`INFORME_SIN_ACUSE_S`) con la coordinadora quieta recibe un recordatorio, uno por informe, persistido, con `sin_aviso` y en su propio hilo; los tres estados se ven en el panel (`web/tests-ui/backlog-informes.spec.ts`).

### P0 — Evaluador e investigación en segundo plano

- [ ] **Implementar el evaluador con Codex/CLI en background, complementando a Jev.**
  Jev conserva el filtro barato y la priorización. Codex investiga los casos elegidos, relaciona
  código y trazas, identifica causas y propone mejoras. No reemplazar Jev por llamadas CLI para todo.
  Criterio: recorrer selección → investigación CLI → resultado estructurado → evidencia en memoria
  → propuesta visible, con un caso positivo y fallos reproducibles.
  Estado (2026-10-17): implementado localmente (optimization_research*, cola y scheduler) con
  pruebas y casos del runner; la vista del panel muestra cuota, bloqueos, candidatos y cancelación.
  Falta reiniciar el backend (puede lanzar `codex exec` real con la cuota de Ariel), primera
  ejecución real, aceptación, baseline y mutaciones aprobados.
- [x] Integrar el investigador a la cola y al scheduler de Lienzo: un trabajo controlado,
  límites de duración/consumo, condiciones de inactividad y recursos, pausa, cancelación,
  recuperación y deduplicación. No afectar sesiones ajenas ni habilitar reintentos infinitos.
  Criterio: actividad del usuario o un fallo detiene/pospone según el contrato, conservando evidencia.
  Hecho (verificado el 2026-10-23): cola, scheduler y condiciones de recursos (0.6.13); tests/test_optimization_scheduler.py, test_optimization_queue.py, test_optimization_cancel_races.py.
- [x] Definir y comprobar la política de autonomía y consumo del investigador.
  Distinguir investigación de sólo lectura, experimentos aislados y aplicación de cambios.
  La conversación no concede un presupuesto monetario nuevo ni autoriza instalar lo que recomiende.
  Criterio: mostrar límites y motivos de bloqueo; ninguna ejecución puede saltarse las guardias.
  Hecho (verificado el 2026-10-23): lienzo/optimization_research_policy.py separa read_only/isolated_experiment/apply con techos y motivos de bloqueo en la UI; tests/test_optimization_research_unit.py.
- [x] Ampliar las preguntas del evaluador al flujo completo: herramientas, contexto, memoria,
  arquitectura, planificación, tareas/features, construcción, iteraciones entre olas, coordinación,
  esperas, pruebas, review, auditoría, retrabajo, documentación y capacidades que faltan.
  Criterio: cada propuesta identifica problema, fuentes, alcance, alternativa y forma de comprobarla.
  Hecho (verificado el 2026-10-23): optimization_research.py define las 20 áreas y exige problema, alcance, alternativa, comprobación y riesgo con fuentes; tests/test_optimization_research.py.

### Ciclo aparte — Tres niveles de registro (pedido de Ariel, 2026-10-17)

- [x] **Guardar lo que pasa en Lienzo en tres niveles y que cada consumidor lea el suyo.**
  Hecho 2026-10-22 (decisión 5, 84aa7b8): nivel 1 crudo con depuración diaria a 30 días; niveles 2 y 3 ya existían.
  1. Crudo: todo (transcripciones, salidas completas, eventos). Se depura cada tanto con una retención que
     decide Ariel; depurar es borrar, no se automatiza sin esa decisión.
  2. Cómo se hizo el trabajo: llamadas, tiempos, esperas, quién hizo qué. Es para el investigador.
  3. Qué pasó: qué se hizo y en qué proyectos, resumido y limpio, sin cosas internas ni ruido. Es para todas
     las sesiones y para los sistemas externos que reciben información de Lienzo.
  El investigador usa los niveles 2 y 3 para optimizar. Hoy su paquete trae el 3 (nodos de memoria) y sólo
  ids de sesión del 2; las capturas (`captura`) son la fuente natural del nivel 2.
  Criterio: un consumidor externo recibe sólo el nivel 3; el investigador recibe el 2 y el 3 sin
  transcripciones; el crudo se puede recuperar hasta su depuración.
  Estado (2026-10-17): nivel 2 del investigador desde capturas hecho (por sesión y hasta 60 eventos
  recientes, redactados; el crudo no viaja). Faltan las llamadas a herramientas por paso, el nivel 3
  para sistemas externos y la depuración del crudo.
  Estado (2026-10-29): nivel 3 con contenido. `GET /conocimiento/registro-externo` (índice de proyectos),
  `GET /conocimiento/<p>/registro-externo?detalle=1` (temas, decisiones vigentes y propuestas, hallazgos
  y preguntas abiertas) y `.../registro-externo/buscar?q=` (BM25 sólo sobre eso). Sin IDs, rutas ni
  secretos; tests/test_registro_externo.py.
  Bot de ChatGPT: `lienzo/bot_externo.py`, sólo GET con clave Bearer en 127.0.0.1:7330, arranca con el server
  si existe `~/.lienzo/bot-externo.json` y sale por Tailscale Funnel (https://ariel.taild86fe5.ts.net).
  Resumidor (`lienzo/resumidor.py`): en segundo plano, cada día cerrado de pedidos y respuestas pasa a un
  `informe` `resumen_nivel3` con temas; tope propio de 12 vueltas/día (decisión de Ariel, 2026-10-29) y la
  depuración del crudo espera también a su cursor. Falta revisar los primeros resúmenes reales.
- [x] Llevar la instrucción de RTK de la base agéntica (`lienzo/tools/rtk.py`) a todo lo que lee un agente
  Cerrado 2026-10-22 (encargo I): la instrucción ya cubre `rtk read`, `rg`, `find`, `git` y `recall`; lo prueba `test_rtk_base_comun`.
  (`rtk read`, `rtk rg`, `rtk find`, `rtk git`, `rtk recall`), no sólo a las salidas largas. La base la
  comparten las sesiones y el investigador.

### P1 — Memoria, creencias, patrones y decisión

- [x] Integrar la base de creencias en la memoria existente, con fuentes, contexto, confianza,
  excepciones, vigencia y posibilidad de refutar/reemplazar sin borrar historia.
  Estado: código y contratos locales; falta aceptación y activación.
  Hecho (verificado el 2026-10-23): lienzo/creencias.py (confianza, excepciones, vigencia, refutación, reemplazo sin borrar historia), activo desde 0.6.10; tests/test_creencias.py.
- [x] Entregar el checklist contextual como vista de creencias respaldadas, corto y ajustado al trabajo.
  Excluir propuestas sin validar, vencimientos, refutaciones y apoyos retirados.
  Estado: implementación local sin reglas duplicadas; falta integración de uso y activación.
  Hecho (verificado el 2026-10-23): checklist del motor Prolog (lienzo/prolog_checklist.py) desde 0.6.10; tests/test_prolog_checklist.py.
- [ ] Detectar y contrastar patrones de desarrollo sin tratar todo igual.
  Separar bugfix, feature, refactor, investigación, documentación y arquitectura, conservando
  proyecto, tecnología, área, fase, agente/modelo/versiones y condiciones relevantes.
  Estado: agrupación por etiquetas explícitas; falta investigación de patrones desde flujos reales.
- [x] Incorporar evidencia de pruebas, review local de Claude y auditoría mediante skill.
  Distinguir controles declarados, ejecutados, hallazgos, correcciones verificadas y pendientes.
  Una revisión ejecutada o un turno cerrado no prueba calidad ni completa una tarea.
  Hecho (verificado el 2026-10-23): lienzo/patrones_evidencia.py separa declarado, ejecutado y verificado; tests/test_backlog_e_evidencia.py.
- [x] Mostrar en Lienzo observaciones, investigaciones, propuestas, evidencia, creencias y checklist.
  Permitir que Ariel revise y decida adopción; no promover una recomendación del modelo por sí sola.
  Criterio: se puede seguir una propuesta hasta sus fuentes y conocer qué no fue medido.
  Hecho (verificado el 2026-10-23): web/src/components/Learning.tsx con creencias, propuestas, patrones, checklist y veredicto humano; web/tests-ui/aprendizaje*.spec.ts. Aparte: falta la UI para corregir la cláusula (0.6.15).

### P1 — Catálogo y contrato de plugins

- [x] Activar y verificar el catálogo ampliado: Anatomy y Commit (Image Preview y Sub Meter quedaron
  fuera de Lienzo por decisión de Ariel, 2026-10-17; siguen instalados en Claude Code).
  Estado: fichas implementadas y UI compilada/probada; backend activo observado con cinco fichas
  anteriores. La activación debe coordinarse: había dos sesiones corriendo y tres con turno terminado.
  **Verificado el 2026-10-23** en el backend vivo (`GET /agent-improvements`): Anatomy (skill) y Commit (plugin, 0.2.0) disponibles. Commit es de Better Claude, que la decisión 6 descartó: falta que Ariel confirme si sale del catálogo.
- [x] Instalar y comprobar Better Claude en el entorno autorizado.
  Descartado 2026-10-22 (decisión 6 de Ariel).
  Verificar manifiestos, activación y compatibilidad de Image Preview/Sub Meter/Commit en Claude Code.
  Mantener visible que Image Preview necesita verificación Windows, Sub Meter depende de suscripción,
  y Commit puede hacer commit/push en modo no interactivo. No ejecutar /commit como prueba automática.
  Estado (2026-10-17): instalados por pedido de Ariel en scope user (image-preview 0.1.1, sub-meter 0.1.0,
  commit 0.2.0); el catálogo vivo los ve habilitados. Falta verificar en una sesión nueva de Claude Code
  el hover de Image Preview en Windows (fullscreen) y la barra de Sub Meter. /commit no se ejecutó.
  Ariel confirmó el 2026-10-17 que Better Claude anda.
- [x] Mostrar tools, integraciones y formas de trabajo sin confundir función con empaquetado.
  Estado: metadatos de formato/compatibilidad/límites e inventario de plugins locales implementados.
  Un plugin puede no tener tools ni GitHub. Cargado no equivale a conectado o sano.
  Hecho (verificado el 2026-10-23): AgentImprovements.tsx muestra tools y plugins por separado; plugins.py aclara que «cargado» no acredita salud. Sin aceptación de Ariel registrada.
- [x] Implementar el contrato uniforme de incorporación de plugins:
  Hecho 2026-10-22 (encargo D): carpeta real validada con un plugin mínimo (`declarado`), uno inválido (`error`, cuatro motivos) y uno viejo sin manifiesto (`cargado`); Stepwise sigue `cargado`.
  identidad/versión, compatibilidad, capacidades, configuración, permisos, ciclo de vida, estado,
  evidencia y relaciones opcionales. El manifiesto no obliga a tener endpoints, interfaz o tools.
  Criterio: validar un plugin mínimo y uno inválido, sin romper las extensiones existentes.
  Estado (2026-10-17): contrato v1 implementado localmente (plugin_manifest.py, plugins.py, fichas
  en el panel, parada al salir del server). Mínimo, inválido y Stepwise legacy probados. Falta
  reinicio del backend, aceptación y decidir el manifiesto propio de Stepwise.
- [x] Conservar Stepwise como integración local existente entre sistemas y formas de trabajo.
  No copiar ni publicar su código en GitHub para registrarlo; verificar ficha y disponibilidad local.
  Hecho (verificado el 2026-10-23): Stepwise sigue local (.gitignore, lienzo/extensiones/stepwise.plugin.json), verificado «cargado» por el encargo D del 2026-10-22.
- [x] Conservar Anatomy como herramienta existente de documentación visual y reutilizar su integración.
  Su aporte documental se evalúa por claridad/utilidad; no sustituye controles de calidad del código.
  Hecho (verificado el 2026-10-23): lienzo/tools/anatomy.py reutiliza la skill anatomy; tests/test_catalogo_comunidad.py y tests/test_infografias.py.

### P2 — Investigación de comunidad

- [ ] Preparar investigación periódica de tools, integraciones y formas de trabajo de la comunidad.
  Relacionar cada candidata con necesidades observadas y guardar fuentes, fecha, alternativas,
  costos, permisos, mantenimiento y riesgos relevantes.
- [x] Definir frecuencia y presupuesto de esa investigación, con propuestas para decisión de Ariel.
  Decidido 2026-10-22 (decisión 8): semanal, con Claude, propuestas para que Ariel decida.
  Descubrir o recomendar no autoriza instalar, activar ni modificar proyectos.

### Transversal — Diseño, Markdown, calidad y entrega

- [x] Mantener arquitectura, plan y tareas/features según alcance y riesgo, sin imponer SDD.
  Pasa a práctica (decisión 19): regla vigente en `~/.codex/AGENTS.md`.
  Proceso flexible y calidad no negociable: no reducir revisión, pruebas o información necesaria
  para producir un número mejor de tiempo, longitud o tokens.
- [x] Mantener alineados Producto, Arquitectura, Aprendizaje y Plugins con lo construido.
  Pasa a práctica (decisión 19): regla vigente en `~/.codex/AGENTS.md`.
  Unificar y eliminar documentos intermedios/obsoletos preservando decisiones y evidencia útil.
  Estado: 13 specs retiradas; 26 Markdown revisados por enlaces, sin enlaces locales rotos.
- [x] Mantener esta lista como única fuente de tareas; no cerrar casillas sin pedido explícito.
  Pasa a práctica (decisión 19): regla vigente en `~/.codex/AGENTS.md`.
  Distinguir implementación, prueba local, aceptación, activación y medición en uso real.
- [x] Aplicar Explorer → Analyser → Designer → Executor → Detective y code-audit a los cambios.
  Pasa a práctica (decisión 19): pruebas agénticas y code review obligatorios en `~/.codex/AGENTS.md`.
  Conservar logs/errores y el veredicto real; no aprobar baselines ni mutaciones por cuenta propia.
  Estado medido: 45 contratos del catálogo, 7 recorridos UI y 52 pruebas de creencias/patrones pasan;
  build/lint verificados. Compuertas código 1 por baseline ausente; no hay PASS certificado.
- [x] Verificar el circuito integrado en una instancia aislada antes de activar el backend principal.
  Revalidar las áreas afectadas de consultas, WSL y memoria sin pisar cambios de otras sesiones.
  Retirar las specs no equivale a haber ejecutado sus verificaciones pendientes.
  Obsoleto (verificado el 2026-10-23): el backend principal ya se activó en cada release 0.4–0.6.16 con suites integradas.

Referencias: [Producto](docs/PRODUCTO.md), [Arquitectura local](DISENO.es.md),
[Aprendizaje](docs/APRENDIZAJE.md), [Plugins](docs/PLUGINS.md) e
[índice documental](docs/README.md). Estas prioridades no conceden consumos nuevos ni aceptación de referencias.

Las casillas heredadas se conservan textuales. El 2026-10-10 se cerraron (con `[x]` y su evidencia
debajo) las verificadas en código, pruebas o decisión de Ariel; las demás siguen pendientes. La evidencia histórica no es una prueba
ejecutada hoy. Las referencias de código de esta consolidación se revisaron estáticamente.

## Orquestación de encargos

- [ ] **Incorporar a Lienzo las ideas de coordinación y verificación del experimento de Prime Agent**
  (pedido de Ariel, 2026-10-12). Mantener la tecnología y arquitectura actuales; no reescribir en Rust.
  - Etapas explícitas por encargo: pendiente → implementación → revisión → verificación. El cierre
    de un turno o una respuesta del agente no equivale a aprobación ni completa la tarea por sí solo.
  - Dependencias entre encargos: esperar los insumos necesarios y ejecutar en paralelo los frentes
    independientes, con la coordinadora controlando la integración.
  - Evaluar un `git worktree` por frente que modifica código para reducir interferencias.
  - Límites de gasto y reintentos por encargo, con detención y aviso cuando una ronda repite errores
    sin avanzar. Distinguir consumo medido de estimaciones y datos no disponibles.
  - Evidencia visible junto al informe: cambios, revisión, pruebas ejecutadas, resultados y pendientes.
    Priorizar la vinculación del encargo con su evidencia de revisión y pruebas.
  - Reutilizar la coordinadora, los mensajes, las reglas `on_stop` y sus límites existentes.
  - Criterio de aceptación: un encargo puede recorrerse de punta a punta con evidencia consultable;
    una dependencia bloquea su ejecución hasta disponer del insumo; un fallo de verificación permite
    devolverlo a implementación; los límites frenan reintentos sin avance; ninguna tarea se marca
    completada sin pedido explícito de Ariel.
  Avance 2026-10-22 (decisión 15, 516f7ab): etapas explícitas por encargo, visibles en Memoria → Etapas; un turno cerrado no aprueba. Quedan dependencias entre encargos, worktree por frente y límites de gasto y reintentos.

  Origen: conversación con Ariel del 2026-10-12 sobre Prime Agent.
  Referencia: https://www.primeintellect.ai/blog/prime-agent-rust.
  **Actualización del 2026-10-16:** lo de arriba sirve como requisitos. Falta definir arquitectura,
  plan y tareas según el alcance: cómo encaja en `coordinar.py`, las reglas `on_stop` y las rondas.
  No exige un recorrido SDD obligatorio.

## Rondas largas: lo que quedó afuera (2026-10-16)

Lo hecho está en el README («Rondas largas») y en `code-review-2026-10-16.md`.

- [x] Reiniciar el server de 7321 entre olas de OpenSyync: lo coordina su coordinadora (pedido del
  Cerrado 2026-10-22 como obsoleto (decisión 20).
  2026-10-16, no reiniciar mientras esté en ronda). Hasta entonces el tablero nuevo pide `/avisos` y
  `/memoria` y recibe 404, y Playwright `humo` y `salud` fallan contra 7321 por esos errores de consola.
- [ ] Aprobar o descartar `pruebas-agenticas/resultados/casos-rondas.nuevo.json` (rondas-focal,
  rondas-e2e) y `mutaciones-rondas.nuevo.json` (5 destructivas, 3 de control); después correr
  `mutar.mjs --sin-cache` y la compuerta sobre el estado commiteado.
- [x] Medir con dos PCs: un aviso a un frente de otra PC se confirma leyendo `last_reply` del espejo,
  sin probar todavía con la otra PC real; `POST /avisos/<id>/ack` se manda al lienzo de quien creó el aviso.
  Avance 2026-10-21 (encargo R): el `ACK` por línea desde ar-it33940 quedó registrado acá. El ack por API desde otra PC no existe: el server no reenvía `/avisos/<id>/ack`.
  **Cerrado el 2026-10-23:** `POST /avisos/<id>/ack` se reenvía a las PCs emparejadas si el aviso no es local (`server.ack_aviso`, `/peer/avisos/<id>/ack`); contesta la que lo tiene, y su rechazo vuelve como 409. Prueba en `tests/test_server.py`.
- [ ] Medir con una restauración real tras reiniciar la PC que Claude y Codex hereden reglas y título
  (cubierto con pruebas sobre el registro; no con agentes reales).

## Trabajar con Claude Desktop y Codex desktop (2026-10-16)

- [ ] **Qué hace falta para que el lienzo trabaje del todo con las apps de escritorio** (pedido de
  Ariel, 2026-10-16: «solo documentalo, investigá»). Hoy el barrido las descarta y el envío las
  rechaza por no tener consola. El detalle, con lo verificado separado de lo inferido, está en
  [docs/desktop-apps.md](docs/desktop-apps.md).
  - **Claude Desktop** corre el mismo motor que la CLI: lee `~/.claude/settings.json` y sus hooks, y
    escribe la transcripción en `~/.claude/projects` con `entrypoint: claude-desktop`. Estado,
    contenido y permisos por hook deberían andar ya, como tarjeta de sólo lectura (sin medir). Mandar
    un mensaje no: no hay consola ni API. Los caminos a medir son el canal nativo Claude-Claude y
    Remote Control. Lanzar y retomar: `claude --desktop --resume <id>` lleva una sesión a la app, y
    `claude --resume` la devuelve a la terminal.
  - **Codex desktop** guarda sus hilos en `~/.codex/sessions` con `originator: Codex Desktop`, que el
    lienzo hoy descarta. No hay hook confirmado en la app. El camino firme es el app-server (JSON-RPC:
    `thread/resume`, `turn/start`, `turn/steer`, aprobaciones como pedidos al cliente), con el lienzo
    como cliente de hilos que lanza él. `codex://new?prompt=&path=` y `codex://threads/<id>` sólo
    abren o precargan.
  - **Riesgos:** `~/.codex/config.toml` tiene `[features] hooks = false` desde el 2026-10-07 al menos, y
    eso apaga los hooks de Codex también en la CLI. `is_tui` mira sólo la ruta y no reconoce el
    `claude.exe` que trae Desktop (`\Roaming\Claude\claude-code\`) ni el `codex.exe` de la app. Dos
    clientes en un mismo hilo de Codex no están documentados.
  - **Próximo paso:** una sesión de medición con las dos apps abiertas en una carpeta de prueba: qué
    eventos llegan a `~/.lienzo/events` desde Desktop y con qué proceso; contestar un permiso y una
    pregunta desde el lienzo; probar el canal nativo hacia una sesión de Desktop; y un cliente mínimo
    del app-server de Codex, fuera del server, que abra un hilo, mande un turno y conteste una
    aprobación.

## Puente con el orquestador externo, reglas por frecuencia y envío confirmado (2026-10-14)

Ariel aceptó la entrega del puente con veredicto ESCALAR. Detalle del code review en el historial de git (`code-review-2026-10-14.md`).

- [ ] Medir con un agente real autorizado que el `session_id` del hook coincida con la sesión que el
  orquestador ata a su corrida. Solo se probó con su ejecutor de prueba, que no lanza agentes.
- [ ] Puente: detección por proceso en tmux/WSL, tarjetas del orquestador por el espejo entre PCs, y
  relanzar desde Lienzo. Para relanzar faltan contratos medidos.
- [x] Decidir si el e2e del puente entra a la suite y si se aprueban sus mutaciones (propuesta en
  `pruebas-agenticas/resultados/`).
  **Cerrado el 2026-10-15 (Ariel lo dejó a criterio):** no entra. Prueba el plugin Stepwise, que vive en
  `lienzo/extensiones/` fuera de git, con un binario y fixtures de esta PC; en la suite del repo fallaría
  en cualquier otra. Si hace falta, va con el plugin.
- [x] Indicador "enviando…" en la tarjeta mientras un envío espera su `UserPromptSubmit`. Hoy queda en
  su estado anterior hasta la confirmación; sin confirmación a los 25 s, pasa a "te necesita".
  **Cerrado el 2026-10-15:** `envio_pendiente` se ve como «enviando…» en la cabecera de la tarjeta, sin cambiarle el alto (tests-ui/tarjeta.spec.ts).
- [x] backend-pytest roza el timeout de 300 s del runner: 240 s aislado y más bajo carga. Una corrida dio
  una `F` que no se reprodujo. Recalibrar el timeout con aprobación o separar la batería.
  **Cerrado el 2026-10-15:** Ariel aprobó subirlo a 450 s en `pruebas-agenticas.json`.
- [x] Dos permisos de sesiones que ya no estaban se auto-aprobaban cada hora: el hook murió sin leer la
  respuesta y el pedido quedó en disco. **Cerrado el 2026-10-15:** el auto-aprobar saltea un pedido que ya
  tiene su respuesta escrita (tests/test_autoaprobar.py). Los pedidos huérfanos siguen en
  `~/.lienzo/pending` hasta que alguien los borre. **Cerrado también:** el server borra un pedido vencido
  hace más de 2 minutos, con su respuesta (`sessions.purgar_huerfanos`, tests/test_ola1_sesiones.py).
- [x] Reglas `on_stop` agotadas por el tope total viejo: no se reactivan solas. Se reactivan editándolas
  con `limit:"rate"`.
  **Cerrado el 2026-10-15:** al arrancar, `rules.reactivar_agotadas_por_tope_viejo` las prende de nuevo (tests/test_rules_frecuencia.py).
- [x] Hook en Unix: destino por `TMUX_PANE` sin probar (falta una PC Linux). Origen: code review del 2026-10-10.
  Hecho 2026-10-22 (3dbe685, encargo K): verificado con un Claude en tmux en WSL; lo enviado llegó al pane `%0`.
- [x] Un diálogo de permiso que el auto-aprobar va a contestar pasa la tarjeta a `te_necesita` unos 5 s:
  `answer_dialog` limpia `dialog` pero el estado vuelve recién en la pasada de pantalla siguiente. La
  columna vacía se abre y se cierra y corre el tablero. Medido el 2026-10-15: unas 36 aprobaciones en una
  hora en una sola tarjeta codex. Toca `sessions.screen_once` y `autoaprobar`.
  **Cerrado el 2026-10-15:** queda en su estado mientras el auto-aprobar lo contesta (15 s de margen; después sí pasa) y contestar un diálogo saca ya la tarjeta de «te necesita» (tests/test_autoaprobar.py).
- [x] Si la pantalla pasa de un diálogo a otro sin quedar sin diálogo en el medio, `dialog_at` no se renueva y el
  segundo cae antes en «te necesita». Origen: code review del 2026-10-15. Gravedad: baja.
  **Cerrado el 2026-10-15:** se renueva cuando cambian la pregunta o las opciones (tests/test_autoaprobar.py).
- [x] `mirror._poll_health` llama a `on_change()` en cada health exitoso aunque nada cambie: el tablero
  recibe el estado completo cada 10 a 15 s y reemplaza todas las sesiones. No se ve, pero es render de más.
  **Cerrado el 2026-10-15:** solo avisa cuando el par vuelve o cambia su diagnóstico (tests/test_mirror.py).

## Pendientes trasladados de MEJORAS.md

### Seguridad

- [x] Pruebas que conviene escribir (salieron de la revisión adversarial): matriz de autenticación
  por ruta para el túnel, paridad entre `Handler` y `PeerHandler`, el contrato de los 404
  (`unknown_session` contra ruta desconocida) y referencias (golden) por agente en los parsers.
  - **Cerrado el 2026-10-10:** Ya escritas: matriz del túnel en `tests/test_ola1_seguridad.py` (`test_por_el_tunel_sin_cookie_todo_da_401_salvo_las_rutas_publicas`), paridad `Handler`/`PeerHandler` en `tests/test_ola2_server.py`, 404 `unknown_session` en `tests/test_server.py` y golden por agente en `tests/test_ola2_agentes.py`.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 5. Gravedad: media.

### Multiplataforma

- [x] **Evaluar una forma más óptima de sincronizar las bases de memoria entre PCs** (pedido de Ariel,
  Hecho 2026-10-22 (57d5761): pedido `marcas` por vuelta; vuelta ociosa 41→1 pedido, 494→19 ms de CPU, 769→27 ms; compatible con pares viejos. Medido con dos procesos locales, no entre las dos PCs reales.
  2026-10-10). Hoy cada server le pide a cada par, cada 120 s, los cambios y capturas nacidos allá desde su
  cursor (`lienzo/replica.py`, `/peer/conocimiento`), en lotes, aunque no haya nada nuevo; los cuerpos van
  aparte. Lo que habría que medir y comparar:
  - **Empujar en vez de sondear:** que el par avise por el SSE que ya tienen abierto (`/peer/events`) cuando
    nace un cambio, y recién ahí se pida; el ciclo de 120 s queda solo como red. Menos tráfico ocioso y la
    otra PC se entera en segundos, no en hasta dos minutos.
  - **Tamaño y forma de los lotes:** comprimir el JSON (gzip) y ajustar el límite por pedido; medir cuánto
    pesa hoy un ciclo vacío y uno con capturas largas.
  - **Changesets de SQLite** (extensión session) o una base CRDT (cr-sqlite) en vez de la tabla `cambio`
    propia: ver si ahorran código y bytes o si suman una dependencia que no paga (la stdlib no trae ninguna).
  - **Qué no replicar:** si las capturas `observado` de una carpeta temporal o los textos muy largos tienen que
    viajar enteros o alcanza con el resumen y el hash.
  - Criterio: latencia entre que nace un cambio y lo ve la otra PC, bytes por hora con el tablero quieto y
    activo, y que no se rompan los cursores ni la idempotencia (las 10 pruebas de `replica.py` siguen
    pasando).

  Origen: conversación con Ariel del 2026-10-10. Gravedad: **alta, prioridad** (Ariel, 2026-10-10).
  **Actualización del 2026-10-16:** primer paso: medir bytes de un ciclo vacío y de uno con capturas,
  y latencia hasta que la otra PC ve un cambio. Con esos datos definir arquitectura, plan y tareas
  según el alcance, sin exigir SDD. La medición entre PCs necesita ar-it33940 prendida.

- [x] Integración uniforme de CLI y hallazgos del code review: capacidades compartidas entre
  Python/TypeScript, proveedores de identidad/transcripción/modelo/diálogo/reanudación, Kiro V3
  limitado explícitamente a Windows y diagnóstico de metadatos sin repetir errores.
  Evidencia inicial: 190 pruebas focales pasan y build del frontend pasa (2026-10-07).
  **Cerrado el 2026-10-23:** capacidades compartidas en `agent-capabilities.json` (Python y TypeScript); los proveedores por agente viven en los perfiles de `agentes.py`; Kiro y Antigravity quedan sólo Windows desde `windowsOnly` (Python lo lee de ahí y el lanzamiento lo exige; el front no ofrece WSL para ellos), prueba `tests/test_capacidades_plataformas.py`. El «diagnóstico sin repetir errores» no tenía definición; si hace falta, va como ítem propio.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 3. Gravedad: media.
  **Estado al 2026-10-15:** sin spec y poco definido. Antes de especificar, contrastar con el código: los
  perfiles de `agentes.py` (permisos, diálogos, transcripciones por agente) pueden cubrir buena parte.

### Federación

- [x] Coordinadora sólo del repo (pedido del 2026-10-07): eliminado el rol por PC del menú,
  cliente y API. Las marcas guardadas se migran al cargar; se conserva una marca local por repo,
  prefiriendo la general existente. Seleccionar una coordinadora desmarca las del mismo repo
  en las demás PCs visibles. Las PCs desconectadas requieren reconciliarse al volver.
  Prueba focal: 134 casos pasan. Corrida agéntica `2026-10-07T06-12-22.146Z-27252`:
  cinco suites sin fallas, 981 backend y 117 UI; menú real verificado con captura.
  - **Cerrado el 2026-10-10:** Implementado y probado el 2026-10-07 (nota de arriba); la compuerta del 2026-10-10 pasa con esas pruebas.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 1. Gravedad: media.

- [ ] Cierres del plan multi-PC (`docs/plan-multi-pc-2026-09-26.md`, historial de Git) que siguen sin
  prueba real con la otra PC: la regla de firewall real de `install.py --peer` (código y `--dry-run`
  probados); ver en vivo desde A las tarjetas y la salud de B; aprobar un permiso de B desde el
  tablero de A; lanzar un frente en B desde la ★ de A y que su informe vuelva solo; una ronda real
  repartida entre dos PCs usando solo el skill, y el skill corregido contra lo medido. Hasta ahora
  todo eso se probó entre dos procesos en la misma PC.

  Origen: `docs/plan-multi-pc-2026-09-26.md`, cierres F1 a F5. Gravedad: media.

- [x] Reiniciar lienzo en la otra PC cierra las codas que corren (medido el 2026-10-03; la recarga automática por `git pull` NO las cerró: la coda de la sesión 4 siguió viva; la hipótesis de pestañas de Windows Terminal en la misma ventana del server tampoco, según la coda A cada coda abre en su propia consola, aunque lo dijo leyendo el código y no la configuración): la coda de la sesión 3 quedó
  `ended_at` en el mismo segundo del reinicio y hubo que restaurarla (`restaurar`, con contexto). Además, con la causa sin
  resolver, todo lo que sale hacia esa PC dio `401 firma invalida` de repente (sin cambios de reloj ni de claves) y solo se
  arregló reiniciando su lienzo. Ideas: que las codas no cuelguen del proceso del server, y que ante un 401 el lienzo
  intente el reinicio del peer o avise con el motivo («su server no valida mi firma»), en vez de dejar el tablero mudo.
  - **Nota del 2026-10-10:** el 401 ya llega al tablero con su motivo («la otra PC no acepta mi firma», `federation.py`, con `causa_401`). Queda la causa de que mueran las codas, que necesita la otra PC.
  - **Cerrado el 2026-10-10 (no se reprodujo):** con el código de db12f5e se lanzó una coda en ar-it33940 desde el tablero de
    la otra PC (PID 16848, contestó «OK») y se reinició ahí el server matando solo el PID de 7321 y relanzando con
    `lienzo-server.cmd`: la coda siguió viva antes, durante y después (mismo padre, PID 19636), y el tablero la volvió a
    ver. Si vuelve a pasar, reabrir con el modo en que se abrió esa coda (a mano o desde el lienzo).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 10. Gravedad: alta.

- [x] El lienzo no puede cerrar un agente colgado de otra PC: `/exit` queda en cola y `interrupt` no
  alcanza si el proceso está clavado. Hoy hubo que pedirle a otro coda un `taskkill` por PID. Idea:
  `POST /sessions/<sid>/kill` que la PC dueña ejecute sobre su propio PID (con la misma
  confirmación que las demás acciones destructivas).
  - **Cerrado el 2026-10-10:** Implementado el 2026-10-07: `POST /sessions/<sid>/kill` con confirmación, que ejecuta la PC dueña (`lienzo/kill_agent.py`).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 13. Gravedad: media.

- [x] Latencia entre PCs: un pedido mínimo a la otra PC tarda ~86 ms (mediana, p95 136 ms) contra 2,5 ms
  local; la pantalla de una tarjeta remota, ~470 ms. Cada pedido abre una conexión TCP nueva y firma
  con HMAC. Idea: conexión persistente (keep-alive) por peer y cachear `screen` unos 500 ms.
  - **Cerrado el 2026-10-10:** Conexiones HTTP reutilizables por peer desde el 2026-10-07 (cierre de implementación). Queda medir por LAN con la otra PC (ítem de Chrome remoto).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 14. Gravedad: media.

- [x] El SSE del peer se corta y reconecta cada ~15 s (`peer GET /peer/events` en el log cada 15 s).
  Funciona, porque cada reconexión trae el snapshot entero, pero es tráfico de más y una ventana en
  la que el espejo se reemplaza. Hay que ver si el server corta el stream a propósito.
  - **Cerrado el 2026-10-10:** Causa: el timeout de lectura del cliente. `SSEClient` lo cambia después de conectar (verificado el 2026-10-07).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 15. Gravedad: media.

- [x] **`launch_roots` no se ve desde la otra PC**: `peers.json` no lo trae y no hay forma de saber qué
  carpetas permite un peer sin intentar lanzar. Mostrarlo en `GET /peers`.
  - **Cerrado el 2026-10-10:** `GET /peers` trae `launch_roots` en la salud de cada PC desde el contrato de capacidades (2026-10-07; `tests/test_health.py`).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 16. Gravedad: media.

- [x] Traspasar un encargo entre PCs: copiar y pegar trabajo entre tarjetas funciona dentro de una
  PC; entre PCs no hay forma de mover un encargo a una tarjeta de la otra.
  - **Cerrado el 2026-10-10:** Implementado el 2026-10-07 (traspaso de trabajo entre PCs, cierre de implementación).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 19. Gravedad: media.

- [x] Persistir las reglas cruzadas si la otra PC reinicia: una regla vive en la PC del `from`; si
  esa PC reinicia el lienzo, hay que ver que sobreviva (hoy se guardan en `~/.lienzo`, falta probarlo
  con un reinicio real).
  - **Nota del 2026-10-10:** la regla de qué se conserva al arrancar quedó nombrada (`server.conservar_regla`) y probada releyendo `rules.json` (tests/test_pendientes_tanda3.py): la regla hacia otra PC sobrevive aunque su destino todavía no se vea. Falta el reinicio real en la otra PC.
  - **Cerrado el 2026-10-10:** reinicio real en ar-it33940: la regla `on_stop` de su coda (`e3e32f37`) hacia una sesión
    de la otra PC siguió en `GET /rules` (vive en ar-it33940, la PC del `from`) después de reiniciar su server dos veces.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 20. Gravedad: media.

- [ ] Pruebas reales pendientes (solo se probaron con transportes simulados): recuperación cuando una
  tarjeta remota ya no existe, y el reintento ante conexión rechazada.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 21. Gravedad: media.

- [x] Detectar el lienzo viejo de la otra PC por capacidades: hoy se reconoce por el texto «ruta
  desconocida» de la respuesta (`cablear` y el reenvío). Un campo de capacidades en el handshake
  (`/peer/health` o el emparejado) sería un contrato; el texto cambia sin avisar.
  - **Cerrado el 2026-10-10:** Contrato de capacidades en la salud (`protocol.CAPABILITIES`) desde el 2026-10-07; el 2026-10-10 la réplica de memoria también lo consulta (`memoria.replica`, tests/test_pendientes_tanda1.py).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 22. Gravedad: media.

- [x] **`xpc` + `purge_stale_xpc` con hilo y reloj fijo**: la purga corre en un hilo con un reloj fijo y
  una regla hacia otra PC solo guarda el flag `xpc`. Guardar `to_pc` en la regla y conciliar por peer
  al aplicar su snapshot: hoy un peer apagado frena la purga de las reglas hacia los demás.
  - **Cerrado el 2026-10-10:** Las reglas hacia otra PC guardan su PC y se concilian por peer al aplicar su snapshot (2026-10-07).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 23. Gravedad: media.

- [x] El espejo se reconcilia por rebote: una tarjeta fantasma se detecta cuando un envío vuelve con
  `unknown_session` (`mirror.forward` → `_tarjeta_fantasma`). Debería reconciliarse con un snapshot
  periódico o una secuencia en el SSE, no esperar a que alguien escriba.
  - **Cerrado el 2026-10-10:** Snapshots periódicos con protección ante eventos nuevos (2026-10-07).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 24. Gravedad: media.

- [x] **El enrutado owner→forward está repetido en ~10 handlers de `lienzo/server.py`** (`_route_session`
  + `mirror.MIRROR.forward` en cada ruta de `/sessions/<id>/...`): una sola función `route_or_local`.
  - **Cerrado el 2026-10-10:** `atender_accion` y `ACCIONES_SESION` centralizan las acciones de los dos listeners (verificado el 2026-10-07).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 25. Gravedad: media.

- [x] **`restorables_all` y `cablear` consultan en serie**: una PC lenta o caída suma su timeout al de las
  demás. Paralelizar las consultas por peer.
  - **Cerrado el 2026-10-10:** `restorables_con_fallas` usa `fan_out` paralelo (2026-10-07) y `cablear` crea las reglas en paralelo desde el 2026-10-10 (tests/test_pendientes_tanda1.py).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 26. Gravedad: media.

- [x] Timeout de acciones lentas por sufijo de ruta (`SLOW_ACTIONS`, `RESTORE_ACTION` y
  `_timeout_para` en `lienzo/federation.py`): una ruta nueva lenta se olvida y cae en los 5 s.
  Pasar el timeout como parámetro de `forward`.
  - **Cerrado el 2026-10-10:** `forward` recibe el timeout explícito (2026-10-07).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 27. Gravedad: media.

### UI

- [x] La tarjeta se queda en «Te necesita» con un permiso que ya no existe (medido el 2026-10-02): la tarjeta del Claude del gestor
  mostró durante unas 16 horas «Pide permiso» con el comando de un ruff de un subagente, desde un aviso (Notification) de las 05:06,
  aunque en su terminal no había ningún cartel. Ese permiso lo había aprobado yo hacía horas y la marca no se limpió. Confunde a
  quien mira el tablero y a la coordinadora, que gasta consultas en revisar. Los permisos de los subagentes (forks) de Claude Code
  salen en la terminal del Claude principal y el tablero no los distingue. Idea: cuando el estado dice permiso en la terminal
  y la pantalla ya no muestra el cartel («Do you want to proceed?» o «Enter confirm»), limpiar `needs` y volver al estado real.
  - **Cerrado el 2026-10-10:** Se limpia cuando la pantalla ya no muestra el cartel y nunca ante un fallo de lectura (`tests/test_mejoras.py::test_old_terminal_permission_requires_visible_prompt`).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 6. Gravedad: media.

### Conocimiento por proyecto

- [x] Replicar la base de conocimiento entre PCs con un protocolo explícito de propiedad,
  concurrencia y recuperación. El código de las etapas 1 a 5 de v5 §9 usa la base local de la
  PC que registra los encargos; un pull de Git no transfiere esa base. Se conservan todas las
  revisiones de informes y los duplicados se sugieren sin fusionarlos automáticamente.
  **Cerrado el 2026-10-23:** el sentido inverso anda (las capturas del encargo B, nacidas en 75727ff74069, están en la memoria de ar-it33940) y hubo un choque real en el proyecto de prueba `prueba-replica` (cambio del mismo nodo en las dos PCs a las 22:43:36): quedó en `replica_conflicto` con «gana el más nuevo, los dos quedan en el historial».

  Origen: v5 §9. Gravedad: media.

  Nota del 2026-10-09: diseño en `docs/propuesta-memoria-2026-10-08/anexo-c-replica.md` e
  implementación en `lienzo/replica.py` (cada PC trae de sus pares los cambios nacidos allá, por
  `/peer/conocimiento`, con cursores transaccionales; choques y duplicados para la coordinadora).
  10 pruebas con dos bases simuladas en un proceso. Falta probarlo entre las dos PCs reales.
  - **Nota del 2026-10-10:** primera réplica real: con las dos PCs en db12f5e, esta PC trajo de ar-it33940
    «replica con dee050ccab4f: 9 aplicados» (12:00:21, en `lienzo.log`). Falta ver el sentido inverso en el log de
    ar-it33940 y un choque real.

- [x] **Decidir qué PC es dueña de la base de cada proyecto mientras no haya base compartida.**
  Propuesta, sin decidir (pedido de la ronda 3):
  - Opción A, ninguna dueña (lo que hace hoy la réplica del anexo C): cada PC escribe en su base y
    trae lo de las demás; los choques quedan para la coordinadora. Lo bueno: no depende de que una
    PC esté prendida. Lo malo: puede haber choques y duplicados para revisar.
  - Opción B, dueña la PC de la carpeta (la del remote más viejo): las demás le reenvían las
    escrituras. Sin choques, pero si esa PC está apagada, las otras no escriben.
  - Opción C, dueña la PC donde corre la coordinadora de la ronda: lo natural mientras dura una
    ronda, pero cambia de ronda a ronda y un frente de otra PC escribe por la red.
  - Recomendación: A, que ya está implementada. B o C sólo si en uso real los choques resultan
    frecuentes. Las capturas no chocan (son inmutables); los choques posibles son veredictos dados
    a la vez en dos PCs.
  - **Decidido por Ariel el 2026-10-10: opción A, ninguna dueña.** Revisar sólo si los choques
    resultan frecuentes en uso real.
  - **Cerrado el 2026-10-10:** Decidido (opción A).

- [x] **Decidir la retención de las revisiones de informes y de las capturas.**
  Medido el 2026-10-10: un día cargado (1525 capturas, 990 KB de texto) suma 2,0 MB a la base;
  las revisiones de informes son unos 10 KB cada una. Propuesta, sin decidir:
  - Opción A, todo para siempre: del orden de 0,3 a 0,7 GB por año por PC en el peor caso.
  - Opción B, revisiones para siempre y capturas por 180 días, con un respaldo
    (`POST /conocimiento/<p>/respaldo`) antes de borrar: el conocimiento declarado no se pierde y
    la prosa vieja queda en el respaldo.
  - Opción C, recortar el texto de las capturas viejas a su primera línea y conservar hash y fecha.
  - Recomendación: A por ahora (el volumen es chico) y medir otra vez a los tres meses; si pasa
    de 1 GB, B. Las revisiones de informes conviene conservarlas siempre: son la procedencia de
    lo declarado.
  - **Decidido por Ariel el 2026-10-10: opción A, todo se conserva por ahora.** Queda volver a medir
    el tamaño de las bases hacia enero de 2027.
  - **Cerrado el 2026-10-10:** Decidido (opción A); volver a medir hacia enero de 2027, como dice la nota.

### Otros

- [x] Identidad de Codex en el barrido (hallazgo del cierre, 2026-10-07): `codex.exe` de
  sandbox/helpers podía ocupar una tarjeta con transcripción de una CLI ya cerrada. Se filtran
  subcomandos no interactivos y flags internos `--codex-run-as-*`, y la comprobación de vida
  también lee el comando. Si no se puede leer, no se supone una TUI. Focal: 51 pruebas pasan;
  no se mataron helpers ni procesos de aplicaciones. El PID 26924 ya no existía al verificar.
  Corrida backend posterior `2026-10-07T06-16-42.580Z-16520`: 993 pruebas pasan.
  Revisión y cinco roles en resultados; baseline sin aprobar, compuerta exit 2. Estas notas
  documentales se agregan después de medir; el código probado no cambia.
  - **Cerrado el 2026-10-10:** Implementado con pruebas focales el 2026-10-07; la batería del 2026-10-10 (1313 pruebas) las incluye.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 2. Gravedad: media.

- [x] Validación con `pruebas-agenticas`: obligatoria por la preferencia global de Ariel.
  Reutilizar la configuración del repo; registrar los cinco roles, logs y veredicto sin fijar baseline.
  - **Cerrado el 2026-10-10:** Compuerta PASS el 2026-10-10 sobre daf92bb: 7 de 7 casos y 5 de 6 mutantes muertos, con requisitos y casos aprobados.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 4. Gravedad: media.

- [x] **Coda: `stop_reason` del Stop sin mirar** (medido el 2026-10-02): el `Stop` trae `stop_reason` y el doc solo muestra
  `turn_complete`; ver qué otros valores existen (respuesta cortada que continúa, error) y usarlos en vez de adivinar.
  - **Cerrado el 2026-10-10:** Implementado el 2026-10-07 (lectura de `stop_reason` de CODA).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 7. Gravedad: media.

- [ ] **Probar `PreCompact`/`PostCompact` con una coda real**: solo hay prueba con eventos simulados, y falta correr
  `install.py` en las dos PCs para que coda los mande (toca `~/.coda/config.json`).
  - **Nota del 2026-10-10:** en esta PC los hooks ya estaban y con una coda real (CODA 1.4.0) el PreCompact llegó. El
    PostCompact no se vio: con cinco vueltas cortas coda contesta «Too few messages for compaction» y aborta sin mandarlo (ni
    Stop), lo que dejaba la tarjeta trabada; arreglado (`sessions.coda_compactacion_abortada`). Falta una compactación que
    sí ocurra (conversación larga) y la otra PC.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 8. Gravedad: media.

- [x] **`--coda-home DIR` aísla la configuración de coda** (está en `coda --help`): sirve para lanzar con `--model` sin pisar el
  modelo por defecto de la PC (ver el punto de `--model`). Falta ver cómo conserva el login.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 9. Gravedad: media.
  - **Cerrado el 2026-10-10:** probado con `coda --globant --coda-home C:\Users\ArielLevy\.coda-prueba-home`. Una carpeta
    nueva arranca en el alta (log: «the coda home is not set up (missing .secrets and/or empty global config)»); con
    `--globant` se elige el entorno (Clients) y se pega la clave una vez, que queda en `<carpeta>/.secrets`, y hay que
    reiniciar coda para que cargue el proveedor (antes da 401). Después contestó por el DGX. Cambiar el modelo ahí
    escribió el `config.json` de esa carpeta (`globant_dgx/Qwen3.8-27B`) y el de `~/.coda` siguió en
    `globant_dgx/GLM-5.3-Flash`: aísla el default. Sin `--globant` el alta no ofrece Globant. Que `launch.py` lo use solo
    queda como mejora, sin pedido.

- [ ] **La herramienta `read` de coda se traba** (medido el 2026-10-02): se evita (el adjunto a un coda se lee con
  el shell y los mensajes cortos se tipean directo), pero la causa sigue en coda: avisar a quien lo mantiene.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 11. Gravedad: media.

- [x] **`--model` en coda cambia el modelo por defecto de la PC** (medido el 2026-10-02): `coda --model X` se
  documenta como «para esta corrida», pero el `config.json` de esa PC pasó de `globant_dgx/Qwen3.8-27B` a
  `globant_dgx/GLM-5.3-Flash` a las 00:52:18, justo al lanzar el primer coda con GLM, y las sesiones
  lanzadas después sin modelo ya mostraban GLM. Efectos: se pisa el default del usuario sin que lo sepa
  y las comparaciones entre modelos no valen (la medición «Qwen contra GLM» de esa noche fue GLM contra
  GLM). Ideas: que `lanzar` con `model` avise si el agente es coda, que el lienzo lea el default antes
  y lo restaure al terminar el lote, o lanzar con un `--coda-home` propio para aislar la configuración
  (hay que ver cómo conserva el login).
  - **Cerrado el 2026-10-10:** Desde el 2026-10-10 lanzar una coda con `model` devuelve un `aviso` (tests/test_pendientes_tanda2.py). Aislar con `--coda-home` sigue en su ítem.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 12. Gravedad: alta.

- [x] (Revisar: desactualizado) «Coda no tiene hooks»: el 2026-10-02 las codas figuran `hooked=True`; antes nacía como tarjeta de barrido (`pid-NNNN`, sin título ni
  transcripción), cambia de id, y su estado no refleja que está trabajando. Un hook de coda daría
  título, estado y `last_reply` confiables.
  - **Cerrado el 2026-10-10:** Desactualizado: las codas figuran `hooked=True` desde el 2026-10-02.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 17. Gravedad: media.

- [x] Un solo modelo para todos los codas: Qwen en el DGX atiende de a poco; con 5 codas a la vez
  todos quedan en «Waiting for model». El coordinador tiene que escalonar el trabajo, no repartirlo
  en paralelo sin límite. `capacidad` mide RAM, no el cupo del modelo.
  - **Cerrado el 2026-10-10:** `coordinar.capacidad(pc, n, agent="coda")` cuenta las codas que ya corren en esa PC y deja entrar a lo sumo dos (`CODAS_EN_PARALELO`); lo demás se escalona (`tests/test_coordinar.py`, skill actualizado).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 18. Gravedad: media.

### Notas de implementación y aceptación trasladadas

#### Cierre de implementación del 2026-10-07

Las casillas se conservan pendientes de aceptación. Implementado en esta ronda:
limpieza de permisos con prompt visible (sin limpiar ante fallo de lectura), lectura
de `stop_reason` de CODA, contrato de capacidades y `launch_roots`, snapshots periódicos
con protección ante eventos nuevos, conciliación de reglas por PC, conexiones HTTP
reutilizables, timeout explícito, traspaso de trabajo entre PCs y cierre forzado Windows
con confirmación e identificación del proceso. `POST /run` exige un comando nombrado
en `run_allowlist` de la PC destino y una carpeta dentro de sus `launch_roots`; no se
habilitó ninguna lista ni se ejecutaron comandos remotos reales.

Validación final y revisión: evidencia en `pruebas-agenticas/resultados/` (ignorada por
Git), corrida `2026-10-07T06-02-08.125Z-26940`: cinco suites con código 0; 981 pruebas
backend y 117 UI pasan, además de lint, build y unitarias frontend. Cinco roles registrados
secuencialmente en `roles.json`; revisión en `revision-cierre.json`. Falta baseline aprobado:
el runner sale con 1 y la compuerta con 2; no se certifica PASS ni se aprueban propuestas.
Sin mutaciones ejecutadas. Esta nota documental se agrega después de la medición.

Siguen pendientes las verificaciones con CODA real y dos PCs, aislamiento de login/modelo
con `--coda-home`, capacidad del servidor de modelos, instalación NUC desatendida y
paralelización del cableado. La integración visual de specs/SDD de Kiro no está implementada.
La documentación de Kiro V3 confirma que ofrece un agente Spec nativo; eso no acredita
su integración en Lienzo. El canal cifrado de secretos ya estaba implementado, como
consta en «Hecho»; se quitó la propuesta duplicada.

Checklist conservado por pedido de Ariel (2026-10-07). Las casillas quedan pendientes de
su aceptación; las notas distinguen implementación, pruebas y verificaciones externas.

Verificaciones del 2026-10-07: `restorables_con_fallas` ya usa `fan_out` paralelo;
`atender_accion` y `ACCIONES_SESION` ya centralizan las acciones de ambos listeners;
`SSEClient` ya cambia el timeout de lectura después de conectar; CODA ya registra
`PreCompact` y `PostCompact` en `install.py`. No equivalen a pruebas reales en ambas PCs.
La PC `ar-it33940` figura desconectada en `/peers`; no se puede verificar allí en vivo.

## Pendientes del triage de docs

### Seguridad

- [x] Restringir los datos de GET /health antes de autenticar, también por túnel.
  - Evidencia: lienzo/server.py: Handler.do_GET, rama health anterior a _authed; devuelve sessions, pending y ts.
  - Origen: `docs/pentest-2026-09-07.md, B1` (historial de Git). Gravedad: **media**.
  - **Cerrado el 2026-10-10:** Sin autenticar (o por el túnel) `/health` sólo dice `ok` y `ts` (`salud_publica`, tests/test_pendientes_tanda1.py; verificado en vivo con `CF-Connecting-IP`).

- [x] Definir controles de sesión web y una vista para listar y revocar sesiones activas.
  - Evidencia: lienzo/auth.py: check sólo comprueba token y vencimiento; login guarda ip/ua y SESSION_DAYS vale 7. logout no ofrece administración de otras sesiones.
  - Origen: `docs/pentest-2026-09-07.md, B4` (historial de Git). Gravedad: **media**.
  - **Cerrado el 2026-10-10:** `GET /auth/sessions` y `POST /auth/sessions/<id>/revoke`, con la lista y el botón Cerrar en el diálogo de Authenticator (tests/test_pendientes_tanda2.py).

- [x] Agregar cuota de adjuntos por sesión.
  - Evidencia: lienzo/server.py: MAX_ATTACH limita cada pedido; lienzo/sessions.py: limpieza por ATTACH_MAX_DAYS, sin cuota acumulada por sesión.
  - Origen: `docs/pentest-2026-09-07.md, B5` (historial de Git). Gravedad: **media**.
  - **Cerrado el 2026-10-10:** 200 MB por sesión en `/attach`, 413 al pasarse (tests/test_pendientes_tanda2.py).

- [x] Acotar hilos y conexiones SSE simultáneas.
  - Evidencia: lienzo/server.py: QuietServer hereda ThreadingHTTPServer; el servicio SSE no tiene cupo global. El cupo MAX_SESSIONS de Chrome no cubre SSE.
  - Origen: `docs/pentest-2026-09-07.md, B6` (historial de Git). Gravedad: **alta**.
  - **Cerrado el 2026-10-10:** Tope de 64 streams (`MAX_SSE`), 503 con `Retry-After` al pasarse (tests/test_pendientes_tanda2.py).

- [x] Validar request_id antes de construir la ruta de respuesta a permisos.
  - Evidencia: lienzo/sessions.py: answer_pending usa os.path.join(ANSWERS, f"{request_id}.json") tras buscar el pendiente, sin validar el identificador cargado desde disco.
  - Origen: `docs/pentest-2026-09-07.md, I2` (historial de Git). Gravedad: **baja**.
  - **Cerrado el 2026-10-10:** `answer_pending` rechaza con 400 lo que no sea `[A-Za-z0-9_-]{1,100}` (tests/test_pendientes_tanda1.py; verificado en vivo).

### Multiplataforma

- [x] Resolver PID y destino del hook en Unix.
  - Evidencia: lienzo/hook.py: find_agent_pid usa procinfo.proc_info; lienzo/procinfo.py devuelve valores vacíos fuera de Windows. Sin TMUX_PANE en lienzo/*.py; el destino se obtiene por barrido.
  - Origen: `docs/plan-multiplataforma-2026-09-08.md` (historial de Git). Gravedad: **media**.
  - **Cerrado el 2026-10-10:** fuera de Windows `procinfo.proc_info` lee `/proc` (o `ps` en macOS) y el hook manda `TMUX_PANE`, que pasa a ser el `target` de la tarjeta de tmux (tests/test_pendientes_tanda3.py). Sin corrida en un Linux real, que sigue en «Verificar el servidor nativo».

- [x] Hacer portable --remote y el arranque de cloudflared.
  - Evidencia: lienzo/server.py: CLOUDFLARED apunta a Program Files (x86)/cloudflared/cloudflared.exe; tunnel_loop pasa creationflags=0x08000000 sin condición POSIX.
  - Origen: `docs/plan-multiplataforma-2026-09-08.md` (historial de Git). Gravedad: **alta**.
  - **Cerrado el 2026-10-10:** `cloudflared` del PATH y `creationflags` sólo en Windows. Probado en Windows; Linux y macOS siguen en «Verificar el servidor nativo».

- [x] Traducir rutas de adjuntos de Windows para los agentes de WSL.
  - Evidencia: lienzo/sessions.py: compose_send y run_send pasan rutas locales; no hay conversión con wslpath en lienzo/*.py.
  - Origen: `docs/plan-multiplataforma-2026-09-08.md` (historial de Git). Gravedad: **media**.
  - **Cerrado el 2026-10-10:** `tmux.ruta_wsl` traduce lo que se tipea a un agente de WSL (`/mnt/c/...`) (tests/test_pendientes_tanda2.py).

- [x] Informar backend y fuentes activas en /health.
  - Evidencia: lienzo/server.py: Handler.do_GET, rama health, sólo devuelve ok, sessions, pending y ts; lienzo/backend.py distingue fuentes.
  - Origen: `docs/plan-multiplataforma-2026-09-08.md` (historial de Git). Gravedad: **baja**.
  - **Cerrado el 2026-10-10:** `/health` autenticado o local trae `fuentes` (`win32`, `tmux`) (tests/test_pendientes_tanda1.py).

- [x] Descubrir y direccionar varias distros de WSL.
  - Evidencia: lienzo/tmux.py: _PREFIX = ["wsl.exe"] en Windows, sin selección de distro; backend.proc_key distingue fuente y PID, no distro.
  - Origen: `docs/porting-linux-2026-09-08.md` (historial de Git). Gravedad: **baja**.
  - **Cerrado el 2026-10-15:** `backend.py` consulta los panes de cada distro y `distro` va en la tarjeta (spec `docs/WSL.md`, 538ac22).

- [ ] Verificar el servidor nativo en Linux y macOS, incluido emparejamiento.
  - Evidencia: lienzo/backend.py: sweep; lienzo/tmux.py: _ps_all. El documento de origen registra simulación de plataforma y pruebas desde Windows/WSL, no una corrida nativa completa; esta revisión no ejecutó esas plataformas.
  - Origen: `docs/porting-linux-2026-09-08.md, Integrado a main; README.md, Limitaciones` (historial de Git). Gravedad: **media**.
  Avance 2026-10-22 (decisión 13, 3dbe685): server nativo en WSL Ubuntu emparejado en los dos sentidos, con tres bugs corregidos. macOS sin probar.

### Chrome remoto

- [x] Verificar en vivo la aprobación de conexión del Chrome habitual de Globant.
  - Evidencia: lienzo/browser_consent.ps1 y lienzo/browser_host.mjs: approveChrome implementan el pedido; docs/code-review-2026-10-07.md deja expresamente pendiente la prueba de ese perfil.
  - Origen: `docs/code-review-2026-10-07.md` (historial de Git). Gravedad: **media**.
  Hecho: e1bd847 (decisión 25), según Ariel.

- [ ] Sincronizar el portapapeles en modo ventana.
  - Evidencia: lienzo/browser_window.py no implementa clipboard. web/src/components/RemoteBrowser.tsx: onPaste manda texto local, pero eso no sincroniza el portapapeles remoto; el copy por CDP es otro modo.
  - Origen: `docs/code-review-2026-10-07.md` (historial de Git). Gravedad: **media**.
  Avance 2026-10-22 (69d0bb9): implementado y probado localmente (pegar texto hasta 16.000 caracteres; copia remota avisada sin contenido y traída con «Copiar acá»). Falta probarlo en uso real.

- [x] *(Opcional, 2026-10-15: Ariel lo descartó por ahora, el canal WebSocket anda bien.)* Evaluar transporte no ordenado para movimientos mediante WebRTC/UDP.
  - Evidencia: lienzo/browser_stream.py y lienzo/ws.py usan WebSocket ordenado; no hay transporte WebRTC/UDP para la entrada.
  - Origen: `docs/code-review-2026-10-07.md, Canal vivo` (historial de Git). Gravedad: **baja**.
  Obsoleto: Ariel lo descartó el 2026-10-15.

- [x] Medir latencia sostenida por LAN después del canal WebSocket.
  Hecho 2026-10-21 (encargo R, desde ar-it33940, 300 s): ida y vuelta mediana 12,6 ms / p95 33 ms; entre cuadros mediana 52 ms / p95 183 ms. Falta el tiempo cambio→vista.
  - Evidencia: lienzo/browser_stream.py: serve_viewer; docs/code-review-2026-10-07.md registra cuadros locales y la caída de ar-it33940 antes de medir el canal nuevo por LAN. No hay medición nueva en este encargo.
  - Origen: `docs/code-review-2026-10-07.md, Detective del canal vivo` (historial de Git). Gravedad: **media**.

### Federación

- [x] Incluir conexiones del espejo en GET /links.
  - Evidencia: lienzo/server.py: Handler.do_GET devuelve links.snapshot(); GET /rules sí agrega mirror.MIRROR.rules().
  - Origen: `docs/ronda2/` (historial de Git). Gravedad: **baja**.
  - **Cerrado el 2026-10-10:** `GET /links` suma `mirror.MIRROR.links()` (tests/test_pendientes_tanda1.py).

- [x] Unificar LIENZO_PEER_PORT entre pairing y el listener real.
  - Evidencia: lienzo/pairing.py lee LIENZO_PEER_PORT; lienzo/server.py no consulta esa variable para sus listeners.
  - Origen: `docs/ronda3/` (historial de Git). Gravedad: **baja**.
  - **Cerrado el 2026-10-10:** `--peer-port` toma por defecto `pairing._my_port()` (tests/test_pendientes_tanda1.py).

### UI

- [ ] Verificar un lanzamiento real en otra PC desde el selector de proyecto/PC del tablero; la UI está implementada y sus recorridos con fixtures pasan.
  - Evidencia: lienzo/server.py: accion_launch implementa POST /sessions/launch; la búsqueda de sessions/launch en web/src no tiene coincidencias.
  - Origen: `docs/ronda3/` (historial de Git). Gravedad: **media**.
  Avance 2026-10-21 (encargo R): `POST /sessions/launch` desde ar-it33940 hacia ariel anduvo (tarjeta, respuesta y `/exit`); el título pedido no llegaba y se corrigió con titulo_lanzado. Falta hacerlo desde el selector de la UI.

## Alcance de la consolidación

Se trasladaron 27 casillas previas y 18 pendientes del cuerpo del triage. Su resumen decía
16: omitía la verificación nativa de Linux/macOS y la inconsistencia de LIENZO_PEER_PORT.
No se cerró ninguna casilla ni se aprobó un baseline. Ese alcance era el del 2026-10-10.
El 2026-10-21, por autorización expresa, se incorporaron Plan e Ideas y el historial
de MEJORAS.md en este documento; no se modificaron sus decisiones por inferencia.

## Plan NUC e Ideas trasladados (origen: MEJORAS.md)


Objetivo: coordinar una o varias NUC sin pantalla desde una sola PC, con control total. Motivo real: la otra
PC perdio las credenciales de git, la sesion 4 del curso quedo sin publicar y no habia forma segura de
arreglarlo desde aca.

- [x] Acceso de emergencia: documentar Tailscale o RDP y mostrar en la tira de PCs si la NUC no responde.
  Hecho 2026-10-22 (decisión 24, 3dbe685): la tira ofrece Tailscale o Tailchrome según lo que tenga cada PC. Falta verlo con ar-it33940 real.

- [x] Arranque autonomo de la NUC (pedido por el usuario, 2026-10-03; sin implementar): `install.py --headless`
  Descartado 2026-10-22 (decisión 9); lo que sirve pasa a ar-it33940 (decisión 11, ítem nuevo).
   que deja auto-login, una tarea al iniciar sesion que levanta `lienzo-server.cmd`, plan de energia sin
   suspension y reinicio tras corte de luz. Las codas necesitan consola abierta: tiene que haber una sesion
   de usuario iniciada, un servicio no alcanza. Opt-in, y `install.py --headless --quitar` lo deshace.
   Ademas: que el server llame a `restaurar(todas=True)` al arrancar en una PC marcada `headless`,
   respetando la memoria libre.
- [x] **`POST /run` para comandos acotados en una PC remota** (pedido por el usuario, 2026-10-03; sin
  Hecho 2026-10-22 (decisión 10, d9aa9bb): `/peer/run` registra cada pedido y niega más variantes peligrosas de git. Falta cargar la lista por PC en `config.json` y probarlo entre las dos PCs.
   implementar): solo para peers emparejados, firmado como el resto de `/peer/*`, con una lista de
   comandos permitidos por PC en `config.json` (git status/fetch/log/cherry-pick/tag/push sin --force,
   pytest, ruff, cr-rate), cwd dentro de `launch_roots`, salida y codigo de retorno devueltos y log de cada
   corrida. Sin lista, no ejecuta nada. Motivo: para integrar la sesion 4 hubo que lanzar una sesion de
   Claude solo para correr 7 comandos de git, y esa sesion murio antes de contestar.

Los puntos 5 y 6 crean persistencia y ejecucion remota: antes de implementarlos los revisa y aprueba el
usuario, no se delegan sin que lo diga.


Nota de estado: «sin implementar» en el punto `POST /run` describe la propuesta del
2026-10-03. La implementación con `run_allowlist` está registrada en las notas del
2026-10-07 de este documento; siguen pendientes la aprobación humana de uso,
la configuración y la verificación remota real. No se habilita ninguna lista aquí.

### Propuestas de interfaz y reparto

- [x] Un panel «PCs» con la latencia y la memoria libre de cada una en vivo, y la cola del DGX.
  Hecho 2026-10-22 (5d4f820): la tira ya mostraba memoria y latencia; la latencia ahora se mide en el sondeo de 15 s. La cola del DGX no tiene fuente real y no se agregó.
- [x] `coordinar.repartir(proyecto, modulos, pcs)`: reparto automático según `capacidad`.
  Hecho 2026-10-22 (decisión 23, 3dbe685): sugerencia con módulos disjuntos, OK de Ariel, rama `ronda-<fecha>` sin `--force`. Falta probarlo entre dos PCs reales.
- [x] Aviso en el tablero cuando una tarjeta lleva N minutos `corriendo` sin que cambie su pantalla.
  Hecho 2026-10-22 (69d0bb9): «pantalla quieta · N min», 5 por defecto, configurable. Lo calcula el tablero cada 60 s; pasar el dato al server queda para después de la partición de sessions.py.

Las tres Ideas siguen pendientes como propuestas: los hechos históricos de salud de PCs
y `coordinar.estancada` no prueban el panel con cola DGX ni el aviso automático del tablero.

<a id="historial-mejoras"></a>

## Historial importado de MEJORAS.md

Registro histórico separado de la lista de trabajo. «Hecho» y los símbolos ✅ son
los originales; no son verificaciones actuales ni casillas cerradas en esta ronda.
Se mantienen nombres, cifras, errores, condiciones y decisiones de la fuente.
Las referencias a versiones antiguas describen su fecha, no activación vigente.

### Mejoras del lienzo, anotadas a medida que se usa

Registro de problemas y mejoras encontrados al usar Lienzo, sobre todo entre PCs.
Cada punto lleva evidencia de una sesión real. Los puntos nuevos quedan pendientes;
se pasan a «Hecho» cuando Ariel lo pide. Última actualización: 2026-10-08.

### Hecho

| Fecha | Mejora | Evidencia / motivo |
|---|---|---|
| 2026-10-01 | Recarga automática del server: `lienzo-server.cmd` lo relanza (salida 75) cuando cambia un `.py`; no relanza sobre código que no compila | había que parar y levantar el `.cmd` a mano tras cada `git pull`; la otra PC quedaba con código viejo |
| 2026-10-01 | Timeout de 70 s para `send`/`launch`/`attach` entre PCs (antes 5 s) | un envío tarda hasta 60 s en teclear; con 5 s aparecía como «sin conexión» aunque se hubiera tecleado |
| 2026-10-01 | Tarjeta fantasma: si la otra PC dice «sesion desconocida», el server la saca del tablero y pide el estado de nuevo | los envíos a una tarjeta que ya no existía rebotaban para siempre |
| 2026-10-01 | Reintento solo si el pedido no llegó (conexión rechazada); un timeout NO se reintenta | reintentar tras un corte a mitad podría teclear el texto dos veces |
| 2026-10-01 | Log de reenvíos que fallan (`→ <pc> POST …`) | no quedaba rastro de nada en el origen; no se podía saber si el pedido había salido |
| 2026-10-01 | `coordinar.enviar_seguro`: verifica que la tarjeta tomó el encargo y se recupera de 404/503 | un `200` solo dice que el server aceptó, no que se tecleó |
| 2026-10-02 | `enviar_seguro` rechaza caracteres de control en el texto | una ruta `D:\apps` sin escapar llegó como `D:<BEL>pps` y el server borró el carácter sin avisar: 4 codas buscaron rutas que no existían |
| 2026-10-01 | `coordinar.reubicar`: sigue a una tarjeta cuando cambia de id (`pid-NNN` → UUID) | `enviar_seguro` dio un falso negativo con el coda, que cambió de id al engancharse los hooks |
| 2026-10-01 | `coordinar.estancada(s, minutos)`: detecta un agente colgado (pantalla sin cambios y `corriendo`) | el coda quedó 5 min en «Waiting for model» y nadie lo vio |
| 2026-10-01 | `coordinar.capacidad(pc, n)`: mira la memoria libre antes de abrir sesiones | la otra PC tenía 0,76 GB libres con 6 codas abiertos |
| 2026-10-01 | `coordinar.lanzar_y_titular`: devuelve la tarjeta nueva, ya titulada | `lanzar` solo da el 200; hay que adivinar cuál tarjeta es la nueva |
| 2026-10-02 | Cableado entre PCs: reglas `on_stop` de los frentes de la otra PC hacia la coordinadora (5 reglas, cruzan PC) | no había nada cableado: la coordinadora tenía que consultar cada frente a mano |
| 2026-10-01 | `SKILL.md`: secciones «Mandar un encargo a otra PC…» y «Repartir en otra PC: lo que ya salió mal una vez» | todo lo anterior, para que la próxima ronda no repita los tropiezos |
| 2026-10-02 | Selección múltiple con Ctrl en el tablero: Ctrl+click suma o saca tarjetas; en los chips de proyecto y de PC suma o saca del filtro (varios a la vez); barra con «Marcar las visibles», «Enviar a todas», «Interrumpir» y «Limpiar»; Esc pela una capa por vez | pedido del usuario; 20 pruebas Playwright nuevas |
| 2026-10-02 | Las pruebas de interfaz ya no dependen del server real: sin `peers` simulados, `/peers` devuelve lista vacía (antes caía al server, que ahora tiene un peer emparejado) | `pcs.spec.ts:58` fallaba solo porque la PC tiene un peer; la de emparejamiento esperaba la frase vieja de 6 palabras |
| 2026-10-02 | A un coda, el adjunto se lee con el shell: el aviso del mensaje largo le pide leerlo con `type` y no con `read` (que se traba en coda) | 4 codas colgados más de una hora en «usando read»; con mensajes cortos y lectura por shell las mismas revisiones terminaron en 2 min |
| 2026-10-02 | **Las reglas pasan de la tarjeta provisional `pid-N` a la real**: antes solo se trasladaban en `continue_session` | un agente recién lanzado y cableado perdía su regla al llegar su primer hook |
| 2026-10-02 | **`lanzar_y_titular` cablea por defecto** la tarjeta nueva a la coordinadora | tres codas lanzados sin regla: no avisaban al terminar |
| 2026-10-02 | Elegir el modelo al lanzar (`--model`, coda, claude y codex) | usar GLM 5.3 Flash en la otra PC (ojo: en coda el `--model` cambia el modelo por defecto de esa PC, ver Pendiente) |
| 2026-10-02 | Firma sin query: `signed_headers` firma la ruta sin `?…`, como la verifica el receptor | `/turns` y `/digest` de una tarjeta de otra PC daban 401 «firma invalida» porque el emisor firmaba `?n=…` |
| 2026-10-02 | **El aviso `on_stop` de coda espera 15 s y se cancela si la tarjeta volvió a trabajar** (la coda sí manda hooks: el Stop llega en medio de un turno) (`ON_STOP_SETTLE_S` en `lienzo/rules.py`) | la regla avisó «terminó» de B y de E cuando seguían trabajando (Stop intermedio: compactación o hueco entre herramientas; causa exacta sin confirmar) y la coordinadora leyó un `last_reply` viejo |
| 2026-10-02 | Compactación de coda: `install.py` registra `PreCompact` y `PostCompact`; la tarjeta queda marcada «compactando» (vence a los 10 min) y ni el `Stop` ni `on_stop` cuentan como fin de turno | B y E mostraron «terminó» mientras compactaban; el doc de coda (`hooks.md`) lista esos dos eventos |
| 2026-10-03 | Los botones Permitir/Denegar de coda vuelven si el permiso sigue abierto 20 s después de contestar (`CODA_SENT_RETRY_S`): la marca `where: "enviado"` los escondía para siempre | la tarjeta de D tuvo un permiso real abierto horas sin botones; el usuario: «no me aparecen los yes en lienzo» |
| 2026-10-03 | `coordinar.cablear` y `regla_informe` **fallan claro si `YO` está vacío** | con `YO` vacío el server contestaba 404 «sesion destino desconocida» y parecía que la tarjeta nueva no existía |
| 2026-10-03 | Un 401 entre PCs dice el motivo y qué hacer: `federation.causa_401` mide el reloj contra el `Date` de `/peer/hello` y el error queda «la otra PC no acepta mi firma (…). Reiniciá su lienzo; si sigue, reemparejá» | a las 20:02 todo dio «firma invalida» pelado y el tablero quedó mudo |
| 2026-10-03 | El encargo largo a una coda se ejecuta: el aviso del adjunto le pide ejecutar sin resumir ni pedir confirmación | las codas de las sesiones 3 y 4 resumieron el encargo y esperaron un segundo «arrancá» |
| 2026-10-03 | `coordinar.informe(s)`: el `last_reply` solo si es un informe (None con «usando bash» o mientras corre) | la coordinadora confundía el estado de herramienta con el informe |
| 2026-10-03 | Aprobador oficial con lista permitida (`skills/lienzo/aprobador.py`, `Politica` + `vigilar`): frena lo truncado, lo peligroso, rutas, `rm` y pushes no autorizados | los permisos largos se revisaban a mano y dos aprobadores sueltos en Temp tuvieron bugs (tramo vacío, `rm` de varios destinos) |
| 2026-10-03 | Temperatura en cualquier PC: `health` lee todas las zonas térmicas (y `MSAcpi` si hay permisos) y elige `\_TZ.THRM` o, si no está, la zona plausible más caliente (25–120 °C) | la otra PC no tiene `\_TZ.THRM` y su `temp_c` quedaba siempre en None; esta PC marcó 95 °C |
| 2026-10-03 | Temperatura desde LibreHardwareMonitor: `health` lee primero `http://127.0.0.1:8085/data.json` (paquete del CPU, o el sensor real más caliente sin contar límites ni umbrales) y si no contesta sigue con WMI; URL en `LIENZO_LHM_URL`. Cada fuente es una `FuenteTemperatura` (clase abstracta: `leer` + `elegir`) en la cadena `FUENTES`; una fuente rota da None sin cortar la cadena y su motivo va al log al cambiar de estado, igual que el pedido de salud a otra PC (`mirror._poll_health`), que antes fallaba en silencio | el Dell Pro 14 no tiene zonas térmicas y MSAcpi da «no soportado» (0x8004100c); LHM 0.9.6 no lee el CPU de esa PC y por ahora da la RAM (~47 °C) |
| 2026-10-03 | Una sola regla de capacidad: `health.agentes_que_entran` (reserva 1,5 GB + 0,7 GB por agente); el server la usa en `/restaurar` y la publica como `agentes_libres` en la salud de cada PC, y `coordinar.capacidad` la lee de ahí | las constantes estaban repetidas en `server.py` y `coordinar.py` (punto pendiente «Capacidad de memoria duplicada») |
| 2026-10-03 | **`drop_session(..., muerta=True)` en vez de leer el texto de la razón, y `ended_on_purpose` por lista blanca** (`restore.ON_PURPOSE`): una razón nueva de SessionEnd cuenta como muerte a restaurar | dos puntos pendientes: el texto usado como protocolo y la lista negra que perdía sesiones con razones nuevas |
| 2026-10-03 | Latencia por PC: cada reenvío suma su latencia y `/peers` muestra `latencia_ms` (mediana de los últimos 50); las acciones que salen bien quedan en el log con sus ms y las lecturas solo si pasan de 2 s | antes solo se logueaban los reenvíos que fallaban y no había cómo ver una PC que se vuelve lenta |
| 2026-10-03 | Tira de PCs con CPU, latencia y alerta: cada chip muestra memoria, CPU, temperatura y latencia, y se pone en rojo (con el motivo en el título) si la PC pasa de 85 °C o no le entra otro agente | pedido de Ariel: ver la salud de todas las PCs; esta PC marcó 95 °C y nadie lo veía |
| 2026-10-03 | Plan NUC, punto 1: secretos entre PCs (`lienzo/secretos.py`, `POST/GET /secrets`): cifrados con la clave del par (keystream HMAC-SHA256 y encrypt-then-MAC), de un solo uso, vencen a los 10 min, se leen desde cualquier PC de la LAN (`?pc=` para los de otra PC) y nunca van a un log, un adjunto ni una respuesta. Destino `git` los guarda con `git credential approve`; `coordinar.pasar_credencial_git` copia la credencial de esta PC sin que el agente la vea | la otra PC perdió el login de git y no había forma segura de pasarle un token |
| 2026-10-03 | Plan NUC, punto 2: credenciales de git en la salud (`git_auth` por cada url de `git_check` en `~/.lienzo/config.json`, `git ls-remote` cada 5 min sin ventana de login); la tira de PCs se pone en rojo con «credencial de git vencida» | detectar el login vencido antes de que la coda llegue al push |
| 2026-10-03 | Plan NUC, punto 3: aviso de sesión que murió con un encargo a medias: si el proceso desaparece estando `corriendo` o `te_necesita`, se avisa a los destinos de sus reglas con el `coordinar.restaurar(...)` listo para pegar | una coda de la sesión 4 murió sin contestar y nadie se enteró |
| 2026-10-04 | Los avisos siguen a la coordinadora que se reabre: si muere la destinataria de reglas, quedan en espera 24 h (`parked_to`) en vez de borrarse, y una sesión nueva del mismo agente en la misma carpeta las hereda, acá y en las otras PCs (`POST /rules/retarget`, también a mano) | la coordinadora del gestor se cerró y se reabrió con otro id y se borraron los avisos de todas las codas del curso |
| 2026-10-04 | Los permisos DENEGADOS llegan al lienzo (coda por su log, `decision: deny`; Claude, Codex y Pi por la transcripción): la tarjeta muestra «Denegado: herramienta», el comando y el motivo, con «Autorizar y que reintente»; lo que rechaza el humano no cuenta | en la otra PC había denegaciones que nunca llegaban |
| 2026-10-04 | Auto-aprobar TODO (peligroso, a pedido): check en negro en el menú ⋯, con confirmación y barra negra arriba mientras está prendido; vale para todas las PCs emparejadas y solo se prende desde la LAN. Patrón de proveedores (`lienzo/autoaprobar.py`): `PendientesDeHook` (Claude, Codex, Pi) y `DialogoDeCoda`; no contesta preguntas con opciones y cada aprobación queda en el log como AUTO-APROBADO | pedido de Ariel |
| 2026-10-04 | **`propose_policy` de coda se ve como permiso**: esa herramienta abre «Approval Required» sin dejar un `ask` en el log; ahora el `PreToolUse` pone la tarjeta en «te necesita» con Permitir/Denegar (y el auto-aprobar la toma), y la próxima herramienta la libera | reporte de la coordinadora: una coda de la otra PC quedó esperando la aprobación de una regla y la tarjeta seguía en «corriendo» |
| 2026-10-04 | Refactor, ola 1 (plan del 2026-10-04, ahora en esta bitácora): 4 revisiones de diseño, 2 adversariales y 50 commits de 4 agentes: sin errores silenciados en hilos y archivos, concurrencia bajo el lock, aprobador endurecido, `subproc.correr`, cuerpo sin leer antes del login, espejo que no se congela, SPAKE2 en el emparejamiento | pedido de Ariel: código refactorizado, sin errores silenciados, con patrones que apliquen |
| 2026-10-04 | Permisos de coda que nadie veía: (1) con auto-aprobar prendido, el hook `PreToolUse` de coda (ahora sincrónico) contesta `allow` y el cartel ni aparece; (2) si igual aparece, una coda «corriendo» quieta 8 s tiene su pantalla mirada (cada 10 s como mucho) y, con el cartel, pasa a «te necesita» con el comando; (3) el `ask` del log se ve aunque el inicio del turno quede fuera de la ventana | dos codas de la otra PC esperaron una hora un `npm run build` sin que el tablero ni el auto-aprobar lo vieran |
| 2026-10-04 | Refactor, ola 2: acciones de tarjeta en una tabla compartida por `Handler` y `PeerHandler` (con prueba de paridad antes), registro de agentes en `agentes.py`, `CacheEnSegundoPlano` y una sola escritura atómica (`atomico.py`), cliente de API tipado, `<CardNeeds>` y `useCardActions`, `rules_api.py`, `JsonHandler` y `tarjeta_texto.py`; además `hook.py` anota un `config.json` corrupto en vez de callarse | el plan del 2026-10-04 completo; la suite sigue verde |
| 2026-10-04 | Reinicio explícito: `POST /restart` y `coordinar.reiniciar(pc)`; el server ya no se reinicia solo al cambiar un `.py` (salvo `auto_reload: true`) | se reiniciaba en medio del trabajo de los agentes: 503, capturas y pruebas cortadas (pedido de Ariel) |
| 2026-10-04 | Bugs 1 a 4 del gestor: la tarjeta real hereda el título de la provisoria; el 503 entre PCs dice el motivo (timeout, corte, reiniciando); `lanzar_y_titular` arreglado; el diálogo de confianza de Claude se reconoce, pasa la tarjeta a «te necesita» y `/send` contesta 409 `dialog_open` (lo decide el humano, nadie lo acepta solo) | informes del gestor en nombre de Ariel |
| 2026-10-04 | Cuota de agentes en la salud (mejora 5): `cuotas` por agente; coda por el último error 154 de su log contra el último consumo de `coda.db` (sin gastar tokens), Claude/Codex/Pi por el `limit_until` de sus tarjetas; lanzar una coda sin cuota da 409 y la tarjeta dice «sin cuota» en vez de «terminó» | en una PC toda corrida de coda daba «Quota exceeded» y el tablero no lo mostraba |
| 2026-10-04 | **`pasar_credencial_git` vuelve a andar** (bug 6): `git credential fill` prueba con `path=` antes que solo el host | el GCM con OAuth genérico quería abrir una ventana de login y el pedido daba 404 |
| 2026-10-04 | Credencial de git aparte en la tira, en violeta: el chequeo distingue `vencida` (401/403), `sin_red`, `timeout` y `error`, y la tira muestra cada motivo con su host fuera de la alerta roja | el aviso de git en rojo se confundía con memoria y temperatura, y «error» para todo no decía si había que pasar otra credencial o mirar la red (pedido de Ariel, mejora 7) |
| 2026-10-04 | La credencial de git se prueba solo de los repos en uso (bug 9): las urls salen del remote `origin` https de cada repo con una sesión viva en la PC (hasta 1 h después de la última) más las fijas de `git_check`; la tira muestra host y repo | la tira seguía diciendo «vencida» por un proyecto que Ariel ya no usaba, porque la lista era solo `git_check`, a mano |
| 2026-10-04 | El diálogo de confianza sin números se reconoce (pedido de la coordinadora de chesstudia): `screen.dialog` lee también la lista sin número, con el cursor y el pie «Enter to confirm», y la marca `teclas: flechas`; `answer_dialog` la contesta con flechas, relee la pantalla y recién ahí Enter; `send.py` y `tmux.py` suman `--key up/down/enter` | en ar-it33940 `dialog` daba None, el encargo + Enter eligió «No, exit» y la sesión murió como `pid-6844` |
| 2026-10-04 | Un chip por proyecto aunque esté en varias PCs: la tira de proyectos junta las sesiones que comparten `repo_key` o el nombre del repo (sin mayúsculas), suma el conteo y el chip filtra las de todas las PCs | «chess» salía dos veces en el menú, una por PC: en una la carpeta tenía remote y en la otra no (pedido de Ariel) |
| 2026-10-04 | La cuota de coda solo se muestra con coda en uso (bug 10): `cuotas()` y `coda_cuota` del snapshot la traen si hay una tarjeta viva de coda en la PC (hasta 1 h después de la última); el 409 de lanzar una coda sin cuota sigue mirando la cuota real | la tira ponía la PC en rojo con «sin cuota: coda» sin que nadie usara coda, por un error viejo de su log |
| 2026-10-07 | **Chrome remoto en vivo por WebSocket** (`lienzo/ws.py`, `browser_stream.py`, `browser_window.py --stream`): la PC dueña captura sola y empuja cada cuadro apenas cambia (parche de la región sucia, acuse por cuadro, nunca más de 2 en vuelo), el mouse y el teclado salen por el mismo canal sin cola ni timer, entre PCs cada mensaje va sellado con contador (sin replay ni reorden). `secretos` pasa a SHAKE-256 + XOR de enteros: 1 MB en 14 ms en vez de cientos. Bug corregido: cada cuadro delta mataba el worker (`previous` pisado, `SelectObject` con una tupla) y el siguiente pedido lo relanzaba. Un menú o desplegable de Chrome al frente ya no se cierra al enviar entrada. Pruebas de interfaz de Chrome arregladas (menú ⋯ cerrado al entrar, PNG de ejemplo corrupto) y la de federación rota desde f91fdce | medido por LAN antes del cambio: mouse 15 ms por la API pero 1,6 s por cuadro de 757 KB y 502 al segundo cuadro; en local después: canal en 4 ms, 27 cuadros/s sobre una ventana de Meet. Detalle en el historial de git (`docs/code-review-2026-10-07.md`) |
| 2026-10-08 | **Cuenta de GitHub por repo** (`lienzo/cuenta_github.py`): `gh auth git-credential` sólo sirve la cuenta activa (con `ariel-levy_globant` activa, el push a `arielelevy/lienzo` daba 403 y la tira decía «vencida»); health fija cada repo vivo de github.com, en su `.git/config` y sólo para github.com, a la cuenta con `permissions.push` (dueño del repo, activa, resto) con un helper que saca el token con `gh auth token --user` al usarlo, y ante «vencida» vuelve a elegir y mide otra vez | `git push` en `D:/Apps/lienzo` devolvía `Permission to arielelevy/lienzo.git denied to ariel-levy_globant` con la cuenta de Globant activa; con el repo fijado, `git credential fill` responde `username=arielelevy` y el push en seco pasa aunque la activa sea otra |
| 2026-10-08 | **Auto-aprobar los permisos que la TUI dibuja como diálogo** (`autoaprobar.DialogoDePermiso`): el «Would you like to run the following command?» de Codex (y el «Do you want to proceed?» de Claude) no pasa por ningún hook; el barrido de pantalla lo deja en `dialog` y el auto-aprobar elige la primera opción «Yes» con `answer_dialog`, reintentando a los 20 s si sigue abierto; una pregunta de verdad, «Switch model?» o la confianza en una carpeta no se tocan | la tarjeta de Teorema (Codex) quedó en «Espera que elijas en la terminal» con el auto-aprobar prendido |
| 2026-10-08 | **Foco de Chrome remoto con toque de Alt** (`browser_window.Windows.focus`): Windows sólo deja cambiar la ventana activa al proceso que recibió la última entrada; antes de enganchar el hilo del frente, el worker se vuelve ese proceso con un Alt sintético (`keybd_event` abajo y arriba) y vuelve a pedir el frente. Sin ventana al frente (PC bloqueada) lo dice en vez de «no permitió activar Chrome» | captura de Ariel del 2026-10-08 11:33: «Windows no permitió activar Chrome; no se envió la entrada» con el escritorio abierto y otra ventana al frente |
| 2026-10-08 | **La pregunta de un diálogo se busca hacia arriba** (`screen._armar`): Codex dibuja el comando entero entre «Would you like to run the following command?» y las opciones; con un `python -c` largo la pregunta quedaba más de 12 líneas arriba y la tarjeta mostraba un pedazo del comando como pregunta. Ahora se toma la última línea (hasta la regla o 40 líneas) que arranca como pregunta de la TUI; además `opcion_de_permiso` reconoce un permiso por su opción «don't ask again» aunque la pregunta se haya leído mal | tarjetas Teorema y A del 2026-10-08 en «Espera que elijas en la terminal» con la «pregunta» «smartBI/claude-skills/lienzo');import coordinar as»; al reiniciar, las dos se aprobaron solas (12:46:10) |
| 2026-10-08 | **El permiso dibujado como diálogo lo reconoce cada perfil** (`agentes.Perfil.permission_option`, `permission_reason`): Claude («Do you want to proceed/make/...»), Codex («Would you like to run», o la opción «don't ask again»), Kiro («requires approval» con Allow/Deny); Pi y coda no. **La tarjeta dice por qué el auto-aprobar no contesta un diálogo** (`auto_aprobar_omitido`: confianza en una carpeta, cambio de modelo, pregunta con opciones), y se borra al cerrarse el diálogo o al apagar el auto-aprobar. **Prueba de punta a punta real** (`pruebas-agenticas/e2e_autoaprobar.py`): lanza un Codex desde el lienzo, le pide un comando y espera el «AUTO-APROBADO (dialogo)» de esa sesión; cierra la sesión al final | la lista global de preguntas en inglés iba a quedar corta; «Espera que elijas en la terminal» no decía si fue decisión o falla; corrida 2026-10-08 13:09: veredicto ok (pid-20716, aprobado a las 13:09:38) |
| 2026-10-08 | **Foco de Chrome remoto: más trucos y un aviso que dice quién tiene el frente** (`browser_window.Windows.focus`, `describe`): tras Shift y AttachThreadInput se prueban `SwitchToThisWindow` (lo de Alt+Tab) y minimizar/restaurar, con el tiempo de bloqueo del frente en cero para la sesión (SPI_SETFOREGROUNDLOCKTIMEOUT, sin persistir); si igual falla, el error dice «Al frente está: clase · título · proceso» | desde la otra PC seguía «Windows no permitió activar Chrome» con el toque de Shift; sin saber qué ventana tenía el frente no se podía diagnosticar |
| 2026-10-08 | **Chrome remoto con la otra PC bloqueada: lo dice de entrada** (`browser_window.focus`): si al frente está LockApp.exe (la pantalla de bloqueo de Windows) no prueba ningún truco y avisa «La PC está bloqueada: desbloqueala allá». Con la sesión bloqueada ningún programa recibe entrada; la imagen sí se sigue viendo | medido desde la otra PC: «Al frente está: Windows.UI.Core.CoreWindow · Pantalla de bloqueo predeterminada de Windows · LockApp.exe» |
| 2026-10-08 | **Conocimiento por proyecto, etapa 1** (`lienzo/conocimiento.py`, `conocimiento_api.py`, `coordinar.proyecto/abrir_ronda/encargo/encargo_enviado/entregar/cerrar_ronda/conocimiento`): base SQLite privada por proyecto en `~/.lienzo/proyectos/<proyecto>/` (FTS5 + CTE), proyectos con identidad propia (remotes y carpetas por PC, no `repo_key`), rondas, encargos con el cuerpo guardado, entrega explícita de informes con hash y revisión (idempotente), nodos tipados con estado y tabla de transiciones por rol, vínculos tipados sin ciclos, historial de cambios, búsqueda BM25 con expansión por el grafo; el server observa de las sesiones con encargo el cierre, la vuelta a viva, el permiso denegado, el error de API y la muerte a medias (incidentes `observado`, una vez por clave). Escrituras sólo desde la LAN; `enviado` exige una tarjeta que el lienzo conozca. Diseño: `docs/propuesta-memoria-2026-10-08/v5.md`; etapas 2 a 5 en PENDIENTES.md | pedido de Ariel del 2026-10-08; proyecto `lienzo` registrado en vivo con su primera ronda; 19 pruebas focales; corrida agéntica `2026-10-08T21-12-35.952Z-40372`: cinco suites en 0, 1144 backend y 119 UI; code review (high) con diez hallazgos corregidos; sin baseline (compuerta 2) |
| 2026-10-08 | **Conocimiento por proyecto, etapa 2: el bloque `conocimiento` del informe** (`conocimiento.extraer_bloque/validar_bloque/_incorporar_bloque`, `coordinar.INSTRUCCION_CONOCIMIENTO`): el informe termina con JSON (`version`, `nodos`, `vinculos`); el server lo valida entero (ids locales únicos, tipos de hallazgo a evidencia, campos obligatorios por tipo, relaciones del frente, extremos por id local o `nodo:<id>`, motivo en elige/descarta, decisión con elige o descarta, regla con derivada_de) y lo incorpora en la transacción del informe: estado inicial por tipo, ronda del encargo, `declarado_en`, hallazgos `encontrado_por` la sesión. Con un error no entra nada y `datos.conocimiento` trae los errores por posición; el reenvío devuelve los mismos ids. `POST /nodos` exige lo mismo; `enviado` sólo con tarjetas de esta PC (409 para una espejada) hasta la base compartida; cerrar una ronda cerrada es 409; el esquema se decide por `user_version` | primer uso real: informe A r2 del proyecto `lienzo` con 10 nodos y 10 vínculos, buscables y expandibles; 27 pruebas focales; corrida agéntica `2026-10-08T23-00-24.878Z-34616`: cinco suites en 0, 1152 backend y 119 UI; segundo code review (high) con diez hallazgos corregidos; sin baseline (compuerta 2) |
| 2026-10-09 | **Memoria sola por carpeta** (`lienzo/captura.py`, anexo A de v5): proyecto = carpeta (raíz del repo; un worktree es el del repo principal); la primera vista de una tarjeta crea el proyecto y su sesión, y cada pedido, respuesta final, envío, regla `on_stop` y aviso queda como captura `observado` (tabla aparte, inmutable, con FTS) por una cola con hilo propio. Secretos con forma conocida tapados, adjuntos sólo por nombre, carpetas temporales afuera. Una respuesta con bloque `conocimiento` es un informe (si la sesión tiene un encargo enviado, lo entrega). Texto con U+FFFD o mojibake rechazado con línea y columna, y reparación auditada del mojibake. `preguntar(prosa=True)` busca en cuerpos y capturas, aparte. Los cuerpos se escriben byte por byte (con `atomic_write` en modo texto ningún informe verificaba su hash: 5 de 5) | pedido de Ariel del 2026-10-09 («si pasa por lienzo se registra»); server real aislado: 12 de 12 pasos; volumen medido: hasta 990 KB de texto por día suman ~2 MB a la base |
| 2026-10-09 | **Memoria v5 completa y replicada entre PCs** (`veredictos.py`, `aprendizaje.py`, `replica.py`, anexos B y C de v5): auditoría diseño → código con 15 huecos cerrados (respaldo en las transiciones, `vigente_desde` por cualquier ruta, cuestionar al confirmar un `repite`, «¿por qué se descartó?», encargos abiertos, briefing en Markdown, fusión por mejor puesto, incidentes por agente, reincorporar un bloque, evidencia, respaldo con la API de backup); réplica por `/peer/conocimiento` con cursores transaccionales, reloj híbrido, choques y duplicados para la coordinadora; panel con «Capturado» y prosa; 16 hallazgos de dos revisiones corregidos (`code-review-2026-10-10.md`, en el historial de git) | corrida agéntica `2026-10-10T04-01-11.975Z-29204`: cinco suites en 0, 1291 backend y 126 UI; 5 de 5 mutantes de memoria muertos y el de control vivo; copia de la base viva migrada de 1 a 3 sin pérdida; sin baseline (compuerta 2); la réplica entre las dos PCs reales queda por probar |

### Puntero histórico a pendientes

La lista única de pendientes está en PENDIENTES.md.


### Antecedentes del Plan NUC (puntos 1 a 3)

1. ✅ (hecho, ver arriba) Canal cifrado para secretos (ver Ideas): `POST /secrets`, vence en 10 min, un solo uso, solo en
   memoria o en el almacen de credenciales de Windows de la PC destino, nunca en adjuntos ni en logs.
2. ✅ (hecho) Chequeo de credenciales de git: `GET /peers` muestra `git_auth: ok|vencida` probando `git ls-remote`
   con timeout corto, para detectar el problema antes de que la coda llegue al push.
3. ✅ (hecho) Aviso de sesion que murio sin contestar: una tarjeta que pasa a `muerta` con un encargo pendiente
   dispara aviso a la coordinadora (paso con la sesion de integracion de la sesion 4 del curso).

### Ideas: decisión histórica sobre secretos


Canal cifrado de secretos: ya implementado; ver «Hecho», Plan NUC punto 1 y
`lienzo/secretos.py`. La propuesta anterior estaba duplicada y desactualizada.

### Turnos: cupos, modo exclusivo y liberación por inactividad (OpenSyync K, 2026-10-27)

Medido en la ronda R7: la coordinadora tuvo que pasar el turno `motores` a mano dos veces.
La dueña lo retenía sin ningún proceso pesado vivo, mientras otra esperaba en la cola.
Ariel pidió que sea automático.

- **Cupos por recurso.** Política `cupos: N`, por ejemplo 2 para `motores` si hay memoria
  libre. Varios dueños a la vez, cada uno con su vencimiento.
- **Modo exclusivo.** `exclusivo: true` al pedir el turno, para mediciones de tiempo. Espera a
  que no haya otros dueños y bloquea nuevos otorgamientos mientras dura.
- **Liberación por inactividad.** El dueño declara sus PIDs, o el server mira los hijos del
  proceso de la sesión. Si en X minutos no hay un proceso pesado vivo y hay cola, el turno pasa
  al siguiente y se le avisa al dueño anterior, que vuelve a la cola si lo pide.
- **Aviso al otorgar.** Al siguiente de la cola se le avisa sin despertar a la coordinadora.

### Registrar apagados y suspensiones de la PC (OpenSyync K, 2026-10-27)

La PC se apagó o suspendió de 00:42 a 09:25. Dos Codex quedaron en «Working» con 0
actividad: uno retomó solo al volver y el otro necesitó un Escape. La coordinadora lo
interpretó como un cuelgue del modelo, porque nada distinguía los dos casos.

- Detectar la reanudación: un salto entre el reloj monotónico y el de pared, o los eventos
  de Windows Kernel-Power 42/107 y 1074/6006.
- Guardar el intervalo `pausa_pc {desde, hasta}` y mostrarlo en el tablero.
- Descontar ese intervalo en la auditoría (`idle_evitable`, «working» largo) y en los
  vencimientos de turnos.
- Al reanudar, revisar cada sesión que estaba `corriendo`. Si su transcript no avanza en N
  minutos, avisar a la coordinadora que necesita un Escape y un reenvío.

### Revisar el plazo del E2E de tarjetas ajenas (2026-10-28)

- [ ] `pruebas-agenticas/tarjetas_ajenas_e2e.py:106`: espera hasta 120 s la eliminación de la tarjeta, pero `lienzo/state.py:58` fija `DEAD_KEEP_S = 120` y `lienzo/sessions.py:2261` elimina con `edad > DEAD_KEEP_S`. El log muestra la regla estacionada correctamente y la herencia posterior correcta, pero `tarjeta del frente borrada: False (120 s)` hace fallar el caso. Revisar el contrato y el margen del caso, sin regenerar baseline para ocultarlo. Reproducir con el runner sobre `pruebas-agenticas/tarjetas-ajenas-N.json`; evidencia en `resultados/tarjetas-ajenas-N/salidas/tarjetas-ajenas-e2e.log`. Detectado al corregir la lectura de las conversaciones de Claude SmartBI.
