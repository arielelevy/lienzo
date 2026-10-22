# Code review — encargo S (investigador de creencias en segundo plano), 2026-10-22

Skill `code-review`, nivel medium, sólo sobre el delta de S (el árbol tiene trabajo de otros frentes):
`lienzo/research_creencias.py` (nuevo), `lienzo/optimization_scheduler.py`, `lienzo/optimization_activity.py`,
`lienzo/optimization_queue.py`, `lienzo/optimization_research_runner.py`, `lienzo/optimization_research.py`,
`tests/test_research_creencias.py` (nuevo), `tests/test_optimization_research.py`, `tests/test_research_azure.py`.

La revisión devolvió 10 hallazgos sin verificar. Cada uno se verificó con una prueba en rojo antes de corregirlo
(`.temp/resultados/2026-10-22-S/rojo-review.log`: 6 en rojo).

| # | Hallazgo | Resultado |
|---|----------|-----------|
| 1 | Una vuelta se encolaba por cualquier cambio sin leer (datos, vínculos, nodos fuera de lo que se manda): vueltas del modelo sin nada que leer | **Corregido.** Sólo cuentan los cambios que crean un nodo relevante o le cambian el estado; el resto se absorbe en el cursor sin vuelta (`_classify`, `estado`). Prueba `test_irrelevant_changes_are_absorbed_without_a_model_round` |
| 2 | La poda de la cola borraba vueltas del día y con ellas sus inicios (tope diario) y su clave | **Corregido.** Sólo se podan vueltas terminadas con último inicio de hace más de 24 h. Prueba `test_full_queue_keeps_belief_rounds_that_ran_today` |
| 3 | Las muestras con agentes trabajando sumaban a `good_samples`: al quedar quieta la PC se salteaba la segunda muestra | **Corregido.** Contador propio `fondo_samples`; el modo segundo plano deja `good_samples` en 0. Prueba `test_busy_samples_do_not_count_as_quiet_ones` |
| 4 | `record` corría bajo el lock de la cola (el contraste puede despertar WSL) y una excepción dejaba el trabajo fallido sin evidencia | **Corregido.** El registro corre fuera del lock; si falla, el trabajo queda `failed` con evidencia de fallo y el cursor sin avanzar. Prueba `test_record_failure_leaves_failed_job_with_evidence_and_cursor_untouched`. Las escrituras son idempotentes por clave: repetir la vuelta no duplica |
| 5 | `resguardo_capturas()` no está conectado a la depuración del crudo | **No corregido acá (fuera de alcance).** `registro_niveles.py` es de I: propuesta con diff y prueba sugerida en `.temp/resultados/2026-10-22-S/registro_niveles.propuesta.md`, la integra la coordinadora |
| 6 | `status()` devolvía el diccionario vivo de la vista de creencias | **Corregido.** Copia. Prueba `test_status_returns_a_copy_of_the_belief_view` |
| 7 | Una mirada recorría y hasheaba las fuentes tres veces | **Corregido en parte.** `case()` recibe los pendientes ya calculados (dos recorridos menos por tick); `gather` al lanzar sigue recorriendo, porque es lo que se lee de verdad |
| 8 | Un archivo tocado sin cambio de contenido se re-hasheaba siempre; el docstring decía un proyecto por tick | **Corregido.** La firma nueva se guarda sin releerlo. Prueba `test_touched_file_with_same_content_is_not_rehashed_forever`. Docstring corregido |
| 9 | La prioridad baja usaba `preexec_fn` en POSIX (inseguro con hilos) | **Corregido.** `os.setpriority` después de lanzar. Se deja la prioridad baja para todo el investigador de fondo (también el viejo): es el pedido de no quitarles CPU a los agentes |
| 10 | `_check` duplica el validador anidado en `optimization_research.validate` | **No corregido.** Unificarlo cambia el validador del investigador viejo (otra semántica de `minLength`); queda como pendiente para la coordinadora |

Verificación después de corregir: `tests/test_research_creencias.py` 32 passed (3 de 3 repeticiones); suites que
importan los módulos tocados 326 passed; ruff sin hallazgos en las rutas de S.

Mutación manual en una copia fuera del repo (`.temp/resultados/2026-10-22-S/mutacion-manual-2.log`): control
sobrevive; 6 de 6 mutantes muertos (umbral 1,5 GB, sin filtrar propias, contradice ignorado, agentes cortan la
vuelta, cursor sin guardar, poda sin día). El mutante «sin filtrar propias» sobrevivía en la primera medición:
se sumó `test_existing_beliefs_and_proposals_are_context_not_sources`.
