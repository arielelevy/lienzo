# Code review — encargo N (2026-10-22)

Delta revisado: `lienzo/sessions.py` (`adopt_process`, `_prioridad_sucesora`, `adopt_dead_target`, `set_title`,
comentario de `drop_session`), `tests/test_tarjetas_ajenas.py` y `pruebas-agenticas/tarjetas_ajenas_e2e.py`.
Skill `code-review`, nivel medium, con una revisión independiente (fork). Hubo 10 hallazgos.

| # | Hallazgo | Resolución |
|---|---|---|
| 1 | Renombrar corría la herencia completa: una muerta `restaurada` le ganaba al título, y cualquier sesión renombrada se llevaba las reglas del frente que se estaba relanzando | Corregido. Un renombre usa `adoptar_por_titulo` → `adopt_dead_target(solo_titulo=True)`, donde sólo vale el título. Prueba `test_renombrar_no_le_quita_las_reglas_a_un_frente_que_se_esta_restaurando` (roja antes) |
| 2 | Copycat también pasa por `set_title` y podía llevarse una restaurada | Corregido por el 1. El título «… · copycat» nunca coincide con uno de una muerta |
| 3 | Titular una provisoria `pid-N` la hacía sucesora, y SUCESORAS y las otras PCs quedaban apuntando a un id que se da de baja | Corregido. `sucesora_por_titulo` descarta `pid-`/`tmux-`. Prueba `test_la_provisoria_del_barrido_no_hereda_al_titularla` (roja antes) |
| 4 | Sin el respaldo «la muerta más nueva», una coordinadora sin título que se reabre a mano no recupera nada | Aceptado, es el comportamiento pedido (sucesora real). Ver «Pendientes reales» |
| 5 | La guarda de `adopt_process` también aplicaba a identidades exactas (Codex verificado, pi/coda/kiro) | Corregido. Sólo aplica a transcripciones adivinadas (`adivinada`). Codex conserva su «observado en dos procesos; no se reasigna» (`test_observation_does_not_steal…` sigue en verde) |
| 6 | Altura: un proceso personal sin hooks que adivinaba la transcripción de otra sesión viva le pisaba `backend`, `no_console` y `target` | Corregido. La guarda vale para toda transcripción adivinada, externa o no. Prueba `test_una_tui_sin_hooks_no_le_pisa_la_tarjeta_a_otra_sesion_viva` (roja antes) |
| 7 | Carrera: un segundo renombre rápido no cancelaba el hilo del primero | Corregido. El hilo relee la tarjeta y sólo hereda si el título sigue igual. Prueba `test_un_segundo_renombre_rapido_cancela_la_herencia_del_primero` (roja antes) |
| 8 | Cada renombre lanzaba un hilo que recorría las reglas | Corregido. El hilo sale sólo si `sucesora_por_titulo` encuentra una muerta, y esa consulta es barata y se hace con el lock |
| 9 | El e2e se caía con StopIteration si la regla no aparecía | Corregido. `next(..., {})` y salida 2 si POST /rules no devuelve id |
| 10 | El docstring todavía describía «la muerta más nueva» como criterio | Corregido en `sessions.py`. El de `server.preparar_sucesion` (server.py:905) es de H: queda anotado para la coordinadora |

Rojo de los arreglos de la revisión: `.temp/resultados/2026-10-22-N/rojo-revision.txt`, con 4 de 12 fallando sobre
una copia con el comportamiento previo a la revisión. Con el arreglo pasan las 12.

## Pendientes reales
- (4) Una sesión muerta sin título del usuario sólo la heredan un resume con el mismo id o una restauración desde el
  lienzo. Para que la coordinadora reabierta a mano recupere sus avisos, tiene que haber tenido título (las
  coordinadoras de las rondas lo tienen) y hay que ponerle el mismo a la nueva.
- `server.py:905`: el docstring de `preparar_sucesion` dice «antes que otra del mismo agente en la carpeta», y ya
  no hay «otra cualquiera». Archivo de H.
