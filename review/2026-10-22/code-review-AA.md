# Revisión del delta AA — 2026-10-22

Alcance pedido: archivos AA para 0.6.15; revisión estática en esta sesión, complementaria al recorrido agéntico. No audita cambios simultáneos de otros frentes ni dependencias no modificadas.

## Cambios revisados

Parser y proyección (prolog_programa), transporte (prolog_servicio), hechos medidos (prolog_hechos), evaluación temporal/derivación/reuso/generalización/graduación (prolog_ciclo), hook _Conexion.__exit__, integración creencias/checklist/contraste/research y pruebas. servicio.pl se revisa en motor-logico.

## Hallazgos corregidos

- T3: el deadline cubre stdin.write bloqueado, no sólo lectura. Caso de payload mayor al pipe y servidor que no lee: rojo y verde conservados en T3-rojo.log/T3-verde.log.
- T11: prueba conductual con directiva que intentaría crear un archivo. El motor rechaza el término y el sentinel no existe; no se usa una búsqueda de cadenas para probar seguridad.
- Hash SHA calculado sobre bytes publicados (CRLF) y encoding(octet) en SWI. Se detectó en integración real y corrigió.
- Windows: taskkill /T antes de matar el padre; prueba del hijo anidado verifica recolección. El PID SWI real también se comprueba terminado tras error/cierre.
- Inactividad: Timer cierra el motor sin exigir otra consulta.
- Revisión semántica: cambiar texto/regla/acción/contexto/metadatos exige veredicto de esa revisión. Revisión temporal identifica revisión y fecha del veredicto; evidencia y uso por destino tienen claves separadas.
- Premisas externas conservan proyecto/id/revisión; no se crean vínculos inválidos entre proyectos. Se verifica snapshot antes de publicar y caída transitiva.
- Las derivadas conservan cláusula visible validada, prueba, hechos y hash del programa; nacen propuestas.
- Metadatos completos: proyecto/tecnología/extensión/ruta/área/fase/trabajo/agente/modelo se emiten como hechos de la creencia; vacío desconocido no agrega comodines. Delta final verificado con 18 casos de hechos+ciclo y SWI real, tras rojo del helper ausente.
- Worker de exportación captura ruta de DB y log: no escribe accidentalmente en memoria real tras limpiar fixtures.
- Tests de transporte antiguo adaptados a servicio persistente conservando respuesta inválida deliberada y oráculo.

## Verificaciones y límites

Ruff sobre rutas propias: limpio. Parser restringido sin eval/consult/goals recibidos; protocolo y árbol de procesos acotados. Ninguna dependencia nueva de producción. SQLITE sigue siendo autoridad; manifest regenerable.

La política Chrome/>2 es conservadora aprobada por Ariel, no deducción de 4 frentes. Chrome/WSL/cuotas no medidos quedan desconocidos; no se producen hechos inventados.

La revisión no sustituye verificación en servidor desplegado: no se reinició 7321. UI regla_logica expresamente fuera del lote. Baselines/mutaciones requieren cierre de la coordinadora (decisión 3), aunque Ariel aprobó ejecutar las pruebas.

El primer runner detectó un caso que simulaba el transporte anterior. El ajuste conserva una respuesta inválida deliberada y comprueba que el transporte persistente no despierta WSL dos veces. Las salidas de verificación, incluidos fallos y posteriores corridas, quedan en .temp/resultados/2026-10-22-AA/runner/. El informe final de esa carpeta registra el veredicto medido, sin sustituirlo por esta revisión estática.

ESTADO: revisión estática del delta realizada; veredicto de ejecución en el informe AA.

## Regresiones detectadas por coordinadora, 22:25

Reproducidas sin editar tests: test_v5_el_checklist_de_otro_proyecto_suma_las_de_proceso_de_lienzo y test_cr2_la_vista_no_tapa_un_contexto_roto (40 passed, 2 failed). Correcciones en creencias.py y prolog_ciclo.py: excluir del reuso las creencias de alcance proyecto cuyo dueño es Lienzo; validar la forma del contexto guardado antes de diagnosticar una revisión semántica sin veredicto. Los demás cambios semánticos siguen exigiendo nuevo veredicto.

Verificación con AA_MOTOR_SIMULADO=1 y proveedor simulado conectado explícitamente: 42 pruebas de aprendizaje + 14 del ciclo, 56 passed. No se tocó ningún test para hacerlas pasar. Sin WSL ni SWI en esta verificación. Ruff check/format limpios. Evidencia: aprendizaje-rojo.log y aprendizaje-verde.log en resultados AA.

## Ajuste de precedencia Python/Prolog solicitado a las 22:48

La coordinadora detectó tres discrepancias en grafos aleatorios con SWI real: el chequeo de contexto roto se había adelantado indebidamente a respaldo retirado, respaldo caído y vencimiento. Esta corrección sustituye la precedencia descrita en el apartado anterior: _evaluar conserva el orden original y usa _veredicto_evaluable, compartido con los hechos de prolog_checklist. Un contexto roto permite diagnosticar la invalidez, pero no se vuelve aplicable ni oculta un respaldo retirado/vencido. Los cambios semánticos con contexto válido siguen exigiendo nuevo veredicto.

No se tocaron pruebas ni conocimiento.py. Verificación: tests/test_prolog_checklist.py y tests/test_prolog_learning.py, 37 passed con SWI real. Revalidación de las dos regresiones anteriores: 2 passed, 40 deselected con simulador explícito. Logs precedencia-real.log y precedencia-focal.log. Ruff check/format limpios; turno suite liberado y ambas coordinadoras avisadas.

