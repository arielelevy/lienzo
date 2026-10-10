# Requisitos: evaluador de performance por harness

## Introducción

Ariel reparte trabajo entre claude, codex, pi y coda, con modelos distintos (de frontera y on-premise),
y hoy no tiene cómo comparar lo que rinde cada uno. Quiere, por agente y modelo, **el resultado contra
el gasto y el tiempo**, acumulado entre rondas, para decidir a quién mandarle qué.

El lienzo ya tiene casi todo: las transcripciones (con el uso de tokens por turno), las consultas (cada
respuesta con su hora, y en la vuelta 2 qué acepta, sostiene o refuta cada investigador del otro) y el
conocimiento por proyecto (encargos con enviado y entregado, veredictos de la coordinadora sobre los
hallazgos). Falta juntarlo, puntuarlo con reglas fijas y mostrarlo en una tabla.

Lo que se mide va antes que la opinión de otro modelo; lo que se estima se marca como estimado.

Unidades que se evalúan: una **participación en una consulta** (un investigador en una consulta) y una
**ejecución de un encargo** (la tarjeta que tomó un encargo).

Lo que ya hay, verificado el 2026-10-10:

| Fuente | Qué trae |
|---|---|
| Claude (`transcripts.py`, turno `usage`) | input, output, cache_read, cache_creation por respuesta |
| Codex (`token_count`) | `total_token_usage` acumulado de la sesión |
| Pi (sesión en `~/.pi/agent/sessions`) | tokens y `cost.total` en dólares por respuesta, calculado por Pi |
| coda (`~/.coda/coda.db`, tabla `usage`) | input, output, reasoning, cache_read, cache_write, `cost_micro` (0 en on-premise) |
| `consulta.json` | por vuelta e investigador: texto, `ts`, agente, modelo; `creada`; `pendientes[sid].enviado` sólo mientras espera (se borra al tomar la respuesta) |
| `conocimiento` | estados del encargo (`pendiente → enviado → entregado`) con fecha en `cambio`; hallazgos `propuesto → confirmado / rechazado / corregido` |

## Requisitos

### Requisito 1: Gasto de una unidad

**Historia:** Como Ariel, quiero saber cuántos tokens y cuántos dólares gastó cada agente en cada
consulta o encargo, para comparar el costo de cada harness y modelo.

#### Criterios de aceptación

1.1. CUANDO se evalúa una unidad ENTONCES el sistema DEBE sumar, de la transcripción de esa tarjeta,
los tokens de los turnos que caen entre el inicio y el fin de la unidad, separados en entrada, salida,
lectura de caché y escritura de caché (y razonamiento si la fuente lo da).

1.2. Para Codex, cuyo contador es acumulado, el sistema DEBE tomar la diferencia entre el último
`token_count` dentro de la ventana y el último anterior a ella.

1.3. Para coda, el sistema DEBE leer la tabla `usage` de `~/.coda/coda.db` de la sesión de coda de la
tarjeta, en la misma ventana (`created_at`), en sólo lectura.

1.4. CUANDO el modelo tiene precio en la tabla de precios ENTONCES el sistema DEBE calcular los dólares
con ese precio por tipo de token. SI la fuente trae su propio costo (Pi, coda con `cost_micro > 0`)
ENTONCES el sistema DEBE mostrarlo y usarlo cuando el modelo no tiene precio en la tabla.

1.5. SI no hay precio ni costo de la fuente ENTONCES el sistema DEBE dejar los dólares vacíos y mostrar
los tokens; nunca DEBE inventar un precio ni suponer cero.

1.6. SI la transcripción ya no existe o no se puede leer ENTONCES la unidad DEBE quedar con gasto
«sin dato», sin frenar la evaluación de las demás.

### Requisito 2: Tiempo de una unidad

**Historia:** Como Ariel, quiero los minutos que tardó cada agente, para ver quién es lento y quién rápido.

#### Criterios de aceptación

2.1. En una consulta, el tiempo de un investigador DEBE ser la suma, por vuelta, de la espera entre el
envío de su pedido y la hora de su respuesta.

2.2. CUANDO la consulta abre una vuelta ENTONCES el sistema DEBE guardar la hora de envío junto a la
respuesta de esa vuelta (hoy se pierde al tomarla), para que el tiempo quede medido.

2.3. SI una consulta no tiene guardada la hora de envío (las anteriores a este cambio, como
`c-20261010-a841ea`) ENTONCES el sistema DEBE estimarla (vuelta 1: `creada`; vuelta n: la última
respuesta de la vuelta n−1) y marcar el tiempo como estimado.

2.4. En un encargo, el tiempo DEBE ser de `enviado` a `entregado` según las fechas de `cambio`; SI no
llegó a entregado ENTONCES la unidad DEBE quedar abierta, sin minutos.

### Requisito 3: Resultado de una participación en una consulta

**Historia:** Como Ariel, quiero un puntaje de lo que aportó cada investigador que salga de lo que el
otro le aceptó o le refutó, no de la opinión de un juez.

#### Criterios de aceptación

3.1. CUANDO hay vuelta 2 ENTONCES el sistema DEBE leer las secciones «Acepto», «Sostengo» y «Refuto» de
cada respuesta y contar sus ítems (viñetas o numerados de primer nivel).

3.2. Los ítems que X acepta o refuta DEBEN contar para el otro investigador (son afirmaciones suyas);
los que X sostiene, para X. Con tres investigadores, un ítem que nombra a uno se le acredita a ése; si
no nombra a nadie, se reparte y se marca como estimado.

3.3. SI un investigador escribe la marca de sin cambios en la vuelta 2 ENTONCES el sistema DEBE contarlo
como que no se retracta; SI acepta algo que contradice su vuelta 1 ENTONCES DEBE contarse como
retractación propia (que no resta, pero se muestra).

3.4. CUANDO la consulta tiene síntesis ENTONCES el sistema DEBE registrar, por investigador, si su
posición quedó en «Acuerdos», en «Desacuerdos» o en la «Conclusión recomendada», y si en la revisión
contestó que la síntesis lo representa o la corrigió.

3.5. El puntaje DEBE salir de una fórmula fija escrita en el diseño, con los conteos crudos a la vista
para poder recalcularlo.

3.6. SI la respuesta no tiene las secciones (formato libre) ENTONCES el sistema DEBE dejar el resultado
«sin señal» para esa vuelta, no cero.

### Requisito 4: Resultado de un encargo

**Historia:** Como Ariel, quiero que el resultado de un encargo salga de los veredictos de la
coordinadora y de las pruebas, para medir lo que de verdad quedó.

#### Criterios de aceptación

4.1. CUANDO un encargo tiene informes con hallazgos ENTONCES el sistema DEBE contar sus hallazgos
confirmados, corregidos, rechazados y sin veredicto, con el estado vigente en `conocimiento`.

4.2. CUANDO el informe o sus nodos registran pruebas que pasan o fallan ENTONCES el sistema DEBE
contarlas; SI no hay registro de pruebas ENTONCES el resultado DEBE salir sólo de los veredictos y
decirlo.

4.3. Un encargo `sin_entrega` DEBE contar como resultado cero con gasto y tiempo medidos.

### Requisito 5: Registro acumulado

**Historia:** Como Ariel, quiero que lo medido no se pierda cuando la tarjeta se cierra o se borra la
transcripción, para acumular entre rondas.

#### Criterios de aceptación

5.1. CUANDO una consulta se cierra o un encargo pasa a `entregado` o `sin_entrega` ENTONCES el sistema
DEBE evaluar sus unidades y guardar el resultado (conteos, tokens, dólares, minutos, qué es medido y qué
estimado) en un registro persistente.

5.2. El registro DEBE ser idempotente: evaluar dos veces la misma unidad la reemplaza, no la duplica.

5.3. CUANDO se pide reevaluar (por ejemplo, tras cambiar la tabla de precios) ENTONCES el sistema DEBE
recalcular los dólares de todas las unidades con los tokens ya guardados, sin volver a leer
transcripciones.

5.4. El sistema DEBE poder evaluar a mano una consulta o un encargo ya cerrados (o en curso, marcados
como parciales), para cargar lo anterior a esta funcionalidad.

5.5. La evaluación NO DEBE escribir en la carpeta de la consulta ni en las transcripciones.

### Requisito 6: Vista por agente y modelo

**Historia:** Como Ariel, quiero una tabla por agente y modelo con resultado, costo, minutos y resultado
sobre gasto, para elegir.

#### Criterios de aceptación

6.1. CUANDO se pide la vista ENTONCES el sistema DEBE mostrar una fila por (agente, modelo) con:
cantidad de unidades, resultado acumulado, tokens, dólares (o «sin precio»), minutos, resultado por
dólar y resultado por hora.

6.2. Cada número estimado DEBE verse distinto de uno medido (marca y explicación al pasar el mouse).

6.3. CUANDO se elige una fila ENTONCES el sistema DEBE mostrar sus unidades, con el enlace a la consulta
o al encargo y los conteos crudos.

6.4. El sistema DEBE exponer lo mismo por API (`GET`) en JSON, filtrable por proyecto y por fechas.

### Requisito 7: Tabla de precios

**Historia:** Como Ariel, quiero mantener a mano los precios por modelo, en un solo lugar.

#### Criterios de aceptación

7.1. Los precios DEBEN vivir en un archivo editable a mano (dólares por millón de tokens de entrada,
salida, lectura y escritura de caché), con la fecha de cada precio.

7.2. SI el archivo falta o tiene un error ENTONCES el sistema DEBE seguir sin dólares y avisar el error
en la vista, sin caerse.

### Requisito 8: Primer caso real

8.1. El sistema DEBE evaluar `c-20261010-a841ea` (Claude Opus 5.5 contra Pi gpt-6.1-sol) leyendo
`~/.lienzo/consultas/c-20261010-a841ea/` sin modificarla, y la vista DEBE mostrar esas dos filas con
sus conteos de la vuelta 2 y sus tiempos marcados como estimados.
