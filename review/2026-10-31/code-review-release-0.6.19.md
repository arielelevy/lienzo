# Revisión del corte 0.6.19

Fecha: 2026-10-31. Revisión secuencial por la sesión principal con code-review.
Alcance nuevo: `tests/test_xfer.py`, `web/tests-ui/capturas.spec.ts`,
`pruebas-agenticas/tarjetas_ajenas_e2e.py`, metadatos de versión y notas del release.
El código de producto entre v0.6.18 y 0848396 reutiliza las revisiones guardadas
en review/2026-10-28, review/2026-10-30 y code-review-fricciones-openseec.md.
No se presenta esta revisión del corte como una segunda auditoría completa de esos 130 archivos.

## Hallazgos corregidos

- Capturas: siete espacios U+3000 literales violaban no-irregular-whitespace.
  Se expresan con escapes dentro del template; el texto HTML resultante es idéntico.
- Xfer sin espejo: la prueba de conservación copiaba 302 archivos y falló con estado
  copiando a los 60 s. El diagnóstico del caso original sin cambiar el plazo pasó
  en 53.11 s; las operaciones r_estado sumaron 14.78 s y r_paquete 40.48 s.
  Se acotó sólo este caso a dos archivos de origen y dos sobrantes, en raíz y subcarpeta.
  Ahora comprueba bytes de lo copiado y de ambos sobrantes. La copia masiva y la
  detección de cambios siguen cubiertas por sus tres casos existentes, sin modificaciones.
  No se cambian plazos, permisos, prioridad de Windows, fsync ni confinamiento de producción.
- El plazo del E2E de tarjetas se revisa por separado en code-review-plazo-tarjetas-ajenas.md.

## Verificación

- Ruff check global: código 0. Ruff format --check: 569 archivos con formato correcto.
- Xfer sin espejo corregido: 1 passed; llamada de 0.49 s, 4.71 s total.
- Frontend: primera corrida conserva el fallo de lint; unitarias 9/9 archivos,
  Playwright 353 passed y 16 skipped, build código 0.
- Tras corregir lint y ajustar versión: lint y build revalidados, ambos código 0.
- git diff --check: código 0.
- Suite completa de backend en curso; no se aprueba el release antes de leer su resumen.

## Límites

No se midió esta tanda en ar-it33940. No se presentan las siete pruebas previas
verdes en esta PC como demostración de que esa otra PC está corregida.
La medición de prioridad de Windows cambió el hilo de 0 a -4 pero no aumentó el
tiempo de 30 fsync: 0.058 s en ambos modos. No se le atribuye la demora de xfer.
No se regeneraron baselines después de fallos. La aceptación del plugin aún carece
de baseline en este directorio; los códigos de los casos y el del runner se distinguen.
STT-CLI y sus ajustes locales no se publican ni se incorporan al repositorio.

## Retención y mutaciones

La corrida global detectó tres pruebas de encargo U con un fixture anterior al
resumidor. Se reprodujeron aisladas: 3 fallos y 8 éxitos. El contrato vigente exige
ambos cursores (ver registro_niveles y test_registro_retencion). Se agrega únicamente
el archivo de cursor válido del resumidor para ejercitar los mismos oráculos:
borrar hasta la marca del investigador y rechazar su fecha inválida conservando datos.
Los 23 casos de encargo U y retención pasaron después; no se cambia producción.

Mutaciones previamente aprobadas de fdd-hoy, sólo con su caso focal y en copia física
aislada: sanidad 68 passed; cinco defectos reales muertos por sus aserciones y control
de docstring vivo (5 de 6). Se leyeron las cinco firmas de fallo y el log del control.
El comando mutar salió 1 por el control superviviente de la configuración heredada;
no se convierte ese código en PASS de aceptación. No hubo mutación del servidor vivo.
Los hashes antes/después acreditan restauración de los tres archivos y el árbol de
la copia quedó limpio. Las diferencias CRLF/LF con el origen se normalizaron sólo
para comparar; los bytes de la copia restaurada coinciden con sus hashes iniciales.

Otra roja de la corrida global fue el doble de regla_informe del caso de PID a UUID:
no aceptaba el parámetro keyword solo_si que el cliente ya utiliza. Se reprodujo el
TypeError y se actualizó el doble para exigir ese keyword y comprobar ESTADO:.
Los 13 casos de ronda4/entrada pasaron después. La primera invocación focal incluyó
por error test_coordinar_confirmacion.py (inexistente): no ejecutó casos; se conserva
ese código 1 y no se lo informa como fallo del producto.

## Estado al publicar

La suite global local posterior pasó: 4098 passed, 11 skipped, código 0.
Frontend posterior: 355 passed, 16 skipped; lint, nueve archivos unitarios y build código 0.
El botón Denegar y la corrección posterior de excepciones se revisan en
`code-review-denegar.md`: 120 regresiones pasaron en copia aislada; no se repite la suite
global histórica como si certificara ese delta posterior.

En ar-it33940 se ejecutaron las ocho regresiones: seis pasaron y dos fallaron por
rendimiento (guardar memoria 53,47 ms frente a 50 ms; briefing 332,8 y preguntar
302,3 ms frente a 200 ms). Logs completos en
`pruebas-agenticas/resultados/release-0.6.19-20261031/remoto-evidencia-final/`.
Después de informar esos resultados, Ariel pidió explícitamente publicar y reiniciar.
Se registra la excepción a la condición previa, sin cerrar las dos tareas ni informar PASS.
