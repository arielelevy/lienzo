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
