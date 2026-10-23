# Code review B: cuatro bugs

2026-10-23. Revisión focal de `lienzo/sessions.py`, `tests/test_encargo_b_bugs.py`,
`tests/test_autoaprobar.py` y `tests/test_optimizacion_trabajo.py`. Mismo agente, sin delegación.
Alcance dado por el encargo; no se auditó el resto del repositorio ni sus dependencias.

## Hallazgos y resolución

1. **Alta, corregida.** `answer_dialog`, rama numérica: el diálogo persistido podía estar cerrado.
   Se reutiliza `_dialogo_en_pantalla`, que relee consola, compara opciones y llama `same_dialog` del
   perfil antes de escribir. Un error de lectura devuelve 409 con motivo; no escribe el número.
   Dos regresiones fallaron con 200 antes del cambio y pasan con 409 después.
2. **Alta, corregida.** `_nombrar_nativo`: `typing` proviene del barrido y no prueba que la caja esté
   vacía ahora. Se relee antes de cada comando, se exige una caja reconocible entre reglas, sin texto
   activo, sin cola y sin diálogo. Se difiere con `native_deferred`; no borra el borrador.
   En la propia revisión se añadió el rechazo de lectura vacía sin caja reconocible: el parser por
   sí solo la clasificaba como placeholder. Se verifican caja con `11`, error de lectura, pantalla
   sin caja y caja vacía válida.
3. **Test ajustado.** La prueba existente que sólo verifica el cambio de columna de un diálogo no
   preparaba pantalla ni PID. Ahora sustituye expresamente la revalidación con un diálogo vigente;
   los casos nuevos prueban el rechazo real con lectura fallida o sin diálogo.
4. **Kiro, sin cambio productivo.** `accion_send.en_turno` ya aplica a Kiro. La regresión recorre dos
   turnos con `apply_turn_unhooked` y sus envíos, con un acuse intermedio por turno. El reloj virtual
   mantiene el enfriamiento de 30 segundos real entre entregas. La primera versión del test no
   avanzaba `datetime.now()` y difería el segundo aviso; se corrigió el diseño temporal del test.

## Riesgos y límites

- La lectura y la inyección en una TUI no son atómicas. Una persona puede escribir o cerrar el menú
  entre ambas. Este cambio elimina el uso de una muestra vieja del barrido, pero no garantiza
  exclusión mutua con el teclado humano ni con otros procesos. No se afirma que ésa fuera la causa
  exacta del incidente remoto; sí se reprodujo un mecanismo capaz de generar los «1».
- `screen.input_area` interpreta los placeholders existentes; no se rediseñó el parser.
- El rechazo de una pantalla que no reconoce la caja puede diferir un renombre válido. Es el
  comportamiento conservador autorizado por el encargo y deja un motivo visible.
- El hallazgo de direcciones del beacon continúa abierto. Se entrega diseño y reproductor aislado,
  sin cambiar el protocolo ni prometer compatibilidad mixta no medida.
- Las pruebas usan fixtures de consola/transcripción. No se enviaron teclas a sesiones reales.

## Comprobaciones

`ruff check` sin hallazgos en los cuatro archivos. `ruff format` aplicado sólo a esos archivos.
Pruebas focales: 110 passed. Runner del plugin: B-focal OK, salida del runner 1 por baseline ausente.
No se fijó referencia ni se aprobó ningún artefacto. La compuerta no acredita PASS.

Suite completa: 3644 passed, 11 skipped en 888.74 s, código 0, una sola ejecución.
El estado final se documenta en `informe-B-bugs.md`.
No quedan hallazgos nuevos bloqueantes dentro del cambio implementado; permanecen los límites
de atomicidad de consola y la migración del beacon indicados arriba.
