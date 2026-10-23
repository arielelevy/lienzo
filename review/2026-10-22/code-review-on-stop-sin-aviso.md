# Code review: on_stop callado por un acuse sin_aviso a mitad de turno

Fecha: 2026-10-22. Alcance: `lienzo/server.py` (`accion_send`, `en_turno`), `lienzo/sessions.py` (comentario
de `sin_aviso`), `tests/test_optimizacion_trabajo.py`. Bug reportado por la coordinadora de OpenSyync
(`.temp/coordinacion/2026-10-22/bug-on-stop-0.6.15.md`).

## Causa

`send_to_session` pisa `last_prompt` con todo texto enviado, también a mitad de un turno. Claude toma ese
mensaje dentro del turno en curso (`queued_command`, sin `UserPromptSubmit`). Si era un acuse con
`sin_aviso`, al cerrar la entrega `last_prompt` coincidía con el texto del acuse y `fire_on_stop` la callaba
(«salteado: el turno respondía un envío sin_aviso»). Se vio en K2 (`a85a003b`, 23:23:12) y en Kiro
(`sess_0f7b8931`, 22:33 y 22:34).

## Primera versión y hallazgos de la revisión (skill code-review, medium)

La primera versión contaba turnos cerrados (`turnos_cerrados`) y callaba sólo el turno siguiente al de la
llegada del acuse. La revisión encontró siete hallazgos. Los principales:

1. `te_necesita` por `idle_prompt` se tomaba como turno en curso: el turno propio del acuse no se callaba.
2. Los turnos cerrados por `reconciliar` (Stop sin transición) no sumaban al contador.
3. El contador se leía en vivo desde el hilo y podía atribuirse al turno equivocado, callando la entrega.
4. Un acuse absorbido en el turno quedaba armado y podía callar un informe posterior.
5. Pi sin hooks nunca cerraba turno en el contador.
6. Campo nuevo fuera de `new_session` y comentario de forma de `sin_aviso` desactualizado.
7. Faltaban pruebas de `te_necesita` inactivo.

## Corrección final

Se quitó el contador. Un acuse que llega con un turno en curso (`corriendo`, o `te_necesita` por un permiso,
diálogo o pregunta del mismo turno) no arma `sin_aviso`, y queda en el log. Con `te_necesita` por `idle` o
`sin_enviar` se arma como antes. Así desaparecen los hallazgos 1 a 5. El costo es un aviso de más cuando
el acuse a mitad de turno termina siendo un turno propio. Perder un informe es peor.
Hallazgo 6: se actualizó el comentario. Hallazgo 7: hay pruebas para `corriendo`, `permission` e `idle`.

## Verificación

- `tests/test_optimizacion_trabajo.py`: 20 passed. Sin el cambio de `server.py`, fallan las 3 de regresión.
- ruff format y ruff check: sin cambios ni errores.
- Suite completa: ver el informe de la sesión.
