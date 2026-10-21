# Motor lógico y aprendizaje verificable

Actualización del alcance autorizada por Ariel el 19/10: implementar consulta opcional de ida y
vuelta y separar el motor en `D:/Apps/motor-logico`. Se usa JSON por proceso con límites;
el prototipo anterior sigue descartado. Python mantiene creencias y aprendizaje sin Prolog.
Se conserva debajo la propuesta inicial como historia, sin marcar tareas como completadas.

Verificación del 20/10: la interfaz real de Lienzo completó la consulta opcional a SWI-Prolog en
WSL. El proyecto tenía 0 creencias y 5 encargos sin clasificar; el contraste devolvió 0 creencias
analizadas y 0 diferencias con Python. Esto verifica el transporte, no la utilidad del aprendizaje.
Las 16 pruebas de `tests/test_prolog_learning.py` pasaron con el runtime real, incluida la
comparación diferencial. No se aprobaron baselines ni se cerraron etapas. El contrato 1 del
motor independiente sigue usando un proceso por consulta; el servicio persistente descrito
más abajo pertenece a la propuesta histórica y requiere comparación medida antes de adoptarlo.
Evidencia: [revisión del contraste ampliado](../../../review/2026-10-20/code-review-2026-10-20-prolog-contraste.md), que incluye las pruebas del contrato inicial.

Propuesta del 19 de octubre de 2026. Revisada por una CLI real de Claude Opus 5.5;
ajustada por Codex. Pendiente de decisión de Ariel.
Se planifica antes de implementar. El prototipo en `.temp/motor-logico` no es producto integrado.

## Decisión técnica propuesta tras la revisión

Primero cerrar el circuito útil de aprendizaje dentro de Lienzo. La integración Prolog se
mantiene como objetivo posterior: no se cablea el prototipo actual, cuya semántica no coincide
con el grafo real. No se habilitan dos autoridades sobre respaldos.

Hallazgos de Claude contrastados en código: `apoya` termina en evidencia sin estado;
`derivada_de` sale de regla y no de decisión; `aprendizaje._Respaldos` ya recorre
`motivada_por` y `contesta` con BFS, visita única y cadenas mínimas. Desactivar un vínculo
no equivale a cambiar el estado de una evidencia. El mapa de relaciones y transiciones reales
es un requisito previo a nuevas reglas. El prototipo queda descartado como implementación.

No se adoptan los umbrales sugeridos por Claude de 10 creencias y 30 encargos: carecen de una
calibración acordada. La condición para extraer el motor será demostrar una consulta útil
de inferencia compuesta que justifique el coste, con casos reales reproducibles y comparación
contra la implementación actual. No hace falta inventar un volumen mínimo para demostrarlo.

El motor separado solicitado por Ariel sigue siendo una restricción del destino final;
no obliga a construir hoy un supervisor, servicio persistente y segundo dominio. Evaluar
primero un lote SWI limitado en WSL contra un proceso persistente, midiendo arranque,
latencia y aislamiento. La decisión de transporte queda abierta.

## Resultado que buscamos

Lienzo debe poder explicar qué aprendió, por qué serviría para el trabajo actual, qué evidencia
lo sostiene y qué falta comprobar. El valor no es mostrar consultas Prolog: es evitar repetir
errores y poder revisar cada recomendación. El mismo motor debe servir a Chesstudia con otro
dominio de reglas y sin importar código, tablas ni nombres de Lienzo.

Ejemplo objetivo: antes de un refactor de una API, la sesión ve dos aprendizajes pertinentes,
un respaldo vencido y una pregunta concreta pendiente. «¿Por qué?» abre la cadena hasta la
prueba y el veredicto originales. Un control declarado nunca aparece como control ejecutado.
El punto de entrega es la preparación/envío del encargo, con contexto derivado del encargo;
Memoria permite investigar el detalle y corregirlo, sin exigir escribir el contexto a mano.

## Base medida y límites

El código actual ya conserva grafo, procedencia, veredictos humanos, contexto y vigencia.
`creencias.py` exige persona y evidencia para validar; `patrones_evidencia.py` distingue
declarado, ejecutado y verificado. `Knowledge.tsx` ofrece creencias, checklist y patrones.
La medición anterior de esta sesión encontró 0 creencias y 5 encargos sin clasificar: no es
un inventario permanente, se vuelve a medir al iniciar el piloto. Prolog no crea experiencia
donde faltan observaciones. El checklist Python sigue siendo la autoridad durante el piloto.

WSL2 Ubuntu 24.04 tiene SWI-Prolog 9.0.4 del repositorio de Ubuntu; se verificó su arranque.
La copia Windows fue desinstalada. Elegir una versión superior exige comprobar compatibilidad,
origen y reproducibilidad; no se necesita la rama de desarrollo para este alcance.

## Arquitectura del motor posterior (condicionada al piloto)

1. **Lienzo conserva la memoria y las decisiones.** SQLite y sus APIs actuales almacenan
   observaciones, pruebas, propuestas, veredictos e historial. No hay segunda base de creencias.
2. **Un adaptador produce un snapshot consistente.** Sólo un proyecto y sus dependencias
   activas; IDs estables, estados, contexto, vigencia y referencias. Una transacción de lectura
   evita mezclar revisiones. Declara lo ausente y lo truncado; nunca rellena datos inventados.
3. **Motor independiente en WSL.** Proceso persistente, reglas locales versionadas por dominio,
   HTTP sólo en loopback y consultas acotadas. Python pequeño + MQI es una opción; comparar
   con HTTP nativo de SWI antes de fijar transporte interno. La API pública es JSON y no depende
   de esa elección. No hay goals, rutas de archivos ni código Prolog en las peticiones.
4. **Reglas de dominio explícitas.** Un registro cerrado carga módulos instalados. El núcleo
   maneja contratos, límites, explicación y versión; aprendizaje y ajedrez tienen reglas propias.
5. **La app presenta resultados revisables.** Estados y motivos legibles; el detalle técnico
   queda en un desplegable de evidencia. Una inferencia no se transforma en veredicto humano.

No ejecutar Prolog por cada render, no arrancar WSL por cada consulta y no exponer MQI a la LAN.
Cada PC es dueña del motor que usa. El acceso desde otra PC pasa por Lienzo autenticado y su
protocolo firmado; no agrega un puerto Prolog público ni requiere Cloudflare. Tailscale no
sustituye autenticación. WSL caído se muestra «Motor no disponible», sin fingir cero hallazgos.

## Contrato v1 y semántica

`GET /health`: versión del motor, dominios/reglas cargados y estado operativo.
`POST /v1/infer`: dominio, versión de contrato, snapshot, contexto y momento explícito.
Respuesta: ID de consulta, hash/revisión de snapshot, versión de reglas, conclusiones y
justificaciones. Cada conclusión referencia una regla y los IDs concretos que la sostienen.

Estados de salida separados: aplicable, bloqueada, requiere revisión, información insuficiente
y fuera de contexto. Error de motor/timeout/entrada inválida es error de transporte o contrato,
nunca «sin conclusiones». No usar ausencia de prueba como falsedad. No sumar confianza por
cantidad de caminos que repiten la misma fuente. No inventar porcentajes de confianza.

El adaptador mapea expresamente `apoya`, `derivada_de`, estados y veredictos del grafo. Una
arista conserva dirección y significado: no todas las relaciones son dependencias lógicas.
No llamar «contradicción» a dos textos distintos: sólo detectar oposiciones estructuradas
de la misma proposición, contexto y vigencia, con esquema definido y validado.

Límites iniciales propuestos: 1 MiB, 1.000 nodos, 2.000 aristas, profundidad y conclusiones
acotadas, presupuesto de inferencias y 3 segundos. Si se excede alguno, resultado explícito
no concluyente; una muestra parcial nunca acredita aplicabilidad completa. Validar con datos
reales antes de fijar esos valores. No introducir memoización sin incluir fecha/vigencia,
revisión de grafo y versión de reglas en la clave.

## Experiencia visual objetivo

Entregar una vista «Aprendizaje» dentro de Memoria que reúna Creencias, Checklist y Patrones,
reemplazando esas tres entradas; no sumar una novena vista. En el encargo mostrar hasta tres
recomendaciones pertinentes con acceso al detalle:

- Qué se sabe para este contexto y por qué.
- Qué perdió respaldo, venció, depende de una fuente ausente o forma un ciclo.
- Qué aún es propuesta y qué dato puntual permitiría contrastarla.
- Qué cambió desde la consulta anterior, distinguiendo hechos de inferencias.

Cada tarjeta permite «Ver evidencia» y «¿Por qué no aplica?». Filtros de contexto se conservan
por proyecto; cambiar de proyecto cancela peticiones y descarta respuestas tardías. Se muestran
fecha, cobertura del snapshot y estado del motor. Sin datos se presenta un vacío honesto con
el dato faltante, sin fabricar ejemplos como resultados reales.
La señal «sirvió / no aplica / ya lo sabía» pertenece a la recomendación mostrada. No demuestra
ejecución ni causalidad. La UI de veredicto exige evidencia y el mismo permiso humano que la API;
proponer, dar feedback y validar son acciones diferentes. No aceptar un rol humano escrito por
un agente como autenticación suficiente: revisar ese límite antes de exponer nuevas escrituras.

El grafo es un detalle opcional de una conclusión, no una red enorme decorativa. Propuesta
visual: tarjeta de conclusión arriba y cadena corta de fuentes/veredicto debajo, navegable
con teclado. El texto principal habla de aprendizaje; Prolog y hashes quedan en el diagnóstico.

## Cómo se conecta con aprender

El ciclo es observación → patrón descriptivo → hipótesis → contraste → evidencia → veredicto
humano → aplicación contextual → nueva observación. El LLM puede formular hipótesis y explicar;
Prolog comprueba consecuencias de hechos estructurados. Las pruebas aportan observaciones;
la aprobación sigue el contrato existente. Ningún scheduler convierte recurrencia en verdad.

Primero cerrar captura y calidad de datos: contexto del encargo, controles declarados y
referencias de ejecución. Incorporar deduplicación/procedencia de observaciones antes de
contarlas como experimentos independientes. Más adelante, investigaciones propuestas con
criterio observable, coste y autorización separados; no ejecutar pruebas pagas por inferencia.

La sesión consulta al iniciar un encargo y ante cambios relevantes, con deduplicación por
revisión. No inyectar el mismo consejo en cada turno. Guardar qué recomendación se mostró
permite comparar después utilidad y ruido; no implica que se siguió ni que causó una mejora.

## Independencia y despliegue

Repositorio `motor-logico` separado, con contrato, reglas, pruebas, CLI de diagnóstico y
ejemplos sintéticos. API versionada y dominio sin imports de Lienzo. Chesstudia se valida con
un segundo dominio mínimo de ejemplo antes de llamar al núcleo reutilizable; nunca enviar
análisis de Stockfish como verdad estratégica sin su contexto de búsqueda.

Instalación idempotente en filesystem Linux; runtime y dependencias fijados y comprobables.
Para servicio persistente evaluar systemd de WSL disponible; si no, supervisor explícito con
estado, logs limitados, inicio/detención y diagnóstico. No modificar configuración global de
WSL sin necesidad ni asumir que Windows localhost reenvía en todas las PCs: probar el camino.

Sin secretos, conversación cruda ni claves en snapshots/logs. Persistir sólo referencias y
metadatos necesarios. Límites de concurrencia, tamaño, tiempo y vida del proceso hijo; aborto
limpia su consulta. Una caída no bloquea las CLI ni el tablero. No reiniciar sesiones de agentes.

## Entrega por etapas y criterios

- [ ] 1. Captura y mapa semántico. Medir inventario real; contexto requerido con opción explícita
  sin clasificar; producir evidencia desde resultados verificables con referencia, no desde prosa
  del agente. Mapear relaciones, estados y desactivación de vínculos.
- [ ] 2. Checklist explicado y punto de uso. Reutilizar el recorrido Python existente; motivos
  de no aplicabilidad, cadenas de respaldo caído y recomendaciones al preparar un encargo.
- [ ] 3. Vista unificada y circuito humano. Conservar fuentes y contexto; veredictos con evidencia,
  feedback diferenciado, cambio de proyecto, respuesta tardía y vacíos honestos.
- [ ] 4. Piloto medido. Consejos mostrados, relevantes, repetidos y descartados; incidentes y latencia.
  Informar tamaño de muestra, sesgos y carácter exploratorio; no prometer causalidad.
- [ ] 5. Prueba Prolog sobre el grafo real, con una consulta que justifique extracción. Comparar con
  checklist y apoyos rechazados; mismo snapshot, semántica, fecha y justificaciones. Medir lote WSL
  contra servicio; elegir con evidencia. No aplicar conclusiones como veredictos.
- [ ] 6. Extraer motor independiente si la prueba lo justifica. Contrato versionado, SWI real,
  aislamiento, límites y fallas explícitas; segundo consumidor mínimo para verificar independencia.

Recorrido obligatorio secuencial Explorer → Analyser → Designer → Executor → Detective;
tests con SWI real, contrato HTTP y navegación UI. Casos: evidencia retirada transitiva,
ciclo, fuente ausente, expiración exacta, contexto distinto, datos parciales, snapshot aislado,
inferencia limitada, caída y recuperación WSL, cambio de versión, dos proyectos, respuesta tardía.
Agregar `apoya` desactivado, creencia reemplazada, contexto parcial y paridad con `apoyos_rechazados`.
No aprobar baselines, mutaciones ni tareas automáticamente. Code review de cambios antes de entregar.

## Fuera de este plan

El actualizador visual/API de Lienzo es un frente independiente autorizado por Ariel.
No se introduce entrenamiento de modelos, motor probabilístico, edición de Prolog desde chat,
ejecución de comandos recomendados ni migración de la memoria a otra base.

## Revisión solicitada

Claude revisó el plan en la sesión `03edfd91-33dd-4805-a7ec-8afaf6c5a4bf`, por Lienzo,
con encargo y retorno registrados. Su informe original está en
`.temp/coordinacion/2026-10-19/revision-claude.md` (ignorado por Git). Se incorporaron sus
hallazgos semánticos, el punto de uso, la fusión de vistas y la captura previa. No se adoptó
su recomendación de abandonar la independencia pedida por Ariel ni sus umbrales arbitrarios.
Los conteos que Claude cita provienen de la medición anterior, no de una nueva consulta viva.
