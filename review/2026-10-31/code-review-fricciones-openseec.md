# Revisión del delta de coordinación y preguntas de openSeec

Alcance: cambios de esta tanda en `skills/lienzo/coordinar.py`, `lienzo/auditoria.py`,
`lienzo/server.py`, `lienzo/preguntas.py` y sus cuatro archivos de regresiones.
Revisión estática en la misma sesión, aplicando code-review: errores, autorización,
concurrencia, persistencia, rutas paralelas y compatibilidad de llamadas existentes.
Sin auditoría global de dependencias ni revisión independiente por otro agente.

## Hallazgos y correcciones

- **Alto, persistencia de la espera:** la primera versión mutaba la tarjeta antes de
  `touch`; un OSError podía dejar una espera sólo en memoria pese al error HTTP.
  `server.accion_espera` ahora mantiene el lock y restaura el valor previo antes de
  propagar el error. Prueba parametrizada para declarar y cancelar con disco fallando.
- **Alto, pregunta inaccesible:** `preguntas.obtener` descartaba needs.permission antes
  de mirar si su pending era AskUserQuestion; también rechazaba ids residuales y no
  distinguía expiración. Se reproducen tres fallas antes del arreglo, conservadas en
  `permiso-variante-antes.log`. Ahora prioriza preguntas de hook vivo y, si venció,
  exige un diálogo actual antes de responder por terminal. No habilita envíos generales.
- **Medio, identidad de pestañas:** encabezado y opciones iguales podían confundir dos
  páginas del selector. La identidad y la comparación previa al envío incluyen detail.
  Regresiones para cuatro pestañas y para un cambio de pestaña antes de la tecla.
- **Medio, derivación perdida:** una pregunta de hook vivo con needs.permission también
  debe reconocerse como consulta de trabajo para llegar a la coordinadora. Se conserva
  el reconocimiento por questions del hook, sin ampliar a permisos arbitrarios.

## Verificación y límites

Ruff check y format sobre el delta. Regresiones de turnos, reglas sin_aviso, auditoría,
permisos, proceso detenido y cambios de diálogo. HTTP real con Handler y cliente reales,
tarjetas fixture y teclado simulado; sin envío a las sesiones abiertas ni reinicio de 7321.
Logs y códigos completos en `pruebas-agenticas/resultados/openseec-20261031/`.

No se afirma cierre de suite global del árbol final ni PASS de aceptación: las propuestas
nuevas no están aprobadas y no hay baseline de esta tanda. No se ejecutaron mutaciones
nuevas sin aprobación. La corrida general lanzada antes de las correcciones de revisión
se conserva como evidencia de ese estado anterior, no como certificación del final.

Sin hallazgos altos pendientes identificados en este delta. Continúan pendientes el control
automático de rojas al cerrar, la detección de acuses sin sin_aviso, los automatismos de
hunks/copias y la validación de la variante 34 en una terminal real. El origen del tool_result
de G con las recomendadas no está demostrado; los timestamps y respuestas se conservaron.

Resultado final observado: 208 regresiones del delta pasaron y la última corrección de derivación
se revalidó con 30 pruebas de preguntas. Ruff check/format y git diff --check en 0.
La corrida amplia del runner salió 1 por timeout del caso backend-pytest a 900156 ms, con marcas
de fallas sin resumen final. No se clasificaron esas rojas ni se afirmó que fueran preexistentes.
Compuerta: código 1, falta baseline.json. Tendencia: 0 de 1 casos del runner pasaron; sin mutación.
El proceso de esa suite dejó de existir y /health de 7321 respondió ok true, sin reiniciarlo.
