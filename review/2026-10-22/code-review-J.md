# Code review — encargo J (2026-10-22)

Skill `code-review` (nivel medium, agente bifurcado) sobre el delta de J: `lienzo/prolog_checklist.py` (nuevo),
`prolog_learning.py`, `prolog_contraste.py`, `creencias.py`, `conocimiento_api.py`, `web/src/components/AprendizajeBar.tsx`
(nuevo), `Learning.tsx`, `Knowledge.tsx`, `App.tsx`, `styles.css`, las pruebas y los scripts de `pruebas-agenticas/`.
La revisión no ejecutó código; cada hallazgo se verificó acá antes de corregirlo.

| # | Hallazgo | Verificación | Resultado |
|---|---|---|---|
| 1 | Crear un encargo corría el motor en línea: con WSL dormido hasta 90 s + 20 s, y `coordinar.pedir` corta a los 20 s; el reintento da 409 | Real. Rojo: `test_crear_un_encargo_no_espera_que_arranque_wsl` | Corregido: `para_encargo` usa `esperar_wsl=False`; con WSL dormido lo mostrado va «sin contraste del motor lógico». La vista sí despierta |
| 2 | `_modelo` guardaba un solo origen por regla (`dict`): una regla derivada de dos creencias daba `con_diferencias` con el motor correcto | Real. Rojo: `test_regla_cuestionada_con_dos_origenes_cuestiona_a_las_dos` | Corregido: pares `(regla, origen)`; mutación `regla-un-solo-origen` propuesta |
| 3 | `test_unavailable_timeout_and_invalid_result_are_visible` dependía del orden: en Windows el despertar convertía el timeout falso en «WSL no arrancó» | Real (pasaba sólo si otra prueba había tocado WSL hacía <30 s) | Corregido: la prueba fija `motor.WSL = False` |
| 4 | El despertar corría con el semáforo del motor tomado: un arranque lento dejaba «ocupado» a todo lo demás hasta 90 s | Real | Corregido: el despertar va antes del semáforo en las dos `run` |
| 5 | `DESPERTAR_TRAS_S = 30`: la distro podría apagarse antes | Parcial. Lo caro es la VM (8,9 s medidos), que WSL apaga a los 60 s sin uso (`vmIdleTimeout` por defecto); reiniciar sólo la distro con la VM viva entra en el plazo de 12–20 s | Sin cambio. Riesgo aceptado y anotado; no se midió el reinicio de la distro sola, porque `wsl -t` cortaría las sesiones WSL de otros frentes |
| 6 | `_modelo(facts)` se calculaba dos veces por consulta | Real | Corregido: una vez, y se pasa a `pc.resultados` |
| 7 | `checklist_motor_e2e.ps1` dejaba `LIENZO_HOME`/`LIENZO_URL` en la consola que lo corre | Real si se corre a mano (el runner usa `pwsh -File`, otro proceso) | Corregido: se guardan y se restauran en el `finally` |
| 8 | Dos `except` con el mismo cuerpo | Real | Corregido: unidos |
| 9 | Con más de 50 cuestionadas no se decía «Se muestran X de Y» | Real | Corregido, con prueba UI `si hay más cuestionadas que las mostradas lo dice` |
| 10 | Tocar la tira con la memoria abierta no cambiaba de proyecto | No alcanzable: la memoria pone `#root` inerte y la tira queda debajo del modal | Igual se agregó `key={knowledgeTarget}` (remonta si cambia el destino); costo nulo |

Después de corregir: ruff limpio en las rutas de J, `tsc` y `eslint` con 0. El runner corrió los dos casos de
`pruebas-agenticas/checklist-motor-J.json` en OK: backend 250 pruebas, e2e 20 recorridos de navegador. Faltan
baseline y mutaciones aprobadas (decisión 3, coordinadora).

## Agregado de Ariel (12:11): la pestaña Aprendizaje

Segunda pasada de `code-review` (medium) sobre el agregado: `creencias.contexto_sugerido`, la ruta
`contexto-sugerido`, la carga al abrir en `Learning.tsx` y la tarjeta elegida en `App.tsx`.

| # | Hallazgo | Verificación | Resultado |
|---|---|---|---|
| 1 | La sugerencia tardía pisaba lo que la persona ya había escrito o consultado | Real. Rojo comprobado sacando el arreglo (spec `una sugerencia tardía no pisa…`) | Corregido: editar o consultar aborta la sugerencia y la descarta |
| 2 | `pickedAntes` quedaba pegado a una tarjeta vieja y ganaba al último panel | Real | Corregido: guarda sólo la elegida justo antes del último click |
| 3 | La guarda de proyecto no usaba `repo_key`: una tarjeta resuelta por remote se descartaba | Real. Rojo comprobado sin `repo_key` | Corregido: `resolver_proyecto(repo_key, cwd, pc)` |
| 4 | Una sesión sin encargo acá no caía al encargo en curso | Real. Rojo (`test_sugerido_sin_encargo_…`) | Corregido: si el de la sesión no aporta nada, vale el en curso |
| 5 | Una sesión desconocida bloqueaba esa caída | Real | Se resuelve con el 4 |
| 6 | `fuente` nombraba un encargo que no había aportado nada | Real | Corregido: sólo si aportó algún dato |
| 7 | Valores del encargo sin recortar ni cortar a 100 | Real. Rojo en la misma prueba | Corregido |
| 8 | `datos` no-dict daba 500 | Real (`_fila` deja el texto si el JSON no parsea) | Corregido con guarda; sin prueba propia |
| 9 | El id del nodo sesión dependía del remote actual | Real | Corregido: se busca por `clave_ingesta`, como `_ronda_de_sesion` |
| 10 | Doble lectura de la tarjeta, la segunda sin lock y sin copia | Real | Corregido: la local se copia bajo su lock; la espejada, afuera (el espejo tiene su lock) y copiada |

Después: ruff limpio en las rutas de J, `tsc` y `eslint` con 0. Runner: backend 255 pruebas OK y e2e OK
(24 recorridos de navegador sobre una instancia aislada, incluido un proyecto real sin creencias).