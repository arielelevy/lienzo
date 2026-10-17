# Code review 2026-10-16: skills/lienzo-infografias

Revisión con el skill `code-review` (nivel medio) de la skill nueva de infografías, sus SVG en
`docs/img/infografias/` y `tests/test_infografias.py`. Nueve hallazgos, ninguno rompía algo.

| # | Hallazgo | Estado |
|---|---|---|
| 1 | `--check` aprobaba aunque la página tuviera errores de consola o scroll lateral | Corregido: exige `console: clean` y `scrolls sideways: no` |
| 2 | El `aria-label` decía «lámpara blanca», que en el tema claro es negra | Corregido: «lámpara resaltada» |
| 3 | La leyenda atribuía el hook de 60 s a todos los agentes; `hook.py` lo registra para Claude Code, Codex y CODA | Corregido en la leyenda y en la clave |
| 4 | El rótulo «60 s» del reloj quedaba de unos 4 px en el README | Corregido: tamaño 4,2, verificado con acercamiento |
| 5 | `BUSY` tenía entradas muertas y duplicaba `JACK` | Corregido: se quitó el conjunto |
| 6 | Una opción mal escrita (`--chek`) se ignoraba y salía 0 | Corregido: sale 2; caso `test_opcion_desconocida_sale_2_sin_armar` |
| 7 | Dos SVG casi idénticos de 178 KB por figura | Pendiente: un solo SVG con `prefers-color-scheme` exige reescribir el CSS del kit |
| 8 | El ancho de captura no seguía el de la figura | Corregido: viewport de 1200 px, holgado para figuras más anchas |
| 9 | El README no mencionaba la skill ni sus figuras | Corregido en «Estructura»; insertar la figura en el texto queda a decisión de Ariel |

Verificación: `pytest tests/test_infografias.py` 7 de 7; `build.mjs --check` con consola limpia y
0 líneas sueltas en los dos temas; suite `pruebas-agenticas/infografias.json` con los dos casos OK.

## Segunda ronda: figura de plugins y renombre

Revisión de `figuras/plugins.mjs`, la sección «Plugins locales» del README y el renombre a
central de comunicaciones. Diez hallazgos, todos corregidos:

- Los SVG nuevos sin versionar y los viejos borrados: se commitean juntos.
- La ruta `/ext/<nombre>` existe sólo si el módulo define `get` o `post`: lo dicen el README y la leyenda.
- Un archivo con nombre fuera de `[a-z][a-z0-9_]{0,31}` se ignora sin aviso: documentado.
- Una vista `.tsx` con error rompe el build o el tablero (sin ErrorBoundary en `App.tsx`): documentado; «no frena» queda sólo para el módulo del server.
- Módulo y vista son independientes y opcionales: lo dicen la figura y el README.
- Cuatro carpetas `extensiones/` fuera de Git, no dos: corregido.
- `RUNNERS_EXTERNOS` e `iniciar()` faltaban en el README: agregados.
- La prueba de «no toca lo versionado» miraba la carpeta equivocada: ahora compara fechas de los SVG versionados.
- `--check` cubría sólo una figura: ahora recorre todas.
- «Coordinadora» como nombre del tablero chocaba con el rol de sesión: la figura dice «sesión coordinadora».

## Tercera ronda: delegar trabajo y memoria por proyecto

Revisión de `figuras/delegar.mjs`, `figuras/memoria.mjs`, los acentos de color de `kit.mjs` y su
lugar en el README. Diez hallazgos:

- Una cápsula ámbar (encargo) en la bandeja de vuelta y la pista «cada cápsula es un encargo» contradecían la leyenda: queda sólo la verde y la pista dice «Ámbar sale, verde vuelve».
- Lo vigente lo decide la coordinadora o una persona (README), no sólo una persona: corregido.
- Lo capturado es pedido, respuesta final, envío entre sesiones y disparo de regla: corregido en el `label`.
- 64 KB es un tope, no un tamaño fijo: corregido el comentario.
- La comprobación de anatomy miraba sólo `iso-kit.mjs`: ahora exige también `tube.mjs` y `lathe.mjs`.
- El `SKILL.md` no mencionaba `acento`, `fillet` ni `floorSvg`: agregados.
- La base repetida en cada figura pasó a `floorSvg` en `kit.mjs`.
- Orden de pintado de tubos y de la bandeja: revisado en las capturas de los dos temas, sin superposiciones erróneas; no se cambia.

## Cuarta ronda: scheduler de mejoras

Revisión de `figuras/scheduler.mjs` contra `lienzo/optimization_*.py`. Siete hallazgos, todos corregidos:

- El 100 es el tope de trabajos en cola; cada trabajo toma los 30 incidentes más recientes de un proyecto (`optimization_memory.py`): la tolva dice «30 / proyecto».
- Un cambio en los incidentes recientes encola otro análisis de los 30, no sólo de los nuevos: lo dice la leyenda.
- Los dos medidores son CPU ≤ 35 % (`MAX_CPU`) y memoria libre ≥ 1,5 GB (`RESERVA_GB`), y todo tiene que cumplirse en dos muestras seguidas (`good_samples`).
- La luz de «nadie ocupado ni permiso vigente» estaba apagada mientras la pista decía «todo en verde»: ahora es verde.
- Faltaba la llave del usuario (aprendizaje no pausado): agregada al panel.
- La figura iba al principio de la sección, junto a Caveman y RTK: pasa al párrafo del scheduler.
- El texto alternativo omitía el permiso vigente: corregido.

## Quinta ronda: «Mejoras de agentes» a pantalla completa

El panel pasó de un diálogo de 420 px (unos 2900 px de alto) a una vista de pantalla completa:
integraciones en tarjetas a la izquierda y el aprendizaje en segundo plano a la derecha. Diez
hallazgos, todos corregidos:

- Un clic dentro de la vista cerraba el panel de la sesión de atrás (`App.tsx` buscaba `.gate`): suma `.mejoras-vista`.
- Las cabeceras eran `<header>` y heredaban el encabezado global pegajoso: pasan a `<div>`.
- Cerrar desmontaba el `<dialog>` sin `close()`: ahora se cierra antes de desmontarlo.
- `width: 100vw` pasaba por debajo de la barra de scroll: la vista se dimensiona con `inset: 0`.
- El interruptor era un diseño propio sin `prefers-reduced-motion`: reusa el `.switch` del encabezado.
- La casilla con forma de interruptor lleva `role="switch"` y `aria-describedby` hacia su estado.
- El chip de estado estaba dentro del `<h3>`; la lista de trabajos vacía se dibujaba; cada trabajo repetía tipo e hipótesis: corregidos.

Verificación: `tsc`, ESLint, build y `tests-ui/mejoras.spec.ts` (6 de 6, la del interruptor
ahora toca la etiqueta); casos `frontend-lint`, `frontend-build` y `frontend-playwright` de la suite
principal; capturas a 1440 y 390 px.

## Sexta ronda: Consultar Jev

Revisión de `figuras/jev.mjs` contra `lienzo/jev.py`, `optimization_cost.py`, `optimization_budget.py`
y `optimization_scheduler.py`. Nueve hallazgos; tres también corrigen el párrafo del README:

- Lo que se reserva es el máximo de la cotización (`maximum_usd`, tope `MAX_COST` USD 0,002688), no USD 0,001: el visor dice «máx. cotizado» y el README lo explica.
- La consulta autorizada a mano no es la única: el piloto del scheduler consulta solo, dentro de su ventana y su tope de intentos (`pilot_decide`): la figura dice «consulta manual» y el README lo aclara.
- Bloquean un cargo sin cota, una infracción, un pedido en curso o pasarse del límite; un cargo desconocido pero acotado (`bounded_unknown`) queda reservado y no bloquea: corregido en figura y README.
- La clave de OpenRouter viaja como `Authorization`: «credenciales de la sesión» en la pestaña roja, y la aclaración en la leyenda y el README.
- Faltaba el proveedor único con ZDR y sin recolección: la placa dice «ZDR · sin reintentos».
- La muestra cruzaba un barrote: el hueco va de -13 a 7 y la pestaña verde queda del lado que se ve.
- Comentario de una boca de entrada que no se dibuja, y texto alternativo con la lista recortada: corregidos.

# Code review 2026-10-16: rondas largas

Revisión con el skill `code-review` (nivel alto) del cambio de rondas largas: filtro de avisos en
`lienzo/rules.py`, sucesión persistente en `lienzo/sessions.py` y `lienzo/server.py`, `lienzo/rondas.py`,
`skills/lienzo/coordinar.py` y la tira del tablero. Diez hallazgos, todos válidos y corregidos, cada uno
con su regresión en `tests/test_rondas_revision.py`.

| # | Hallazgo | Estado |
|---|---|---|
| 1 | Los avisos de rondas (completo, vencido, turno que pasa o vence) se mandaban dentro del bucle de reglas, hasta 60 s cada uno | Corregido: `_avisar` los manda en un hilo |
| 2 | `solo_si` se buscaba en la respuesta recortada a 6000 caracteres: un `ESTADO:` al final de un informe largo se perdía | Corregido: se busca en la respuesta entera (`FILTRO_CAP`); `{respuesta}` sigue recortada |
| 3 | Al restaurar, las reglas apagadas (un solo disparo ya salido, apagada a mano) volvían prendidas | Corregido: se guarda y se repone `parked_was_enabled` |
| 4 | `coordinar.pedir_turno` mandaba siempre `ttl_min=30` y una política menor lo rechazaba | Corregido: sin `ttl_min` decide el server |
| 5 | El dedupe descartaba el mismo texto de otra tarea («Listo.») | Corregido: la huella es pedido + respuesta |
| 6 | Un relanzado fallido dejaba la marca `restaurada` 24 h | Corregido: se saca al fallar |
| 7 | `enviar_seguro` gastaba un intento al saltar a la sucesora; con `reintentos=0` no llegaba a mandar | Corregido: el salto no gasta intento (hasta 3) |
| 8 | Una dueña de turno restaurada con otro id no podía soltarlo ni renovarlo | Corregido: se compara por id vigente y la revisión reescribe el id |
| 9 | El tope por repo, lanzando en otra PC, comparaba una clave local que no coincide | Corregido: cuenta también por carpeta |
| 10 | Un id viejo y su sucesora en el mismo aviso recibían el texto dos veces | Corregido: 400 |

Además: el comentario de `SUCESION_MAX_S` decía que la sucesión no sobrevive al reinicio; actualizado.

Verificación: `pytest tests` 1730 passed, 3 skipped; `pruebas-agenticas/rondas_e2e.py` 17 de 17 contra
un server propio (7393, `LIENZO_HOME` temporal); Playwright `humo` y `salud` 3 de 3 contra un server
nuevo. Contra el 7321 sin reiniciar fallan por 404 de `/avisos` y `/memoria`: es entorno, se va al reiniciar.

# Code review 2026-10-16: el sueño mide cómo se trabaja

Revisión con `code-review` (nivel alto) de `lienzo/optimizacion_trabajo.py`, su enganche al scheduler,
`GET /trabajo/<proyecto>` y el envío `sin_aviso`. Diez hallazgos, todos válidos y corregidos, con
regresión en `tests/test_optimizacion_trabajo.py`.

| # | Hallazgo | Estado |
|---|---|---|
| 1 | `sin_aviso` se consumía en el próximo Stop cualquiera: un acuse mandado en medio de la entrega la callaba | Corregido: calla sólo el turno cuyo pedido es el texto del acuse |
| 2 | Tres salidas tempranas (compactando, error, pregunta) dejaban el flag vivo para un turno real | Corregido por el mismo cambio: un turno con otro pedido nunca se calla |
| 3 | El scheduler contaba como nuevos los hallazgos que ya existían | Corregido: `registrar` devuelve sólo los creados |
| 4 | «Perfecto, ahora implementá…» contaba como acuse, y la sugerencia habría callado entregas reales | Corregido: un acuse no trae tarea (regex `TAREA`) y pesa menos de 300 B |
| 5 | Difusiones agrupadas por hash en 72 h: perdía las reales y contaba dos «ok» | Corregido: tandas a menos de 2 min y textos de 40 B o más |
| 6 | `sin_aviso=True` en coordinar forzaba `from` y la flecha aunque `enlazar=False`; sin `YO` se ignoraba callado | Corregido: manda el id en `sin_aviso`; sin `YO`, ValueError |
| 7 | `/trabajo` no decodificaba el id, daba 200 vacío para un proyecto inexistente y 500 ante fechas sin zona | Corregido: `unquote`, 404, fechas sin zona como UTC y 503 con motivo |
| 8 | La conexión no tenía el tope de tiempo ni las claves foráneas del resto del análisis | Corregido: lectura con tope de 3 s; escritura por `optimization_memory._connect` |
| 9 | Traía el texto entero de cada captura | Corregido: principio y final de los textos de más de 1000 caracteres |
| 10 | La hora se marcaba antes de analizar: una cancelación lo postergaba una hora | Corregido: se marca después; cancelado, se retoma en el próximo rato quieto |

Verificación: `pytest tests` 1745 passed, 3 skipped; `rondas_e2e.py` OK; ruff limpio.

## Catálogo de comunidad, plugins locales y creencias

Revisión estática del delta propio, aplicando code-audit en esta sesión. No es una revisión
independiente de Claude. No incluye los cambios ajenos de backend.py, tmux.py y sus pruebas.

Alcance: tools/__init__.py, tools/anatomy.py, tools/better_claude.py, plugins.resumen,
agent_improvements.status, AgentImprovements.tsx, creencias.py, patrones_desarrollo.py,
sus rutas/integración y pruebas focales. Sin dependencias nuevas ni cambios de hooks/permisos.

| Hallazgo | Corrección |
|---|---|
| Marcar disponible por una entrada del registro ocultaría archivos faltantes o manifiesto equivocado | Comprueba scope user, ruta absoluta, archivo y nombre del manifiesto, y habilitación explícita; corrupción visible |
| Tests del catálogo podían leer la configuración real de Claude | CLAUDE_CONFIG_DIR temporal en conftest; pruebas de sólo lectura comparan bytes antes/después |
| Una regla derivada podía quedar vigente tras refutar/vencer su creencia | Se eliminó la regla materializada; checklist como vista sobre creencias y apoyo activo del mismo proyecto |
| Consulta de apoyo por cada item del checklist | JOIN tipado de evidencia en la consulta, sin N+1 |
| Confundir plugin local cargado con sistema conectado o con colección de tools | Inventario separado; no invoca funciones de extensiones ni exige tools; estado explícito cargado, salud no acreditada |
| Aplicar instalación Windows a una distro o a otro agente | No disponibilidad WSL sin verificar; Better Claude declara compatibilidad sólo Claude y no inyecta instrucciones |
| Commit podía interpretarse como una acción automática de Lienzo | Ficha informa commit/push no interactivo; catálogo sólo muestra instrucciones, no ejecuta /commit |

No se observaron bloqueantes pendientes en los cambios focales revisados. La validación local
no acredita compatibilidad real de los mods de Better Claude, su instalación, el render de Anatomy
ni una conexión real de Stepwise. El estado humano del veredicto sigue el contrato existente de
autores declarados de la API; no se incorpora un sistema nuevo de autenticación de roles.

Verificación reproducible: runners catalogo-comunidad.json y creencias.json; sus resultados y
veredictos están en pruebas-agenticas/resultados, con logs completos y correcciones conservadas.
Build frontend, ESLint, Ruff y Black revisados. Se conserva el aviso Vite de bundle >500 kB.
Sin aprobar baselines/mutaciones. El investigador CLI y el manifiesto uniforme siguen pendientes.

# Code review 2026-10-16: investigador CLI en background (frente A)

**Fecha**: 2026-10-16 · **Alcance**: revisión de PR, sólo archivos del frente A · **Revisor**: Claude Opus 5.5 (skill code-audit)
**Archivos**: `lienzo/optimization_research.py`, `optimization_research_policy.py`, `optimization_research_quota.py`,
`optimization_research_runner.py`; cambios en `optimization_scheduler.py`, `optimization_queue.py`, `optimization_cost.py`.

### Resumen

| Severidad | Encontradas | Corregidas | Abiertas |
|---|---|---|---|
| CRÍTICA | 0 | 0 | 0 |
| ALTA | 2 | 2 | 0 |
| MEDIA | 5 | 4 | 1 abierta |
| BAJA | 2 | 1 | 1 |

### ALTA (corregidas)

1. **Autocancelación por hooks de Lienzo.** `codex exec` cargaría `~/.codex/hooks.json`, que llama a `lienzo/hook.py`.
   Si los hooks se activan, el investigador aparecería como sesión ocupada y `_research_stop` lo cortaría al instante.
   Hoy `features.hooks = false`, pero eso depende de una configuración ajena. Corrección: `--disable hooks` y
   `-c notify=[]` en el argv. Verificado sin inferencia: `codex -c notify=[] --disable hooks features list` → 0.
2. **Lector de cuota imposible de reemplazar.** `CodexAdapter(quota_reader=quota.read_codex)` ataba la función
   como argumento por defecto: una prueba que parcheara el módulo igual lanzaría el `app-server` real. Corrección:
   resolverla al llamar. Las pruebas fallan explícitamente si se intenta leer la cuota real.

### MEDIA

3. **Inyección de prompt desde la memoria** (mitigada). Los textos de las sesiones entran al prompt. Mitigaciones:
   el prompt declara el caso como dato, sandbox read-only sin red, esquema estricto y validación de fuentes antes
   de escribir. Residual: el sandbox no impide leer archivos fuera del repo.
4. **Secretos dentro de valores** (corregida en la ronda 2, 2026-10-17). `redact()` cubre una lista cerrada de
   formatos en el paquete, en la respuesta antes de guardarla y en los errores, con conteo por tipo. No es una
   detección universal. Hay pruebas por formato y de no falsos positivos. Bug encontrado y corregido: `DB_PASSWORD=`.
5. **`pid` registrado tras un error al guardar** (corregida). Se limpia `pid` en cuanto termina el proceso propio.
6. **`_research_step` de ~70 líneas** (abierta). Supera el máximo de 50. Se mantuvo lineal (evaluar → iniciar →
   resultado) para que el orden de las transiciones quede legible; se puede extraer `_research_outcome`.

9. **Salida sin tope durante la ejecución** (señalada por la coordinadora; corregida en la ronda 2). Los archivos
   temporales podían crecer 900 s. Ahora la lectura es por tuberías con un tope total en vivo y se mata el árbol
   propio al pasarlo. `result.json` también tiene tope (200 kB).

### BAJA

7. `fuentes` no-lista en `select` iteraba caracteres (corregida).
8. `check()` dentro de `validate` usa `return errors.append(...)` como corte (estilo; abierta).

### Verificación

- Silencios: ningún `except` vacío. `read_codex` y `runner.run` devuelven fallos explícitos y matan sólo su propio
  árbol. Tras un reinicio, el PID registrado nunca se mata (cubierto por pruebas).
- Sin `getenv` con valores por defecto, sin código muerto (ruff limpio), sin dependencias nuevas.
- Mutación sobre una copia: ronda 1, 5 de 5; ronda 2, **8 de 8** muertos por aserción, control vivo (`mutacion-copia.json`).

# Code review 2026-10-16: contrato uniforme de plugins (frente B)

Alcance: lienzo/plugin_manifest.py, plugins.py, tools/better_claude.py, PluginCard de
AgentImprovements.tsx y sus pruebas. Skill code-review (10 hallazgos) y code-audit en la sesión B.

| Hallazgo | Estado |
|---|---|
| Configuración en la raíz de config.json chocaba con claves de Lienzo (`wait`, `ejemplos`) | Corregido: `config.json["plugins"][<id>]` |
| Un plugin deshabilitado con manifiesto roto se informaba como error | Corregido: deshabilitado tiene precedencia |
| Rutas de un plugin cuyo `iniciar()` falló seguían atendiendo | Corregido: 503 para plugins con manifiesto; legacy igual que antes |
| `get` leía fichas sin lock | Corregido |
| Un registro viejo de Better Claude tapaba uno válido | Corregido |
| Estado desconocido rompía el render; `conectado: false` se veía «sano»; salud vieja tras «Actualizar» | Corregidos en la UI |
| `validar` (30) y `cargar` (18) sobre el umbral de complejidad; `except` silencioso | Corregidos (≤ 10; ahora va al log) |
| `detener()` no se invocaba al cerrar | Corregido en la integración: `server._salir` lo llama con tope de 3 s antes de `os._exit` |
| Un módulo incoherente ya ejecutó su import antes de rechazarlo | Abierto, documentado en docs/PLUGINS.md |

# Code review 2026-10-17: entrega de informes y tablero (coordinación)

Alcance: reconciliación de on_stop en rules.py, reapertura por `<task-notification>` en
transcripts.py, orden y grilla del tablero (Board.tsx, card.css, styles.css), parada de plugins en
server.py, aislamiento de plugins en conftest.py y la vista del investigador. Skill code-review
(10 hallazgos sobre la primera versión).

| Hallazgo | Estado |
|---|---|
| Asentamiento de coda (15 s) y reconciliación (10 s) podían evaluar el mismo turno dos veces | Corregido: la sesión queda reservada (contador) desde el inicio de fire_on_stop |
| Reglas sin marca reevaluaban el último turno al desplegar | Corregido: toman como visto el turno que encuentran |
| La marca `turno_visto` no se guardaba en salidas tempranas | Corregido: se guarda al cambiar |
| `last_reply` reescrito por la transcripción disparaba reevaluaciones | Corregido: sólo se reconcilian sesiones Claude con hooks |
| Turno reabierto por una notificación y después interrumpido quedaba abierto | Corregido: la interrupción lo cierra |
| La reconciliación compartía `try` con los envíos lentos | Corregido: corre primero y aparte |
| Comentario del orden y CSS muerto de la multicolumna | Corregidos |
| La grilla deja huecos bajo tarjetas cortas | Abierto: precio de que no salten de columna; decisión de Ariel |
