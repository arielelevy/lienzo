# V2 — arreglos T1, T2, T9 y T4

2026-10-22, sesión `pid-41040`. Encargo `.temp/coordinacion/2026-10-22/encargo-V2-arreglos.md`. **Arreglos implementados y verificados con pytest focal: 113 aprobadas y 1 omitida en cinco archivos, sin sumar repeticiones.** Revisión estática del delta sin hallazgos altos/medios pendientes dentro de este alcance. No es aprobación de release ni verificación en uso real.

La pausa de recursos de Ariel sigue vigente. No corrí Playwright, builds, Vite, suites amplias, WSL ni motor Prolog real. No pedí turnos. No hice git de escritura, reinicios ni cambios de configuración.

## Archivos propios para integrar

- `lienzo/codex_queue.py`
- `lienzo/creencias_revision_ia.py`
- `lienzo/registro_niveles.py`
- `tests/test_envio_publicacion.py`
- `tests/test_creencias_revision_ia.py`
- `tests/test_encargo_u.py`
- `tests/test_registro_retencion.py`
- `review/2026-10-22/code-review-V2.md`

Evidencias ignoradas en `.temp/resultados/2026-10-22-V2/`: logs completos, propuestas del plugin, `roles.json`, `actual.json`, compuerta e informe Detective. Los demás cambios presentes en el árbol son de otros frentes y no se tocaron. En particular, no modifiqué `creencias.py`, `conocimiento.py`, `prolog_*`, `hooks_eventos.py`, `sessions.py` ni `research_creencias.py`.

## Qué cambió y qué lo prueba

### T1 — diario Codex

`lienzo/codex_queue.py:141` sólo interpreta `FileNotFoundError` como diario nuevo. JSON inválido, contenido ilegible, estructura incorrecta y fechas imposibles bloquean el envío. Se validan los registros antes de usarlos. Antes de llamar al CLI, un error de lectura/escritura devuelve `rechazado`; después de la llamada devuelve `sin_confirmacion`, sin sobrescribir el diario ni reintentar. Confirmar tampoco sobrescribe un diario ilegible.

En `tests/test_envio_publicacion.py:315` y siguientes se comprueban JSON corrupto, raíz no diccionario, registro nulo y `PermissionError`; el runner y `_save` fallan el test si se invocan. También se prueba una reserva incierta real en un archivo temporal, error de lectura, recuperación y segundo intento sin reenviar; corrupción entre el envío y el guardado; y timestamp numérico que antes producía `OverflowError`.

- **Rojo inicial:** 4 fallas, `T1-rojo.log`, salida 1; intentaba guardar encima del diario ilegible.
- **Borde adicional rojo:** `T1-fecha-rojo.log`, salida 1, `OverflowError: int too large to convert to float`; corregido con rango válido de timestamp sin conversión desbordante.
- **Verde final:** archivo de publicación completo, 37 aprobadas dentro de `final-dos-focales.log`; transporte existente en `tests/test_codex_queue.py`, 21 aprobadas, `codex-regresion.log`.

### T2 — redacción al enviar y al persistir respuestas

`lienzo/creencias_revision_ia.py:36` reutiliza `redact_deep` y `SECRET_KEY` de `optimization_research.py`. No se copian patrones de credenciales. Un `object_hook` oculta valores de campos sensibles a cualquier profundidad, incluso si su contenido no tiene un formato conocido. Luego el redactor existente limpia textos libres. Se aplica a propuestas, fuentes, candidatos y respuestas de Claude/Codex; el punto previo a persistencia vuelve a cubrir adaptadores de decisión. No se mutan los objetos originales.

`tests/test_creencias_revision_ia.py:23` captura stdin de ambos runners simulados y comprueba ausencia de Bearer, sk-proj, contraseña en URL, asignaciones y un valor arbitrario bajo `api_key`. También devuelve un token desde ambos runners y verifica su redacción. `:47` aplica una respuesta con token y comprueba que no entre al veredicto, evidencia, tanda ni historial de cambios.

- **Rojo inicial:** 3 fallas, `T2-rojo.log`, salida 1.
- **Borde adicional rojo:** `T2-campos-rojo.log`, salida 1; el redactor de formatos por sí solo no cubría un valor arbitrario bajo `api_key`. Se agregó el tratamiento de nombres usando el patrón existente.
- **Verde:** `T2-verde.log`, 3 aprobadas; todos los casos siguen verdes en el focal final de IA.

Límite real: se reconocen los formatos del redactor existente y nombres sensibles, no cualquier secreto arbitrario sin señal en texto libre. Los originales ya guardados se conservan privados; no se reescribió el historial ni se eliminaron snapshots necesarios para deshacer.

### T9 — cuerpos de adjuntos y resultado no evaluable

`lienzo/creencias_revision_ia.py:76` lee los artefactos referenciados por las fuentes dentro de la carpeta del proyecto. Rechaza rutas absolutas, traversal y resoluciones fuera del proyecto, además de archivos no regulares. No convierte rutas mencionadas en texto libre en instrucciones de lectura.

Límites conservadores: 1.000.000 bytes por archivo, 6.000 caracteres de texto; por tanda, 8.000.000 bytes y 40.000 caracteres. Se admite texto UTF-8; contenido binario, vacío, ausente o truncado hace la tanda no evaluable. El hash se calcula sobre los bytes originales completos dentro del límite; se compara con el esperado si existe. Una evidencia recibida sin hash tampoco habilita un veredicto. Para un archivo que supera el límite de bytes se registra hash calculado `null`, hash esperado si existe, bytes efectivamente leídos y `truncado: true`: no se inventa el hash de lo no leído.

El prompt recibe el cuerpo redactado, distinto del nombre/caption. La tanda guarda manifiesto de lectura: proyecto, nodo, ruta, hash esperado/calculado, bytes leídos, estado y truncamiento, sin copiar el cuerpo a la auditoría. Se deduplican lecturas de una fuente compartida. Antes de aplicar se vuelven a comprobar los adjuntos, además del control existente de nodos y vínculos; un cambio devuelve 409 y revierte la aplicación.

Si falta una fuente indispensable, la tanda completa se bloquea sin llamar a la IA ni aceptar/rechazar/corregir/fusionar creencias. Se guarda únicamente una evidencia de auditoría `revision_ia_no_evaluable` con el manifiesto y se devuelve **HTTP 422 «Tanda no evaluable»**. La UI actual ya muestra ese error. Esto evita devolver `id: null`, que su componente interpretaría incorrectamente como «No hay propuestas pendientes». La auditoría no se presenta como tanda reversible ni como veredicto humano/delegado.

Pruebas en `tests/test_creencias_revision_ia.py:72` y siguientes: contenido real redactado y hash durable; archivo ausente o alterado; hash ausente; referencia vacía; ruta absoluta/traversal; binario; truncamiento por texto y bytes; límites 5.999/6.000/6.001; respuesta API 422 visible; archivo cambiado mientras responde la IA sin cambio de metadatos. Las propuestas quedan pendientes ante estas fallas; sólo aparece la evidencia de auditoría prevista.

- **Rojo inicial:** 8 fallas, `T9-rojo.log`, salida 1; se omitía el cuerpo y se intentaba consultar incluso sin evidencia completa.
- **Verde inicial:** 8 aprobadas, `T9-verde.log`.
- **Borde adicional rojo:** `T9-sin-hash-rojo.log`, salida 1; evidencia recibida sin hash aún permitía consultar. Corregido.
- **Verde final de IA:** 34 aprobadas y 1 omitida dentro de `final-dos-focales.log`.

La prueba omitida ya existía y corresponde a AB.3/contrato AA. No se afirma que se haya implementado ni ejecutado desde V2. El fixture del focal de IA bloquea `subprocess.Popen` y simula notificaciones de proyecciones AA: no puede lanzar un proveedor, navegador o SWI/WSL accidentalmente.

### T4 — crudo sin cursor

`lienzo/registro_niveles.py:131` sólo permite borrar una captura si su proyecto tiene marca de lectura y la fecha está dentro de esa marca, además del corte de retención. Sin cursor, la subconsulta SQL devuelve NULL y no habilita el borrado. Se conserva la guarda del rowid máximo y el tratamiento de cursor inválido.

`tests/test_encargo_u.py:22` cambia deliberadamente su resultado esperado: conserva la fila de 40 bytes del proyecto sin cursor. Antes esperaba borrarla; ahora se cumple la decisión explícita de la coordinadora basada en «no borrar crudo que todavía no se leyó». El nuevo caso `:45` comprueba que sin ningún cursor no se borra nada. Los casos de zona horaria y cursor inválido siguen vigentes.

También se ajustó **sólo la precondición** de dos casos de `tests/test_registro_retencion.py`: ahora declaran que el investigador ya leyó las capturas. Sus expectativas de corte a 30 días y de preservación del rowid más alto se mantienen. Sin esa precondición consagraban el contrato anterior de borrar por edad aunque no hubiera lectura.

- **Rojo inicial:** 2 fallas y 2 aprobadas, `T4-rojo.log`, salida 1.
- **Verde:** 11 aprobadas en `T4-verde.log`.
- **Regresión inicial:** 2 fallas y 8 aprobadas, `retencion-regresion-inicial.log`, por ausencia de marca de lectura en los dos escenarios que pretendían depurar.
- **Regresión actualizada:** 10 aprobadas, `retencion-regresion.log`.

## Cinco roles y revisión del delta

Se trabajó secuencialmente en esta sesión con `pruebas-agenticas`: Explorer leyó fuentes/casos vigentes y delimitó el backend; Analyser contrastó los cuatro requisitos explícitos; Designer preparó los escenarios rojo/verde y controles; Executor lanzó los comandos focales y guardó salida completa/códigos; Detective contrastó las fallas y las verificaciones finales. Los artefactos formales se consolidaron al cierre, sin fingir navegación real ni horarios de etapas que no se midieron. `roles.json` registra esa limitación y los comandos.

- `delta.mjs`: **1**, blueprint válido, sin aprobación humana.
- `certificar.mjs`: **1**, cuatro requisitos válidos; dos límites declarados, sin aprobación humana.
- `trazabilidad.mjs`: **1**, nueve casos, positivos/negativos para los cuatro requisitos y bordes de adjuntos, **«Sin hallazgos»**; falta aprobación humana de las propuestas. Se conservaron los avisos de la primera propuesta y su corrección documental.
- Cuatro mutaciones propuestas, **ninguna aprobada ni ejecutada**. No se cambió baseline ni configuración del proyecto.
- Runner de aceptación: `--no-ejecutado`, salida **0**, registra exclusivamente la aceptación no corrida; los pytest focales constan separadamente.
- `compuerta.mjs --informe`: **ESCALAR (3)**, por aceptación explícitamente no ejecutada. **No es PASS.**

`code-review` aplicado al delta: errores de lectura/persistencia antes y después del envío, conservación de reservas, separación de datos originales/redactados, validación de rutas, presupuestos, hash, atomicidad del veredicto y exposición del error en la UI existente. Se corrigieron en el mismo alcance los bordes de clave sensible sin formato, hash ausente y timestamp desbordante. No se duplican los hallazgos ajenos T3/T5–T8/T10/T11 del informe total ni se los declara resueltos desde V2.

Verificaciones finales:

| Comando focal | Resultado | Log |
|---|---|---|
| `py -3.14 -m pytest tests/test_envio_publicacion.py tests/test_creencias_revision_ia.py -q -p no:cacheprovider` | 71 aprobadas, 1 omitida; código 0 | `final-dos-focales.log` |
| `py -3.14 -m pytest tests/test_codex_queue.py -q -p no:cacheprovider` | 21 aprobadas; código 0 | `codex-regresion.log` |
| `py -3.14 -m pytest tests/test_encargo_u.py -q -p no:cacheprovider` | 11 aprobadas; código 0 | `T4-verde.log` |
| `py -3.14 -m pytest tests/test_registro_retencion.py -q -p no:cacheprovider` | 10 aprobadas; código 0 | `retencion-regresion.log` |
| Ruff check, sólo los siete archivos propios de código/pruebas | código 0 | `ruff-check.log` |
| Ruff format check, mismos siete archivos | código 0, siete archivos formateados | `ruff-format.log` |
| `git diff --check` | código 0 | comprobación local |

La primera ejecución T1 fue bloqueada por sandbox con `PermissionError: [WinError 5]` en el directorio temporal de pytest; se obtuvo aprobación y el rojo funcional se ejecutó después. Una aserción inicial de T2 buscó `veredicto_motivo`, que no existe; se corrigió para inspeccionar los datos persistidos reales, conservando el mismo oráculo de ausencia del token. No se cuentan esas fallas de entorno/test como defectos adicionales del producto.

No cubierto: llamada de IA real, interacción de navegador, integración con motor Prolog real, suite global, mutación, rendimiento bajo carga ni despliegue en 7321. Los límites conservadores de adjuntos pueden producir 422 en evidencias grandes o binarias; ése es el comportamiento previsto para no aceptar con evidencia incompleta. La pausa de recursos no se levantó.

ESTADO: listo para commit de los ocho archivos propios enumerados; aceptación integral pendiente.
