# Code review — noche B, retoma 2: `legado:` y sincronización por marcas (2026-10-22)

Alcance: `lienzo/replica.py`, `tests/test_replica.py`, `tests/test_replica_marcas.py` (nuevo) y `tests/test_import_legacy.py`.
Skill `code-review` (medium) en dos pasadas sobre el delta. Salidas crudas en
`.temp/resultados/noche-B/code-review-sync-pasada{1,2}.txt`.

## Qué cambia

1. `_ultimo_cambio` ya no toma el historial `legado:` (una edición de la base vieja que acá no se aplicó)
   como la edición más nueva del nodo. Sólo lo toma si el nodo no tiene otro historial.
2. Op `marcas`: devuelve, por proyecto, el último `seq_origen` de los cambios propios y el último rowid de las
   capturas propias. El que pide sólo pide `cambios` o `capturas` donde la marca supera el cursor.
3. Un proyecto quieto (marcas alcanzadas, cursores de ese proyecto, carpeta presente y cuerpos revisados
   hace menos de `REINTENTO_CUERPO_S`) no abre la base del que pide. La `fecha` de sus cursores se
   renueva con un único UPDATE por vuelta.
4. Compatibilidad:
   - Un par anterior contesta 400 a `marcas` («proyecto debe ser…»). Esa vuelta se hace con `proyectos` y no se le vuelve a preguntar por 15 min.
   - Cualquier otro fallo de `marcas` hace esa vuelta con `proyectos`.
   - Un 404 «desconocida» sigue siendo SinSoporte.
   - `proyectos`, `cambios` y `capturas` no cambian, así que un par anterior que me pide a mí no nota nada.

## Medición (banco `.temp/resultados/noche-B/medir_sync.py`)

Condición:
- Dos procesos HTTP en 127.0.0.1: pcA en 7342 pide y pcB en 7352 atiende.
- Firma HMAC real: `HTTPTransport` del que pide y `verify_motivo` del que atiende.
- `replica.atender` y `replica.sincronizar` reales.
- Datos: 20 proyectos con remote en pcB, con 50 nodos y 20 capturas por proyecto.
- Una vuelta llena y después 10 ociosas.

No es el server completo: no corren el espejo, el actualizador ni los barridos. Los bytes son de cuerpo, sin headers HTTP. La CPU es `process_time` de cada proceso.

| Vuelta ociosa (por vuelta) | Antes | Después | A nueva, B anterior | A anterior, B nueva |
|---|---|---|---|---|
| Pedidos | 41 | **1** | 41 | 41 |
| Bytes respondidos (gzip) | 3432 (2668) | 2428 (410) | 3432 (2668) | 3432 (2668) |
| CPU que pide (A) | 494 ms | **19 ms** | 438 ms | 430 ms |
| CPU que atiende (B) | 202 ms | **7,8 ms** | 197 ms | 186 ms |
| Reloj, mediana | 769 ms | **27 ms** | 667 ms | 659 ms |
| Vuelta llena: aplicados / pedidos | 1420 / 41 | 1420 / 41 | 1420 / 42 | 1420 / 41 |

Las columnas «antes» y «después» salen de corridas distintas, una por estado del código (`sync-antes.json` y `sync-despues.json`). La CPU del que pide se iba en abrir la base: unas 100 conexiones por vuelta, de unos 2,4 ms cada una con su `_migrar`, según el perfil en `perfil-marcas.txt`.

## Pasada 1 (10 hallazgos)

**Corregidos (9), con prueba en rojo antes:**
- **Cuerpo borrado o nunca traíble en un proyecto quieto.** La revisión de cuerpos vence a los 30 min. Prueba: `test_un_cuerpo_que_falta_se_vuelve_a_buscar…`.
- **Cursor que apunta a otro proyecto local.** Ese proyecto no cuenta como quieto. Prueba: `test_un_cursor_que_apunta_a_otro_proyecto…`.
- **Carpeta faltante.** No cuenta como quieto, así que la vuelta completa da el error. Prueba: `test_un_proyecto_sin_carpeta…`.
- **UPDATE agrupado fuera del try.** Ahora va con su propio `except sqlite3.Error`.
- **Cualquier 400 apagaba las marcas.** Sólo las apaga el 400 de la versión anterior. Prueba: `test_marcas_que_falla_por_otra_cosa…`.
- **`marcas` creaba la base en una lectura.** Ya no la crea. Prueba: `test_marcas_no_crea_la_base…`.
- **Doble apertura por lote y la comparación escrita dos veces.** Ahora hay una sola apertura y una sola comparación (`_alcanzada`).

**No corregido (1):** un `pc` de par que empiece con `legado:`. Los `pc_id` reales no tienen esa forma.

## Pasada 2 (8 hallazgos)

**Corregidos (6), con prueba en rojo antes:**
- **`marcas` lee la base del par.** Si falla (base ocupada) o el texto del 400 cambia, esa vuelta va con `proyectos`. Pruebas: `test_marcas_que_falla_por_otra_cosa…` con 400 y con 500.
- **Un nodo de una tercera PC esperaba 30 min por su cuerpo.** Cuando entran cambios a un proyecto se invalida la revisión de cuerpos con todos los pares. Prueba: `test_cambios_de_otro_par…`.
- **`_estado_local` fuera del try.** Si falla, la vuelta sigue completa proyecto por proyecto. Prueba: `test_si_no_se_puede_leer_el_estado_local…`.
- **Nodo con sólo historial `legado:`.** Una edición más vieja de un par lo pisaba sin comparar. Prueba: `test_un_nodo_con_solo_historial_legado…`.
- **Armado duplicado del resultado.** Ahora sale de `_resultado`.

**No corregidos (2), con motivo:**
- **Índices `captura(pc, proyecto)` y `cambio(pc, proyecto, seq_origen)` para `marcas`.** Sumarlos exige migración de esquema, y la réplica exige la misma `VERSION_ESQUEMA` que el par. Hoy `marcas` recorre las capturas una vez por vuelta y por par. Las consultas por proyecto de antes recorrían lo mismo, repartido en 40 pedidos. Queda como recomendación para la próxima subida de esquema.
- **Volver al diseño sin atajo** (sólo cortar los pedidos). Lo descarto por la medición: sin el atajo, el que pide gasta 466 ms de CPU por vuelta ociosa; con el atajo, 19 ms.

## Límites conocidos

- La revisión de cuerpos vive en memoria del proceso. Al arrancar se vuelve a mirar todo.
- Un cuerpo que no coincide con su hash se reintenta a los 30 min, no en cada vuelta. Es el mismo plazo que ya tenía un pedido fallido.
- Push por `/peer/events`: no se implementó. Con 1 pedido de unos 2,4 kB cada 120 s, el beneficio que queda es la latencia, no el costo.
