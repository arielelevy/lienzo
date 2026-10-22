# Code review noche A (2026-10-21): xfer WSL, borrado del espejo

Alcance: delta propio en `lienzo/xfer.py` (`_win_relativo` con access/share opcionales,
`_carpeta_fija(crear=)`, `_borrar_seguro`, `r_borrar`, aviso de rechazados en el emisor) y
`tests/test_xfer.py` (base WSL `/var/tmp`, guardia de tmpfiles, carrera del espejo, borrado sin
crear carpetas). Skill `code-review` nivel medium, en un fork; sólo lectura de código.

## Hallazgos y resolución

| # | Hallazgo | Estado |
|---|---|---|
| 1 | Con `_quitar_seguro`, un hardlink (nlink≠1) daba 403 y cortaba todo el borrado del espejo | Corregido: `_borrar_seguro` no exige nlink (borrar un nombre no toca el otro); los rechazos se cuentan por archivo (`rechazados`) sin frenar el resto. Prueba `test_espejo_borra_dentro_del_destino_sin_crear_carpetas` |
| 2 | El borrado creaba las carpetas faltantes (`_carpeta_fija` con OPEN_IF/mkdir) | Corregido: `_carpeta_fija(crear=False)`; `vieja/sub/c.bin` queda sin crear (misma prueba) |
| 3 | Abría con `r+b` (lectura+escritura+DELETE, share sólo lectura): más estricto que DeleteFile | Corregido: DELETE+READ_ATTRIBUTES+SYNCHRONIZE, share 7, FILE_OPEN_REPARSE_POINT, FILE_NON_DIRECTORY_FILE |
| 4 | Un junction por encima de la raíz configurada rechaza el borrado | Sin cambio: ya es la regla de todas las escrituras del receptor (`_carpeta_fija` desde la unidad con OBJ_DONT_REPARSE). Queda anotado como decisión de diseño |
| 5 | Mensaje «auxiliar fuera del destino…» al borrar | Resuelto por 1: el rechazo ya no sale como error de la respuesta; el emisor anota «N archivos no se borraron por un enlace en su camino» |
| 6 | Doble recorrido de ancestros por archivo en Windows | Corregido en el camino nuevo: un solo `_carpeta_fija` por archivo (además de `unir`). Agrupar por carpeta queda como optimización posible, no medida |
| 7 | `_locks` crece una entrada por ruta borrada | Preexistente (mismo patrón en bloque/cierre/paquete); no se tocó. Pendiente para la coordinadora |
| 8 | El comentario decía que un hardlink vuelve 403, falso en POSIX | Corregido: ahora ninguna plataforma rechaza hardlinks y el docstring lo dice |

## Verificación

- Carrera determinista: `test_espejo_no_borra_por_junction_puesta_tras_validar[unir]`, roja con el
  código original (borró `exterior-espejo/a.bin`, `.temp/resultados/noche-A/espejo-rojo.log`) y
  verde con el arreglo. `[permitido]` sustituye después del último chequeo por ruta: lo frena el
  handle (OBJ_DONT_REPARSE).
- Focales finales en `.temp/resultados/noche-A/focal-final.log`.
- Ruff check y format sobre mis dos rutas: limpios.

Límites: no se ejecutó el borrado POSIX (sin receptor Linux nativo); no hay mutación ni global.
