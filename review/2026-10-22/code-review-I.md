# Code review — encargo I (2026-10-22)

Alcance: `lienzo/registro_niveles.py`, `tests/test_registro_retencion.py`. Skill `code-review`, nivel medium.

| # | Hallazgo | Decisión |
|---|---|---|
| 1 | `bucle` no lo arranca nadie: `server.py` no lo importa | Por diseño de la ronda: `server.py` es de H. Diff en `.temp/resultados/2026-10-22-I/server.diff` (aplica con `git apply --recount`). Pendiente de integrar. |
| 2 | Una línea del log que llegue entre la última comprobación y `os.replace` se pierde | Aceptado y documentado en el docstring: ventana de microsegundos una vez por día; `state.log` no tiene lock que compartir y tocarlo está fuera de mi alcance. En Windows, con el archivo abierto por otro, `os.replace` falla y no se pierde nada. |
| 3 | Un error de la base frena también el log y los eventos | Corregido: `_parte` aísla cada parte y devuelve `{"error": ...}`. Prueba `test_una_base_trabada_no_frena_el_log_ni_los_eventos`; mutante `base-trabada-frena-todo` muerto. |
| 4 | El test del log dependía de la zona horaria | Corregido: `DIA_CORTE` se calcula igual que el código. |
| 5 | El copiado del log giraba sin pausa esperando el tamaño | Corregido: 10 ms por espera, tope de 100 esperas y `TimeoutError` (queda entero hasta la próxima vuelta). |
| 6 | Una conexión y migración por lote; borrado fila por fila | Corregido: una conexión, `BEGIN IMMEDIATE` y `DELETE ... WHERE rowid IN (subconsulta)` por lote de 2000, suma de bytes en la misma consulta. |
| 7 | Escaneo línea por línea del log | Aceptado: una vez por día; con el log real (11,4 MB) la depuración entera tardó 0,11 s. |

Verificación: 14 pruebas focales en verde, ruff limpio, runner OK en los dos casos, 5 de 5 mutantes muertos y el control vivo.
