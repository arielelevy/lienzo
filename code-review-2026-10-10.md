# Code review: memoria por proyecto, ronda 3

**Fecha**: 2026-10-10
**Alcance**: revisión de los cambios `565448c..39dcc1e` (memoria por carpeta y captura, texto roto,
prosa, huecos de v5, réplica entre PCs).
**Revisores**: un revisor adversarial delegado (subagente) y una sesión de Claude lanzada desde el
lienzo («encargo B», solo lectura), cada uno con pruebas que reproducen lo que reporta. Las correcciones
y sus pruebas, en esta sesión.

## Resumen

| Severidad | Hallazgos | Corregidos |
|---|---|---|
| HIGH | 3 | 3 |
| MEDIUM | 7 | 7 |
| LOW | 6 | 6 |

Nada quedó sin corregir. Cada corrección tiene una prueba de regresión en `tests/test_captura.py` o
`tests/test_replica.py` (sección «regresiones del code review»).

## HIGH

1. **Migración 1→2→3 no atómica y sin lock** (`conocimiento._Conexion`). Con dos o más conexiones abriendo
   la base a la vez, o con un fallo entre la prosa y `user_version`, `prosa_fts` quedaba duplicado o
   salía «duplicate column». Sobre una copia de la base viva: 40 filas de prosa para 10 cuerpos con 4 hilos.
   **Arreglo:** `_migrar` con un lock por proceso, `BEGIN IMMEDIATE`, `user_version` releído adentro, cada
   sentencia con `execute` (sin `executescript`, que hacía COMMIT) y la versión en la misma transacción.
   Pruebas: cuatro aperturas a la vez migran una vez; una migración que falla a mitad no deja nada.
2. **Informe duplicado si la entrega explícita llegaba antes que la captura** (`informe_capturado`).
   **Arreglo:** si ya hay un informe con ese hash en el proyecto, se devuelve ese.
3. **Relojes distintos dejaban las PCs distintas para siempre** (`replica._aplicar_nodo`): el «último que
   escribe» se decidía por la hora de cada PC. **Arreglo:** reloj híbrido en `_cambio`
   (`_fecha_causal`): un cambio local nunca tiene fecha anterior al último que esta PC conoce de ese nodo.

## MEDIUM

4. **Carrera SELECT/INSERT con `clave_ingesta`** (`crear_nodo`): la captura y `encargo_enviado` creando la
   misma sesión daban UNIQUE y un 500. **Arreglo:** `INSERT ... ON CONFLICT (clave_ingesta) DO NOTHING` y releer.
5. **«Cambios desde el cierre» de una ronda cerrada en otra PC** comparaba seqs de dos PCs.
   **Arreglo:** el corte es el seq local del cambio que anotó `cierre_seq`, y la última ronda se elige por fecha.
6. **`tapar` dejaba pasar** `DB_PASSWORD=`, `AZURE_CLIENT_SECRET=`, `GITHUB_TOKEN=`, `"password": "..."`,
   `token: ...` y `sig=` de SAS. **Arreglo:** prefijo permitido en la clave, comillas antes de `:`, `token` y
   `sig`; prueba de que no tapa `max_tokens: 4096` ni texto común.
7. **Escritura fuera del proyecto en `_traer_cuerpos`** con una ruta `../..` de un par.
   **Arreglo:** `ruta_segura` en los dos lados, limitada a `rondas/`, `capturas/` y `evidencia/`.
8. **Un par viejo quedaba salteado hasta reiniciar.** **Arreglo:** se reintenta a los 15 minutos.
9. **Orden por defecto de `preguntar`:** los candidatos sin puesto (por tema o archivo) pasaban adelante.
   **Arreglo:** sin puesto van al final, como antes.
10. **Choques inventados con tres PCs** según el orden de llegada. **Arreglo:** choque solo si lo que se
    pisa nació en esta PC.

## LOW

11. Una respuesta con un secreto tapado se tomaba como informe y chocaba (409) con la entrega explícita
    del original. Ahora queda solo como captura.
12. Una excepción imprevista en un proyecto o par cortaba toda la vuelta de réplica. Ahora se aísla por
    proyecto y por par, con el traceback en el log.
13. La réplica llenaba el log (una línea por pedido, cuerpos faltantes pedidos cada 120 s). Al log solo
    van los errores, y un cuerpo que el par no tiene se reintenta a los 30 minutos.
14. `op: cuerpo` entregaba cualquier archivo de la carpeta, incluida la base. Limitado a las tres subcarpetas.
15. `_aplicar_captura` con `INSERT OR IGNORE` descartaba en silencio una captura mal formada. Ahora el lote
    falla, el cursor no avanza y el error queda a la vista.
16. Un id de 64 caracteres con sufijo `-2` pasaba el largo. Se recorta a 56 antes del sufijo.

## Revisado y sin defectos

Inyección SQL (los f-strings arman solo nombres fijos), deadlocks (la captura encola con el lock de
tarjetas y nunca hace I/O con su propio lock), idempotencia por `(pc, seq_origen)`, savepoints dentro de
`BEGIN IMMEDIATE`, cursores transaccionales, `leer_cuerpo` confinado a la carpeta del proyecto.

## Verificación

- Suite completa: 1287 pasan; 1 falla previa y ajena (`test_cuenta_github`, WinError 6 de subprocess, falla
  igual sin estos cambios).
- Copia de la base viva migrada de esquema 1 a 3: 40 nodos, 58 vínculos y 130 cambios iguales, 10 cuerpos
  indexados, cero cambios sin origen.

## Segunda revisión: base única del lienzo (`569d016..7732c84`)

Un revisor delegado, con pruebas propias contra bases viejas armadas con el código anterior. Corregido
todo, con regresión en `tests/test_captura.py` y `tests/test_replica.py`:

| Sev. | Hallazgo | Arreglo |
|---|---|---|
| HIGH | La misma sesión no podía estar en dos proyectos: el id de su nodo era global y chocaba la PRIMARY KEY | `id_de_sesion(pid, sid)` incluye el proyecto (su remote, igual en todas las PCs, o su id) |
| HIGH | La importación descartaba en silencio lo repetido | se cuenta y se loguea; cada base en su SAVEPOINT |
| HIGH | Renumerar el seq de origen al importar podía confundir a un par de esquema 3 | el esquema 3 no llegó a correr en vivo; la réplica rechaza un par con otro esquema (`SinSoporte`) |
| MEDIUM | Una base vieja ilegible dejaba sin memoria a todo el lienzo | se saltea con su error en el log y se reintenta en el arranque siguiente |
| MEDIUM | Una base vieja que aparecía después de migrar no se importaba, y un proyecto creado por un server viejo no tenía su fila | revisión una vez por proceso; la tabla `importada` hace la reimportación idempotente; se asegura la fila de cada proyecto del índice |
| MEDIUM | La réplica podía pisar un nodo con el mismo id en otro proyecto | queda pendiente con el error a la vista |
| LOW | El briefing sin filtros compartía un límite: muchos abiertos tapaban lo vigente | un límite por grupo |
| LOW | `memoria.py` mezclaba códigos de salida y fallaba con campos ausentes | 1 sin memoria, 2 sin lienzo, 3 pedido rechazado; sin tracebacks |
| LOW | Tres recorridos leían los vínculos de todos los proyectos | filtran por proyecto con un JOIN |

## Tandas 1 y 2 de PENDIENTES

Revisión propia del diff antes del commit. Pruebas nuevas en `tests/test_pendientes_tanda1.py` y
`tests/test_pendientes_tanda2.py` (12); batería completa 1313 pasan; lint, tipos y build del front.
Verificado en vivo tras reiniciar el server: `/health` por el túnel sólo dice `ok` y `ts`,
`/auth/sessions` lista y revoca, `request_id` con punto da 400 y `/links` trae las del espejo.

| Sev. | Observación | Decisión |
|---|---|---|
| MEDIUM | `prettier --write` sobre `Setup.tsx` reformateaba líneas ajenas | se descartó; el diff toca sólo lo nuevo |
| MEDIUM | `/health` con `_is_local()`: hay que confirmar que el túnel no cuente como local | `_is_local` devuelve False con `_via_tunnel`; probado con `CF-Connecting-IP` |
| LOW | La cuota de adjuntos no cuenta `mensaje.md` ni `.send.txt` que arma el envío | a propósito: los arma el server, no el cliente; la limpieza por antigüedad los libera |
| LOW | `ruta_wsl` no llama a `wslpath` | WSL monta las unidades en `/mnt/<letra>` por defecto; un `automount.root` distinto queda fuera |
| LOW | Lista fija de capacidades en `tests/test_health.py` | se sumó `memoria.replica` |

Queda abierto: destino del hook por `TMUX_PANE` en Unix (sin una PC Linux donde probarlo).

## Tanda 3 de PENDIENTES

Revisión propia antes del commit; pruebas en `tests/test_pendientes_tanda3.py` y `tests/test_coordinar.py`.

| Sev. | Observación | Decisión |
|---|---|---|
| MEDIUM | `proc_info` cambia de comportamiento fuera de Windows | sólo lo usan `hook.py` y `kiro.py` (Kiro está limitado a Windows) |
| MEDIUM | El pane viene de un archivo de evento, que podría estar alterado | se toma sólo si es `%` y dígitos, y sólo en tarjetas de tmux |
| LOW | En Linux `/proc/<pid>/exe` del Claude nativo es un binario con nombre de versión | se usa `comm`, que sigue siendo `claude` |
| LOW | El cupo de codas no distingue modelos | todas comparten hoy el servidor del DGX; si se suman otros, separar por `model` |

## Cierre de `--coda-home` en PENDIENTES

**Alcance:** solo `PENDIENTES.md` (una casilla cerrada con evidencia de una prueba manual con coda real). Sin cambios de
código, así que no hay hallazgos ni hace falta compuerta nueva: la última (PASS sobre 4e22760) sigue valiendo para el código.
La evidencia no cita la clave ni su contenido, solo dónde la guarda coda (`<carpeta>/.secrets`). La carpeta de prueba se borró.

## Compactación abortada de coda (`lienzo/sessions.py`)

**Alcance:** `apply_hook` (UserPromptSubmit), `coda_dialogo_en_pantalla`, `coda_compactacion_abortada` y
`_ultimo_mensaje_coda` nuevos; test en `tests/test_coda.py`.

**Defecto encontrado en vivo (CODA 1.4.0):** `/compact` con poca conversación muestra «Too few messages for compaction»
y no manda PostCompact ni Stop (el PreCompact a veces sí). La tarjeta quedaba `corriendo` hasta el pedido siguiente, y con
la marca de compactación el Stop de ese pedido se ignoraba hasta 10 minutos (on_stop sin disparar).

**Arreglo y revisión:**
- La red de pantalla que ya mira una coda quieta en `corriendo` (cada 10 s, sin el lock) ahora también reconoce el cartel, y
  solo si es el último renglón arriba de la caja vacía: un cartel viejo no corta una compactación real. Exige que la tarjeta
  tenga la marca o que el pedido haya sido `/compact`. Vuelve a `termino` sin `set_state`, para no disparar on_stop.
- `UserPromptSubmit` limpia una marca de más de 10 s. Hallazgo propio en la primera versión: limpiarla siempre perdía la del
  mismo `/compact`, porque los dos hooks llegan en cualquier orden; corregido con `COMPACTING_CARRERA_S` y probado.
- Sin silencios ni fallbacks nuevos; la escritura del dict va con el lock. Complejidad baja.

**Pruebas:** 1320 pasan; verificado en vivo dos veces con una coda real (con y sin PreCompact), log
«coda abortó la compactación (pocos mensajes); la tarjeta vuelve a termino».
