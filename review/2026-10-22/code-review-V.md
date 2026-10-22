# Revisión independiente V — próxima release

Fecha: 2026-10-22. Sesión: `pid-41040`. Revisión estática focalizada con el skill code-review.

Rango: `e9d8f53..cbe7ff15e140fcf2ffdedcc91f93f1baac13f685` (11 commits, 46 archivos en el inventario). Se priorizaron permisos de Kiro, identidad de procesos, auto-aprobar, captura/cambio de modo de Chrome y publicación/cancelación del investigador. También se revisó el delta de Q presente en disco: `creencias.py`, `conocimiento_api.py`, `contexto_ia.py`, `Learning.tsx` y sus contratos de pruebas. Q seguía sin commit: sus hallazgos describen esa versión, no una entrega final congelada.

**Resultado: 0 P1 confirmados; 5 P2.** Tres pertenecen al rango commiteado y dos al delta de Q. No implica ausencia de otros defectos. No se modificaron fuentes, pruebas, configuración, memoria de la aplicación ni baselines. No se reinició ningún servicio ni se hicieron escrituras Git.

## Hallazgos del rango commiteado

### V-1 — P2: cancelar puede publicar creencias y consumir su cursor igualmente

Ubicación: `lienzo/optimization_scheduler.py:497` y `:509`.

Después de `research.investigate`, se llama a `creencias_research.record` antes de comprobar `cancel_requested`. `record` crea evidencia, propone creencias, guarda el contraste y avanza el cursor. Luego la cola puede terminar como `cancelled`, aunque todos esos efectos ya ocurrieron.

Escenario: la CLI termina correctamente; la persona cancela justo antes del registro, o durante el contraste que puede despertar WSL. La cancelación se acepta, pero aparecen propuestas nuevas. El cursor marca sus fuentes como leídas y el trabajo cancelado no conserva sus resultados como una vuelta observada.

Evidencia ejecutada: se extrajo por AST el método real `_research_step` y se ejecutó con cola/adaptador/registro en memoria. La cola aceptó cancelar en el `change(pid=None)` del `finally`. Salida, código 0:

```text
cancelacion aceptada
record: publica propuestas y avanza cursor
resultado final: stopped
```

Prueba propuesta: extender `test_cancel_after_runner_result_wins_and_survives_restart` con `case.kind=creencias`, devolver un resultado exitoso con `lectura`, cancelar en ese mismo punto y exigir cero llamadas a `creencias_research.record`, cero creencias nuevas y cursor intacto. Agregar una barrera durante el contraste para definir el punto irreversible de publicación. Los tests existentes de `tests/test_optimization_cancel_races.py` usan un caso sin `kind=creencias`; no prueban esta bifurcación.

Corrección sugerida: establecer un orden explícito entre aceptación de cancelación y publicación, sin mantener el lock de cola durante WSL. Comprobar sólo al final no revierte efectos ya persistidos.

### V-2 — P2: el investigador llama «sostenida» a una propuesta sin evidencia independiente

Ubicación: `lienzo/research_creencias.py:665`–`:668`. Contrato consumido: `lienzo/prolog_contraste.py:533`–`:554`.

Se asigna `sostenida` cuando no hay observaciones negativas y Python/Prolog coinciden. No se exige `evidencia_independiente=humana` ni `listo_para_revision=True`. `concluyente` sólo acredita que las dos implementaciones coinciden; no acredita respaldo de la creencia.

Escenario: propuesta basada únicamente en la evidencia producida por el propio investigador, sin contradicción conocida. El motor devuelve `evidencia_independiente=ausente`, `listo_para_revision=False`, observaciones vacías y `concluyente=True`. Se persiste `resultado=sostenida`. Aunque no se promueva a vigente, la etiqueta de contraste comunica un respaldo que el motor no dio.

Evidencia ejecutada: extracción por AST de `_contrast`, con respuesta fija del contrato anterior. Código 0; resultado observado:

```text
resultado: sostenida
observaciones: []
evidencia_independiente: ausente
concluyente: True
```

Prueba propuesta: cubrir ausencia, independencia no verificada y evidencia humana. Las dos primeras no deben informar «sostenida». `fixed_contrast` de `tests/test_research_creencias.py:43` ya produce el escenario sin evidencia, pero `test_record_proposes_contrasted_beliefs_and_moves_the_cursor` exige «sostenida»: ese oráculo consolida el defecto en vez de detectarlo.

Corrección sugerida: distinguir «sin objeciones conocidas» de «sostenida», o dejar cuestionada/sin respaldo hasta contar con la evidencia independiente que exige el contrato del motor.

### V-3 — P2: el cambio por bloqueo puede elegir otra pestaña y otro perfil

Ubicación: `web/src/components/RemoteBrowser.tsx:249`, `:834`–`:837`.

La pestaña de destino se resuelve con el título de la ventana y el primer `tabs.find(t => t.title === prefer)`. El título no identifica una pestaña. Tampoco se comprueba el contexto/perfil de la ventana seleccionada.

Escenario: dos perfiles tienen abiertas pestañas con el mismo título, por ejemplo «GitHub» o «Nueva pestaña». Se está mirando la ventana del segundo perfil y se bloquea la PC. Si CDP devuelve primero la pestaña del primer perfil, el visor selecciona esa otra cuenta. El aviso afirma que pasó a la pestaña activa, pero la entrada del usuario puede ir a la pestaña equivocada. También puede ocurrir si el título activo cambió desde la última consulta de ventanas.

Confirmado por lectura del selector; no se bloqueó una PC real en esta revisión.

Prueba propuesta: ampliar `web/tests-ui/chrome-lock.spec.ts` con dos ventanas/perfiles, dos pestañas del mismo título y orden inverso al de la ventana elegida. Exigir el target/contexto de la ventana seleccionada. El fixture actual usa títulos distintos y una sola ventana, por lo que no detecta la ambigüedad.

Corrección sugerida: resolver identidad de ventana/target por CDP y preservar contexto; si no se puede resolver sin ambigüedad, pedir elección y no afirmar que se eligió la activa.

## Hallazgos del delta de Q, todavía sin commit

### V-4 — P2: abrir Aprendizaje oculta el estado del motor de las creencias

Ubicación: `lienzo/creencias.py:421` y `:487`; `web/src/components/Learning.tsx:233`.

`vista_proyecto` evalúa mediante Python con contexto `None`; `_item` no incluye `datos.contraste` ni una lectura actual del motor. `BeliefCard` muestra el estado de vigencia/veredicto y la cadena, pero no el resultado del contraste guardado por S. El motor sólo aparece en el filtro opcional o en el contraste de candidatos, no en la lectura inicial del proyecto.

Escenario: S dejó una propuesta con `contraste.resultado=contradice` o `cuestionada`. Al abrir Aprendizaje, se ve «sin veredicto» con «Aceptar», igual que para una propuesta sostenida. Una regla vigente cuestionada por el motor también puede aparecer como vigente en esa vista. Falta la distinción requerida por el agregado a J y la apertura de Aprendizaje con el estado según el motor.

Confirmado por lectura de extremo a extremo del payload y render; sin ejecución UI.

Prueba propuesta: sembrar dos propuestas idénticas salvo contraste `sostenida`/`contradice`, abrir desde el menú sin contexto y exigir ambos estados visibles con su procedencia/fecha. Añadir vigente cuestionada y motor no disponible. El fixture de `aprendizaje.spec.ts` valida vigencia, pero no exige esa distinción en las tarjetas iniciales.

Corrección sugerida: mostrar separadamente veredicto humano y contraste del motor; distinguir el contraste persistido de una consulta actual y conservar el error explícito si el motor no responde.

### V-5 — P2: «vale para todos» no incorpora la creencia al checklist de los demás proyectos

Ubicación: `lienzo/creencias.py:487`–`:500`; `lienzo/prolog_checklist.py:299`–`:304`; `web/src/components/Learning.tsx:375`.

Q incorpora las creencias `proceso_lienzo` al listado de cualquier proyecto, pero el filtro sigue consultando únicamente `/<proyecto>/checklist`. `_foto` sólo carga `creencias._leer(con, pid)`, cuya consulta limita `WHERE proyecto=?`. Las creencias del proceso viven en `lienzo`, así que quedan fuera del checklist del otro proyecto aunque estén validadas y coincida el contexto. El cambio de alcance promete «Ahora vale para todos los proyectos».

Escenario: validar en `lienzo` una regla de proceso para `tipo_trabajo=bugfix`; abrir otro proyecto sin creencias locales y consultar ese contexto. La regla aparece en el bloque de proceso de la apertura, pero «Aplica a lo que vas a hacer» devuelve cero elementos y no analiza esa regla con el motor.

Confirmado por el flujo de consultas y el filtro SQL; sin sembrar datos reales.

Prueba propuesta: fixture con dos proyectos, creencia vigente global y contexto coincidente. Exigir que el checklist combinado la incluya una sola vez, contrastada contra su proyecto dueño; el contexto distinto debe excluirla. La creencia propia de `lienzo` con alcance `proyecto` nunca debe filtrarse a otros proyectos.

Corrección sugerida: integrar explícitamente las creencias globales en la evaluación contextual, conservando proyecto dueño, pruebas y rutas de registro de uso/veredicto. Unir sólo las listas visibles no cumple el contrato.

## Estilo o simplificación — separado de los defectos

- `lienzo/autoaprobar.py` conserva en el docstring la afirmación general de que no aprueba confianza de carpetas; ahora hay una excepción explícita para Kiro dentro de `launch_roots`. Actualizar el texto para que describa la política real.
- `Kiro.permission_reason` todavía menciona únicamente la opción `(a)` si no encuentra una opción válida, aunque la selección principal autorizada pasó a `(f)`. Es diagnóstico desactualizado; no se contó como defecto de autorización.

## Recorrido de pruebas agénticas y límites

Se leyeron el skill y los cinco roles. Trabajo secuencial en `pid-41040`, sin agentes adicionales. El encargo V autoriza sólo lectura y este informe: no se crearon casos ejecutables, archivos de roles ni configuración nueva.

1. **Explorer:** inventario del rango y reconstrucción estática de los flujos de permiso, cambio por bloqueo, investigación/publicación y apertura/filtro de Aprendizaje. No hubo observación en navegador: los flujos UI son inferidos del código.
2. **Analyser:** contraste contra los requisitos de V, S, P y el agregado a J/Q; revisión de contratos de cancelación y de `prolog_contraste`. Sin aceptación de requisitos ni baselines.
3. **Designer:** casos de regresión propuestos en cada hallazgo; reutilizados como referencia los casos de carreras, creencias de fondo, Chrome-lock y Aprendizaje. No se editaron ni aprobaron pruebas.
4. **Executor:** dos reproducciones aisladas en memoria con `py -3.14 -c`, extrayendo las funciones reales por AST y sustituyendo únicamente dependencias externas. Ambas salieron con código 0 y mostraron los resultados consignados. No importaron el server ni escribieron memoria. No son una suite de aceptación. No se ejecutó runner, mutación, suite global ni UI; una mutación violaría el alcance de sólo lectura.
5. **Detective:** V-1 y V-2 reproducidos con dependencias fijas; V-3, V-4 y V-5 confirmados por lectura estática, con regresión propuesta y sin verificación en uso real. No se emitió PASS de compuerta ni se fijaron baselines.

Seguridad revisada: la confianza de Kiro usa `_cwd_allowed` físico y vuelve a comprobar opciones antes de responder; `same_dialog` compara carpeta y pregunta antes de teclear. No se halló un bypass concreto en esos caminos. La opción `(f)` de subagentes es una decisión explícita de Ariel, no se reportó como aprobación excesiva por sí misma.

Queda fuera de la evidencia de esta revisión: bloqueo real, latencia entre PCs, precisión visual de parches en Chrome real, credenciales/cuotas y una nueva llamada paga a IA. Tampoco se certifica el delta mutable de Q como entrega final.

Archivo propio exacto: `review/2026-10-22/code-review-V.md`.

ESTADO: revisión lista
