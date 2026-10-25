# Revisión focal: tokens por turno

Fecha: 2026-10-25. Revisión secuencial del implementador Codex `01a173c8-4826-7d83-bce0-5dd684c7647a`; no independiente.

## Alcance

`turn_usage.py`, captura de respuesta, identidad del turno en sessions/hooks y pruebas de lector/captura/réplica. La réplica productiva no requiere cambio: `origen` JSON ya viaja íntegro. Se ajusta la precondición de la fixture de transcript real para no confundir archivos de metadatos con conversaciones. Sin cambios en creencias ni reclasificación ni casillas completadas.

## Hallazgos revisados y resueltos

- Deduplicación de Claude por mensaje, conservando el último contador publicado de cada campo. No se suman bloques duplicados. Campos ausentes o inválidos no se convierten en cero. Un mensaje sin identidad impide certificar su consumo.
- Diferencia de acumulados Codex, incluyendo todas las llamadas del turno y separando cache leído del input. Evento task_started duplicado no reinicia la base. Cierre confirmado por task_complete/turn_aborted. Si cualquier acumulador baja, se descarta toda la comparación; no se mezclan deltas de una base reiniciada.
- Rama Pi elegida por hoja capturada; SQLite coda sólo lectura, sesión completa como filtro y límites del pedido. URI de SQLite escapada mediante Path.as_uri; parámetros SQL para valores, lista de columnas constante.
- Lectura completa en streaming, tamaño congelado al abrir y sin límite artificial de 2 MB. Un archivo truncado/corrupto no se presenta como consumo completo. El error se registra por clase sin imprimir contenido ni ruta. La captura de respuesta se conserva con usage null.
- I/O exclusivamente en el worker de captura, no al encolar ni bajo el lock de sesiones. La fuente del evento es una copia; un pedido posterior no cambia su identidad. Referencia vieja borrada al entrar pedido nuevo por hook.
- `origen` sólo contiene números/null e identidad del turno; no almacena ruta local de transcript. Las capturas históricas siguen inmutables.

## Verificación y límites reales

Primera focal de lectores/captura: 68 pruebas pasan. Con réplica y captura inmutable: 90 pasan. Con enlace de cierre real de hooks Claude y parser Codex: 96 pasan antes del último borde de reinicio parcial de acumuladores.

La primera batería ampliada dio 3 fallas, 244 pasadas y 3 omitidas: la fixture de Claude elegía el archivo más reciente, que sólo contenía custom-title/agent-name/mode/permission-mode/bridge-session/system. Se ejecutó el parser de HEAD sin cambios sobre el mismo archivo: cero turnos, cero digest y cero assistant. Se corrigió sólo la selección del dato real para exigir herramienta y resultado enlazados presentes en el JSONL crudo. No se cambiaron aserciones ni el parser. Después, test_transcripts dio 35 pasadas y 3 omitidas por ausencia de rollouts Codex en su fecha configurada.

Prueba viva de sólo lectura en un turno cerrado Codex: el lector coincide con una resta independiente de acumulados. Resultado input 31.271, output 23.747, cache_read 8.347.008, cache_write null, reasoning 8.781. Archivo de 3.578.639 bytes; lectura 17,72 ms en esa condición. No se escribieron capturas sintéticas en la memoria productiva.

La corrida final se conserva en `pruebas-agenticas/resultados/tokens-por-turno/`. Sin baseline ni mutaciones aprobadas: no hay PASS certificado de compuerta. Kiro observado sólo publica créditos/contexto y queda null; Pi se valida con fixtures de su árbol, no con una sesión real nueva. No se rellenan capturas anteriores ni se corrigen después si llegan contadores más tarde. Identidad ausente o formato no reconocido se informa como desconocido.

Corrida final `2026-10-25T18-01-46.209Z-21204`: 250 pruebas pasan y 3 se omiten por los rollouts históricos Codex ausentes. Caso del runner código 0, runner código 1 por baseline ausente; compuerta código 2. Ruff, formato focal y diff-check código 0. La primera corrida fallida queda preservada y no se cambia su resultado.

El chequeo final detectó una regresión de formato en el caso de reinicio parcial de acumuladores. Se reformateó antes de publicar: ocho archivos conformes y AST del test idéntico al ejecutado. No se altera el resultado anterior ni se presenta como nueva corrida de pruebas.

No se reinicia un servidor durante las pruebas; avisar previamente a la coordinadora antes de activar.
