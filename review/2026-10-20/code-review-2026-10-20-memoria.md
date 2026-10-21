# Code review: frente C de la memoria (2026-10-20)

**Alcance:** las correcciones 1 a 4 y 6 a 8 del diagnóstico, más la 5 (actor `server` enviado por un
cliente HTTP), autorizadas por la coordinadora.

**Archivos exclusivos:**
- `lienzo/conocimiento.py`
- `lienzo/veredictos.py`
- `lienzo/conocimiento_api.py`
- `web/src/components/Learning.tsx`
- `web/tests-ui/cinco-E-memoria.spec.ts`
- `tests/test_memoria_frente_c.py`

**Evidencia:** `.temp/coordinacion/2026-10-20/C-memoria/` (ignorado por Git). Ahí están el
diagnóstico, `roles.json` y los logs antes y después.

## Cambios

| # | Defecto | Corrección | Regresión |
|---|---|---|---|
| 1 | `cinco-E-memoria` buscaba la vista Creencias, que ya no existe. Aprendizaje no tenía «Cancelar consulta» | Botón «Cancelar consulta» en `Learning.tsx`, que aborta y descarta la respuesta tardía. El recorrido pasa por Aprendizaje con el mismo oráculo | Playwright: falló antes y pasa después (contra un Vite aislado en 5191) |
| 2 | `retirar_vinculo` y `veredictos._retirar_en` no filtraban por proyecto | `retirar_vinculo` valida los dos extremos con `_nodo(con, pid, …)` y acepta `con`. `_retirar_en` lo reutiliza: se quitó el código duplicado | 2 pruebas |
| 3 | La revisión de `informe_capturado` era la cantidad de `responde_a` + 1 | `entregar(revision_siguiente=True)` calcula `MAX(revision)+1` dentro de su `BEGIN IMMEDIATE` | huecos r1/r3, y una entrega explícita concurrente que se adelanta |
| 4 | La entrega y la transición iban en transacciones separadas; los controles corrían en autocommit | `entregar` y `encargo_enviado` toman `BEGIN IMMEDIATE` y aplican la transición con `con`. El reenvío completa un encargo `enviado` o `sin_entrega` (este último sólo coordinadora o persona) si el informe ya responde a ese encargo | fallo simulado con `database is locked`, reintento y reenvíos |
| 5 | `por` o `autor` = `server` llegaban del cliente | `conocimiento_api._sin_actor_server`: 403 en la única entrada HTTP de la memoria. `veredictos_api` y `aprendizaje_api` se despachan desde ahí. `/peer/conocimiento` (réplica) no pasa por ese camino | 4 casos, más coordinadora, frente y lecturas sin cambios |
| 6 | Una ronda se cerraba sin `cierre_seq` por `/nodos/<id>/estado` o por un ítem de veredicto | `cambiar_estado` rechaza `ronda → cerrada` sin `cierre=True`, que sólo pasa `cerrar_ronda`. La ruta de nodos deriva a la de rondas | 2 pruebas |
| 7 | `sin_entrega → entregado` no exigía ninguna entrega | `RESPALDO[("encargo","entregado")] = "responde_a"` | 1 prueba |
| 8 | `pendientes` no mostraba las reglas `cuestionada` | `ESTADOS_PENDIENTES` suma `cuestionada` | 1 prueba |

## Lote 4: sesión en dos proyectos

| Defecto | Corrección | Regresión |
|---|---|---|
| `sesion_cerrada` y `sesion_viva` cambiaban un solo nodo `sesion` (`_proyecto_de_sesion`, que trae uno solo); los de otros proyectos quedaban `viva` (anexo D, v5 L753-754) | `_proyectos_de_sesion(sid)`, nueva y de solo lectura: todos los nodos `sesion:{sid}` con carpeta. `_estado_sesion` aplica la transición en cada proyecto, cada uno con su try y su log | cierre y vuelta en dos proyectos; el incidente queda sólo en el proyecto actual; repetir el cierre no agrega cambios; un proyecto que falla queda en el log y no frena a los demás |

La regresión de cierre y vuelta falló antes (`lote4-regresion-antes.log`). La segunda prueba, de
idempotencia y fallo aislado, se escribió con el diseño ya aplicado.

En la revisión del lote, `test_conocimiento::test_sesion_que_revive_vuelve_a_viva_y_la_cache_negativa_se_invalida`
detectó que la consulta nueva no guardaba en la caché negativa una sesión sin proyecto. Se corrigió
el código; la prueba no se tocó.

Incidentes, captura, ronda y registro siguen con `_proyecto_de_sesion`. No hubo cambios de esquema
ni de datos reales.

**Verificación:**
- Suite de memoria: 227 pasan (`lote4-focal.log`).
- Runner `memoria-focal` y `memoria-e2e`: rc=0, igual al baseline (`ejecutar-memoria-lote4.log`).
- `ruff`: 0.
- No se repitió la batería completa porque D está editando.

## Lote 5: cuestionar dentro de la transacción

| Defecto | Corrección | Regresión |
|---|---|---|
| `veredicto` y `cerrar_ronda` cuestionaban después del commit (`aprendizaje.cuestionar` en otra conexión). Un fallo dejaba el `repite` confirmado sin cuestionar la regla. Al cerrar, el cuestionamiento quedaba en `seq` mayor que `cierre_seq` (10 y 11 contra 8) y faltaba en `pendientes` | `aprendizaje.cuestionar` y `reglas_cuestionadas` aceptan `con`. `_cuestionar_si_repite(con, …)` corre en la transacción del veredicto, que ahora toma `BEGIN IMMEDIATE`, y en la del cierre antes de `k.cerrar_ronda`. Un error se propaga y deshace todo, sin reintentos | rollback del veredicto; cuestionamiento antes de `cierre_seq` y regla en pendientes; rollback del cierre |

**Evidencia:**
- Antes del cambio fallaron las dos primeras regresiones (`lote5-regresion-antes.log` y
  `lote5-regresion-antes-seq.log`). La de rollback del cierre se escribió con el diseño aplicado.
- Después del cambio:
  - 21 de 21 en `test_memoria_frente_c.py`;
  - suite de memoria más `test_prolog_learning`: 246 pasan (`lote5-focal.log`);
  - runner `memoria-focal` y `memoria-e2e`: rc=0, igual al baseline (`ejecutar-memoria-lote5.log`);
  - `ruff`: 0.

**Revisión:**
- `POST /reglas/cuestionar` (sin `con`) conserva su transacción propia.
- `reglas_cuestionadas` sin `con` sigue leyendo en su propia conexión.
- El diff de `aprendizaje.py` sólo toca `cuestionar` y `reglas_cuestionadas`; ruff las reindentó.
- **Comportamiento nuevo:** si cuestionar falla, se deshace todo el veredicto o el cierre.
- **Lock más largo:** el veredicto toma el lock de escritura desde el inicio y lo mantiene mientras
  recorre las reglas vigentes, sólo cuando confirma un `repite`.

## Lote 6: base bloqueada y tope de semillas

Lo pidió Ariel («arreglá lo pendiente»). Alcance: solo estos dos puntos, en `conocimiento.py`,
`veredictos.py` y `tests/test_memoria_frente_c.py`.

| Defecto | Corrección | Regresión |
|---|---|---|
| Cualquier `OperationalError`, incluido «database is locked», salía como 400 «consulta FTS invalida» (`buscar`, `buscar_prosa`) | `_rechazo_fts`: si el error es de bloqueo, ocupado, disco, apertura o solo lectura, devuelve 503 «la base no esta disponible»; si no, sigue el 400 | locked simulado (sqlite3 no deja parchear `execute`) da 503 en las dos funciones; la sintaxis rota sigue en 400 |
| Hasta 30 semillas BM25 **por consulta** (hasta 300); v5 §7.1 pide hasta 30 únicas en total | `_bm25` combina las listas por mejor puesto y desempata por id; el puntaje queda solo como dato. `preguntar` devuelve `semillas_lexicas` con encontradas, usadas y máximo | 60 encontradas → 30 usadas, 15 por lista; con escalas BM25 distintas se elige por id y no por puntaje |

**Evidencia:**
- Antes del arreglo fallaron las tres regresiones: `lote6-regresion-antes.log` y
  `lote6b-regresion-antes.log`.
- La primera versión del corte comparaba puntajes entre consultas. Lo marcó la revisión de la
  raíz; se corrigió y se agregó la regresión de escalas.
- Después del arreglo:
  - suite de memoria más Prolog: 249 pasan (`lote6-focal.log`);
  - la prueba de rendimiento con 200 nodos sigue pasando (`total > 30`);
  - runner: rc=0 los dos casos (`ejecutar-memoria-lote6.log`);
  - ruff: 0.

**Límites:**
- La UI de Memoria (`Knowledge.tsx`, que no es mío) no muestra `semillas_lexicas`: el aviso del
  corte está en la API pero no en pantalla.
- El briefing también usa el corte, porque comparte `_recuperar`.
- El bloqueo no se reprodujo con una base real: en WAL las lecturas no se bloquean.

## Lote 7: la UI muestra las semillas y el corte

Autorizado por la coordinadora. Alcance: `web/src/components/Knowledge.tsx` y una prueba nueva,
`web/tests-ui/memoria-c-semillas.spec.ts`. El backend congelado no cambió. `Learning.tsx` se le cedió
a D y no se volvió a tocar.

- **Qué muestra Buscar** cuando el servidor manda `semillas_lexicas`:
  - **Sin corte:** «Semillas por palabras: N de M (máximo X)».
  - **Con corte** (encontradas > usadas): un aviso `role=status` que dice cuántas se usaron y aclara que
    las demás no se descartan.
- **Sin el campo** (un server anterior): no se muestra nada ni hay error.
- **Conteo inválido** (usadas > encontradas, usadas > máximo o números no enteros): error de formato
  y no se muestran los resultados.

**Evidencia:**
- Antes del cambio fallaron las 4 pruebas (`lote7-ui-antes.log`).
- Después pasan 22 de 22 (`lote7-ui-despues.log`): `memoria-c-semillas`, `conocimiento`, `cinco-E-memoria`
  y `aprendizaje`, con el `Learning.tsx` actual de D. Corrieron contra un Vite aislado en 5191, cerrado
  al terminar. No se compiló `dist`.
- `eslint` y `tsc`: 0.
- La cancelación y la respuesta tardía siguen como estaban: la prueba cancela una búsqueda con corte
  y el aviso nunca aparece.

## Lote 8: paginación con foto fija y orden sin comparar puntajes

Autorizado por la coordinadora. Archivos: `veredictos.py`, `veredictos_api.py`, `Knowledge.tsx`,
`web/tests-ui/memoria-c-foto.spec.ts`, `tests/test_memoria_frente_c.py` y un ajuste autorizado a
`tests/test_captura.py`.

### Contrato

- **Primera página** (`offset` 0, sin `foto`):
  - Se calcula la lista entera y el último `seq` de cambios del proyecto se compara antes y después.
    Si cambió, responde 409, sin reintento.
  - Fija una foto en memoria con los ids y los metadatos de recuperación (procedencia, puntaje, puesto
    y salto), sin textos.
  - Devuelve `foto` con `token`, `hasta_seq` (el `seq` que corresponde a lo calculado), `ids` y
    `vence_en_s`.
- **Páginas con `foto=<token>`:**
  - Salen de la lista fija, sin duplicar ni saltear candidatos.
  - Cada nodo trae su estado actual y `cambio_despues_de_la_foto`: true si él o un vínculo suyo cambió
    después de `hasta_seq`.
  - Si el token es de otra búsqueda (proyecto, consultas, archivos, temas, tipo o saltos): 409.
  - Si venció o no existe: 410, con «repetí la búsqueda». Nunca se recalcula en silencio.
- **Sin `foto` y con `offset` > 0:** se recalcula como antes, con `foto: null` y un `foto_motivo`
  explícito, para mantener compatibilidad con `coordinar.py`.
- **Límites:**
  - Vencimiento a los 600 s.
  - 50 fotos por proceso, y se descarta primero la usada hace más tiempo.
  - 1 MB por foto y 8 MB en total.
  - Una foto más grande no se fija: `foto: null`, con un motivo que pide afinar la consulta.
  - Un reinicio del server pierde las fotos: el token responde 410.
- **Orden final:** salto, mejor puesto e id. El puntaje no ordena (v5 §7.1: las escalas de consultas
  distintas no se comparan) y queda sólo como dato. Lo marcó la revisión de la raíz.
- **`_vinculos_de` ordena por `rowid`:** un nodo trae sus vínculos en el mismo orden en cualquier página.
- **UI:**
  - «Más resultados» y «Anterior» mandan el token.
  - `foto_motivo` se muestra con `role=status`.
  - Un candidato cambiado después de la foto muestra «Cambió después de la búsqueda».
  - Una foto con formato inválido es un error.
  - La cancelación y el cambio de proyecto siguen descartando la respuesta tardía.

### Evidencia

- **Regresiones antes del arreglo:** `lote8-regresion-antes.log` (no existía `_Fotos`),
  `lote8-orden-antes.log` (`b01, c01, a01` en lugar de `a01, b01, c01`) y `lote8-ui-antes.log`
  (3 de 5 fallan; las de 410 y respuesta tardía no dependían todavía de la foto).
- **Después del arreglo:**
  - `test_memoria_frente_c.py`: 31 de 31.
  - Suite de memoria más Prolog: 256 pasan (`lote8-focal.log`).
  - Playwright: 27 de 27 con `--output node_modules/.playwright-artifacts/C-lote8`
    (`lote8-ui-despues-2.log`). La primera corrida dio 2 ENOENT en la carpeta compartida de trazas
    mientras A corría Chrome; es un problema de entorno y no se cambió ningún oráculo
    (`lote8-ui-despues.log`).
  - `eslint` y `tsc`: 0.
  - Runner: rc=0, igual al baseline (`ejecutar-memoria-lote8.log`).
- **Pruebas existentes:**
  - `test_veredictos::test_preguntar_pagina_sin_perder…` detectó que el orden de los vínculos dependía
    del lote consultado. Se corrigió el código con `ORDER BY rowid`; la prueba no se tocó.
  - `test_captura::test_preguntar_con_prosa_es_opt_in_y_no_mezcla` se ajustó con autorización de la
    raíz. Sigue comparando exacto todo salvo el token, comprueba los metadatos de la foto y que la
    prosa no cambie candidatos ni orden.
- **Vite aislado:** 5191, cerrado al terminar. No se compiló `dist`.

### Ajeno

`lienzo/conocimiento_api.py` cambió a las 23:49:51: otra sesión agregó `candidatos` a las rutas que
van a `aprendizaje_api`. Mis cambios de los lotes 1 a 6 siguen. No lo toqué ni lo revertí. El hash
actual es `8a370c2618895357`.

## Hallazgos de la revisión

- **Compatibilidad del control de cierre.** La única llamada interna a `cambiar_estado(..., "cerrada")`
  para rondas es `conocimiento.cerrar_ronda`, que pasa `cierre=True`. `replica.aplicar` escribe el
  estado con UPDATE directo y no pasa por las transiciones, así que no le afecta. Ningún cliente
  (skills, web) cierra rondas por `/nodos`. Un veredicto que traiga el ítem `ronda → cerrada` ahora
  recibe 409 en vez de cerrar sin `cierre_seq`: es el cambio buscado.
- **Archivo huérfano (riesgo bajo, aceptado).** Si la transacción de `entregar` falla después de
  `_escribir_cuerpo`, el cuerpo queda en disco sin nodo. El reintento escribe la misma ruta con el
  mismo contenido. Es el mismo patrón que ya tenía `crear_encargo`.
- **Bloqueos.** `BEGIN IMMEDIATE` toma el lock de escritura antes de leer. Antes ya se tomaba con el
  primer INSERT, así que el tiempo de espera no cambia de orden. Lo que sí cambia es que las lecturas
  de control ya no corren en autocommit.
- **Comportamiento nuevo en los reenvíos.** El reenvío idempotente de un informe que ya responde al
  encargo ahora lo pasa a entregado si estaba `enviado` (server), o si estaba `sin_entrega` y lo
  reenvía la coordinadora o una persona. Un frente nunca reabre un `sin_entrega`. No se acepta un
  informe de otro: se exige `responde_a` activo de **ese** informe a **ese** encargo.
- **Formato.** `ruff format` reacomodó además líneas que ya existían en `conocimiento.py` y
  `conocimiento_api.py` (sólo espacios). Se dejaron así.

## Sin corregir (fuera del alcance autorizado o sin reproducción confiable)

- **Suplantación `persona:`/`coordinadora:`:** necesita una credencial humana. No se inventó.
- **Otros pendientes** (detalle para la coordinadora en `C-memoria/pendientes-para-coordinadora.md`):
  - la reimportación de bases viejas;
  - el nivel 3 para externos, que no tiene credencial con alcance.

## Verificación

- **Regresiones:** las nuevas fallaron antes de la corrección por el motivo esperado
  (`lote1-regresion-antes.log`, `lote3-regresion-antes.log`). Ahora pasan las 16 de
  `tests/test_memoria_frente_c.py`. La de concurrencia se armó sobre la carrera ya corregida; su
  falla con el cálculo viejo es por razonamiento (revisión 2 contra la r2 explícita: 409).
- **Suite de memoria:** 225 pasan (`lote3-focal.log`).
- **UI:** 18 de 18 pasan en Playwright (`cinco-E-memoria`, `aprendizaje`, `conocimiento`) contra un Vite
  aislado. No se compiló `dist` ni se tocó el 7321.
- **Estáticos:** `ruff check`, `ruff format --check`, `eslint --max-warnings=0` y `tsc --noEmit`
  dan 0.
- **Batería backend completa y runner:** ver la sección «Cierre».

## Cierre

- **Batería backend completa** (`backend-completo.log`): 2682 pasan, 4 fallan y 3 se saltean, rc=1, en
  509 s. Fue exploratoria, mientras A, B y D editaban. Fallaron `test_claude_pipe`
  (WinError 10053), `test_red_resiliente`, `test_release_recovery` (409) y `test_rules_frecuencia`
  (409). Aisladas pasan 5 de 5, rc=0 (`backend-4-aislados.log`); ninguna es de memoria.
- **Runner** (`ejecutar.mjs --solo memoria-focal,memoria-e2e`, plugin 0.5.26): OK los dos, igual al
  baseline, rc=0 (`ejecutar-memoria-despues.log`). No se fijó baseline.
- **Pendientes del runner:** no hubo mutaciones ni compuerta, porque la corrida es parcial y otros
  frentes están editando.
- **Procesos propios:** cerré el Vite del 5191 (PID 21072). El server del 7321 no se tocó.
- **Hashes SHA-256** (16 primeros caracteres) de los archivos congelados, en `hashes.txt`. Se
  recalcularon después del lote 4: cambiaron `conocimiento.py` (`0d76b293446ef7d7`) y
  `test_memoria_frente_c.py` (`ed4dff71812542be`). Después del lote 5: `veredictos.py`
  `a0409efb399134f9`, `aprendizaje.py` `611bf58790fcc580` y `test_memoria_frente_c.py`
  `65326d7cde1b2499`. Después del lote 6 (congelado): `conocimiento.py` `23239508a4dc694d`,
  `veredictos.py` `e15e3d1fe42a3ade` y `test_memoria_frente_c.py` `215d48023c2c34ac`.
