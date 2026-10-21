# Cancelación del investigador: revisión y evidencia

Alcance autorizado: `optimization_queue.py`, `optimization_scheduler.py` y
`tests/test_optimization_cancel_races.py`. Se preservan D1-D3. Diseño liviano SDD:
una cancelación confirmada no se pierde ni permite volver a lanzar el caso.

## Cinco roles secuenciales en raíz

Explorer reutilizó las cuatro reproducciones independientes de A: cancelación
durante cuota lenta, cancelación al devolver el runner e historial incompleto.
Analyser recorrió HTTP → cola → tick → runner → registro y recuperación.
Designer agregó ocho regresiones con dobles y barreras de threading; todas
fallaron antes del arreglo. Después agregó la excepción del runner posterior a
una cancelación aceptada. Ningún caso usa cola real, cuotas o inferencia pagas.
Executor ejecutó los casos y toda la familia test_optimization_*: 228 passed,
rc0, 20.21s. Detective contrastó las carreras, persistencia y rollback del guardado.
No se aceptó baseline ni se ejecutó mutación en este árbol compartido en edición.
El runner global aprobado queda pendiente del congelamiento de todos los frentes.

## Solución y simplificación

Se eliminó el conjunto volátil research_cancel. La solicitud vive en la cola
persistida, bajo el mismo lock que reserva un inicio y publica un resultado.
La política se evalúa fuera del lock; al volver se relee el estado antes de cambiarlo.
Cancelación durante el runner se guarda antes de responder; el callback de parada
la observa. Al terminar, la cancelación gana si fue aceptada antes del resultado,
incluso si el runner arrojó una excepción. Guardar mal no confirma una cancelación.

El reinicio mueve running a cancelled si había una solicitud o a review si no;
anota la transición y elimina el PID operativo sin matar ningún proceso.
Los paused conservan su comportamiento D3. El registro final y la cancelación
se serializan; no se mantiene el lock mientras el runner o la cuota trabajan.

## Revisión independiente

C verificó los nueve casos nuevos y las 228 pruebas de optimización. No encontró
fallos reproducibles en los cuatro hallazgos. Informe y logs completos en
`.temp/coordinacion/2026-10-20/C-memoria/review-cancelacion-raiz.md`.
Ruff check y format sobre los tres archivos: rc0. No hay dependencias nuevas.

Límites observados: el registro final SQLite toma el lock de cola y puede demorar
la respuesta de estado/cancelación durante una espera de DB de hasta 10 s. Una
cancelación posterior a un resultado ya publicado se rechaza explícitamente.
Un paused de un archivo antiguo puede conservar un PID que nunca se usa para matar.
Los fallos pasajeros de evaluación de cuota siguen siendo failed, sin reintento
automático; no se alteró esa política dentro de esta corrección.

## Evidencia propia

`.temp/coordinacion/2026-10-20/root-calidad/cancel-red.log`: 8 fallos previos.
`cancel-green.log`: 107 casos pasan en la primera corrección.
`optimization.log`: 228 pasan con las nueve regresiones y la excepción del runner.
Los logs se guardaron completos y no se comprimieron.
Una corrida independiente de memoria dio 64 errores de setup porque raíz omitió
crear la carpeta temporal padre (WinError 3). Tras crearla: 64 passed, rc 0, 12.13 s,
en `memoria.log`. No fue un defecto del producto ni un cambio de pruebas.
