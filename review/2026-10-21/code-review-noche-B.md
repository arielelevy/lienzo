# Code review — noche B (reimportación legacy), 2026-10-21

Alcance: `lienzo/conocimiento.py` (importación de bases viejas), `lienzo/replica.py` (sólo `clave_libre`) y `tests/test_import_legacy.py`.
Skill `code-review` en dos pasadas (medium) sobre el delta sin commitear. Las salidas crudas están en
`.temp/resultados/noche-B/code-review-pasada1.txt` y `code-review-pasada2.txt`.

## Hallazgos del encargo B2 (los 9 de la revisión anterior)

| # | Hallazgo | Arreglo | Prueba (rojo antes) |
|---|---|---|---|
| 1 | Una fila que viola un CHECK o NOT NULL abortaba toda la reimportación | `_escribir_fila`: cada INSERT o UPDATE va en su SAVEPOINT. Una `IntegrityError` deshace esa fila, la loguea y la cuenta como `ignoradas` | `test_una_fila_nueva_que_viola_un_check…`, `test_una_actualizacion_que_viola_un_check…` |
| 2 | `clave_ingesta` repetida: la primera importación perdía la fila y la siguiente la traía | `_completar_primera` intenta lo que no entró en bloque con `clave_libre`, igual que al reimportar | `test_una_clave_repetida_da_lo_mismo…` |
| 3 | Lo que ya difería en la primera importación aparecía como choque nuevo | La primera importación registra como revisión conocida lo de allá para toda fila que está | `test_lo_que_ya_diferia_en_la_primera_importacion…` |
| 4 | Cada arranque recorría todas las filas | Sólo se reimportan las filas que nombra el historial posterior a `ultimo_seq`. Si no hay nada nuevo, no se escribe nada | `test_si_la_base_vieja_no_tiene_cambios_nuevos…`, `test_solo_se_miran_las_filas…` |
| 5 | Colisión de id con otro proyecto se informaba como «cambiaron el mismo» | Tiene motivo propio («… es del proyecto q aca»), también para vínculos (proyecto del nodo `de`) | `test_un_id_que_es_de_otro_proyecto…`, `test_un_vinculo_de_otro_proyecto_no_se_pisa` |
| 6 | La lógica de duplicados estaba copiada en `replica.py` | `conocimiento.clave_libre`, usada por la réplica y por la importación | `test_la_clave_repetida_se_resuelve_con_la_misma_funcion…` |
| 7 | CAS con `IS ?` por columna dentro de la misma transacción | Ahora es un UPDATE por clave: la lectura y la escritura van en la misma transacción `BEGIN IMMEDIATE` | Lo cubren los casos de actualización y choque |
| 8 | La prosa tenía cuatro ramas | Dos: con índice allá se copia, sin índice se leen los cuerpos. Sólo se indexan los nodos sin índice acá (`_sin_prosa`, un `NOT IN`) | `test_con_indice_de_prosa_alla…` |
| 9 | Docstring y log desactualizados | Docstrings de `_importar_viejas` y `_importar_una`. El log cuenta nuevas, actualizadas, choques e ignoradas, y calla si no hubo nada | `test_el_log_cuenta_las_nuevas` |

## Pasada 1 (8 hallazgos, todos corregidos)

- **Capturas sin `cambio`.** El corte temprano dejaba afuera las capturas nuevas. Ahora capturas y proyectos siempre entran en bloque. Prueba: `test_una_captura_nueva_alla_entra…`.
- **Base sin tabla `cambio`.** No se reimportaba nada. Ahora se recorren todas las filas. Prueba: `test_sin_tabla_de_historial…`.
- **Historial de un choque publicado como propio.** Ahora ese historial se guarda con `pc = legado:<ruta>` y `seq_origen` = su seq allá. Queda en el historial y no viaja. Prueba: `test_el_historial_de_un_choque_no_se_publica…`.
- **Falsos choques sin procedencia.** Se resolvió con el punto 4: sólo se miran las filas que nombra el historial. Prueba: `test_lo_editado_aca_sin_procedencia…`.
- **Recorrido completo.** Mismo arreglo que el punto 4.
- **Vínculo de otro proyecto.** Se agregó la guarda. Prueba: `test_un_vinculo_de_otro_proyecto…`.
- **«cambiaron el mismo» falso.** El motivo ahora es neutro: «aca no esta como se importo». Prueba: `test_una_diferencia_de_la_primera_importacion…`.
- **Doble consulta de prosa.** Ahora es una sola consulta con `NOT IN`.

## Pasada 2 (9 hallazgos)

**Corregidos:**
- **Historial de otra PC sobre una fila no aplicada.** Quedaba como ya recibido y la edición de pcB se perdía. Ahora la marca `legado:` va también para pc ajena. Prueba: `test_el_historial_de_otra_pc…`.
- **Primera importación sin guarda de proyecto.** Se agregó. Prueba: `test_en_la_primera_importacion_un_id_de_otro_proyecto…`.
- **Prosa vieja tras actualizar un encargo o informe.** Se borra y se rehace. Prueba: `test_un_informe_actualizado_alla_reindexa…`.
- **Un choque repetido se contaba y escribía en cada arranque** (base sin `cambio`). Ahora es `repetidos`: no cuenta, no loguea y no escribe. Prueba: `test_sin_historial_alla_un_choque_ya_registrado…`.
- **Una captura nueva disparaba la relectura de la prosa.** Ahora sólo la disparan nodos nuevos o cambiados. Prueba: `test_una_captura_nueva_no_relee_la_prosa`.
- **`_sin_prosa` cargaba todo el FTS en Python.** Ahora es un `NOT IN` en SQL.
- **DDL de `importada_fila` por cada base.** Ahora corre una vez por pasada, en `_importar_viejas`.

**No corregidos, con motivo:**
- **`replica._ultimo_cambio` cuenta el historial `legado:` para decidir el más nuevo.** Está fuera de mis archivos: el encargo habilita `replica.py` sólo para el punto 6. El problema ya existía: antes, el historial importado entraba con `pc` local y contaba igual. Propuesta para la coordinadora: excluir `pc LIKE 'legado:%'` en `_ultimo_cambio`.
- **Primera importación en bloque más repaso fila por fila.** Lo dejo a propósito. `test_captura.py::test_importar_vieja_no_mezcla_filas_con_historial_de_otra_revision` engancha la escritura concurrente en el `executemany` «INSERT OR IGNORE INTO nodo», y `test_una_base_vieja_que_falla…` mockea `_rellenar_prosa(con, pid)`. Los dos archivos son ajenos y no los toco.

## Límites conocidos

- Sin procedencia (filas traídas por el importador anterior a este cambio), si una fila cambió allá y acá difiere, queda un choque conservador. Si allá no cambió, ni se mira.
- En una base vieja sin tabla `cambio`, una fila que viola una restricción se reintenta y se loguea en cada arranque. Ese esquema no existe en las bases medidas; el esquema 1 ya trae `cambio`.
- Una fila borrada allá no se borra acá.
