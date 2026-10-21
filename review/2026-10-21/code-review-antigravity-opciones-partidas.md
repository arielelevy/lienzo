# Code review: opciones partidas y permiso de crear archivo en Antigravity

Fecha: 2026-10-21. Alcance: `lienzo/screen.py` (`dialog`), `lienzo/agentes.py` (`Antigravity.permission_option`),
`tests/test_autoaprobar.py`.

## Lo observado

- pid-7368 (agy 1.4.4) con `python -c` largo: las opciones 2 y 3 citan `'python -c "` y siguen en el renglón de abajo.
  `screen.dialog` devolvía solo las opciones 1 y 2, sin `4. No, cancel`, y la tarjeta decía «no es un permiso».
  Pantalla real leída con `screen.read_screen(7368)`.
- Permiso de crear archivo: `1. Yes, allow creation` / `2. No, deny creation`, con el diff arriba y la pregunta
  fuera de pantalla (`lienzo.log`, 16:25:20).

## Cambio

- `dialog` acepta hasta 2 renglones de continuación entre una opción y la siguiente. Solo se suman al texto si
  llega la opción n+1; si no, se descartan y la secuencia termina como antes.
- Antigravity aprueba el par exacto `yes, allow X` / `no, deny X` (dos opciones, misma palabra), sin depender
  de la pregunta.

## Revisión

- Pie o texto suelto después de la última opción: no se suma (prueba `test_dialogo_no_suma_texto_que_no_sigue_con_otra_opcion`).
- Riesgo aceptado: un menú de Claude con una descripción de 1 o 2 renglones bajo cada opción ahora se reconoce
  como diálogo, con la descripción dentro del texto. Antes no se reconocía. `permission_option` de Claude mira
  `startswith("yes")` y «ask again»: una descripción que diga «ask again» podría pasar por permiso. Es raro;
  queda anotado.
- El par `allow/deny` lo podría imitar una pregunta del modelo con esas mismas opciones literales. Es raro.

## Pruebas

- `tests/test_autoaprobar.py` y `tests/test_pregunta.py`: 43 passed.
- Suite completa: 2956 passed, 20 failed y 12 errors. Las mismas fallas aparecen sin el cambio (`git stash`):
  `WinError 6` / `WinError 50` al lanzar subprocesos desde esta sesión (`test_updates`, `test_xfer`,
  `test_infografias`, `test_diseno_regresiones` y otras).
- Server reiniciado (PID 8216). Falta verlo en vivo con el próximo diálogo largo de Antigravity.
