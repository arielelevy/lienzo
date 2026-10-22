# Code review — encargo Q (aprendizaje por proyecto), 2026-10-22

Skill `code-review` en nivel medium, sobre el delta de Q:
- código: `lienzo/creencias.py`, `lienzo/conocimiento_api.py`, `lienzo/contexto_ia.py` (nuevo) y
  `web/src/components/Learning.tsx`;
- pruebas: las de Python y las specs de interfaz.

Se sumaron dos hallazgos P2 de la revisión independiente V (`code-review-V.md`): V-4 y V-5. Toda corrección tuvo
antes su prueba roja (`.temp/resultados/2026-10-22-Q/rojo-review.txt`, `rojo-V.txt`).

| # | Hallazgo | Resultado |
|---|---|---|
| 1 | `conocimiento_api.py`: una tarjeta elegida de otro proyecto caía a la sesión viva más reciente de este | Corregido: la búsqueda de reemplazo corre sólo si no se mandó `session_id`. Prueba `test_cr1` |
| 2 | `creencias._vigencia`: sin contexto devolvía «vigente» antes de validar un contexto roto | Corregido: primero `contexto_invalido`. Prueba `test_cr2` |
| 3 | `Learning.tsx`: el formulario de corrección seguía abierto en la tarjeta ya reemplazada | Corregido: se muestra sólo si la creencia no está cerrada (`fixing && !closed`). Sólo tsc y eslint; la prueba de UI quedó en pausa por recursos |
| 4 | «Renovar» acortaba una vigencia más larga | Corregido: se toma el máximo entre la vigencia actual y hoy + 90 días. Prueba `test_cr4` |
| 5 | Una revisión que fallaba (409, dimensión inválida) dejaba una evidencia `revision_humana` suelta | Corregido: la evidencia nace en la misma transacción `BEGIN IMMEDIATE` que el veredicto, como nodo con los datos de la revisión y sin archivo. Prueba `test_cr5` |
| 6 | `_version_agente` se rompía con líneas JSON que no son objetos y duplicaba el lector de transcripciones | Corregido: usa `transcripts.tail_lines` e `iter_json`, y lee la versión sólo de transcripciones de Claude o Codex. Prueba `test_cr6` |
| 7 | La IA no se podía cancelar: cada reintento apilaba un `claude` y un hilo del server | Mitigado: una interpretación por proyecto a la vez; la segunda recibe 409. La CLI sigue sin cortarse cuando el cliente se va: el plazo de 45 s es el tope. Prueba `test_cr7` |
| 8 | `Learning.tsx`: el estado del filtro sobrevivía al cambio de proyecto | No hizo falta cambiar nada: `ProjectPanel` tiene `key={selected}` y cada proyecto remonta `Learning`. Lo cubre la spec «respuesta tardía…» |
| 9 | `_sesion_reciente` resolvía el proyecto de cada sesión viva, una por una | Corregido: se resuelve una vez por carpeta distinta, `(repo_key, cwd, pc)` |
| 10 | Lector de transcripciones duplicado | Corregido junto con el 6 |
| V-4 | Al abrir no se veía qué dijo el motor | Corregido: `_item` trae el `contraste` que guardó S y la vista suma las reglas derivadas cuestionadas. La tarjeta muestra «Motor lógico: …» aparte del veredicto humano, y el motivo cuando no hubo motor. Prueba `test_v4` y spec nueva |
| V-5 | Las creencias de proceso de Lienzo no entraban en el checklist de otros proyectos | Corregido en `prolog_checklist.checklist` (cambio mínimo; el archivo es de J). Se suman una vez, evaluadas y contrastadas en `lienzo`, con su motor en `motor_proceso` y su `proyecto` dueño. El uso se registra en `lienzo` y el texto del encargo nombra el proyecto. Pruebas `test_v5_*` y spec nueva |

Pendientes reales:
- Con el cliente desconectado, la CLI de Claude del hallazgo 7 sigue viva hasta 45 s; sólo se evita que se apile.
- Las pruebas de interfaz de V-4, V-5 y del hallazgo 3 esperan que termine la pausa de recursos (suite de OpenSyync).
