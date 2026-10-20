# Aprendizaje y mejora de Lienzo

Contrato consolidado el 2026-10-16. Integra el evaluador de harness y las decisiones de producto
posteriores. [Producto](PRODUCTO.md) define la intención; esta página define los límites técnicos.
Los registros fechados del piloto se conservan como evidencia histórica, no como estado actual.

## Alcance

### Consulta opcional a Prolog

En Aprendizaje, **Contrastar con Prolog** envía un snapshot de IDs, estados, relaciones y contexto
al repo independiente `D:/Apps/motor-logico`. No envía conversaciones ni textos de creencias.
Recibe conclusiones justificadas y muestra diferencias con Python sobre el mismo snapshot.
No modifica creencias, veredictos ni aprendizaje. Python conserva la autoridad actual.
Si falta SWI-Prolog, WSL o el repo, sólo falla esa consulta: el resto sigue disponible.
No se invoca al iniciar ni al consultar el aprendizaje normal. No requiere reinstalaciones.

Por defecto busca el repo hermano `motor-logico/main.pl` (remoto privado
`arielelevy/motor-logico`, se clona junto a Lienzo). `LIENZO_PROLOG_ENGINE` permite fijar
otra ruta absoluta al archivo. Windows usa la distro WSL `Ubuntu` existente; Linux usa `swipl`.
Sin el repo, la consulta responde «Motor lógico no encontrado» sin lanzar ningún proceso.
Transporte JSON por proceso, contrato 1/reglas 1; máximo 1000 nodos, 2000 vínculos y 1 MiB.
No trunca el grafo: rechaza la consulta si excede límites. No hay integración ajedrecística aún.
Cada repo tiene actualizaciones independientes; actualizar Lienzo no instala ni actualiza el motor.

Analizar el flujo completo y las capacidades de Lienzo: herramientas, contexto, memoria,
planificación, arquitectura, construcción, coordinación, olas, pruebas, review, auditoría y documentación.
Distinguir problemas observados, causas investigadas, alternativas y beneficios demostrados.
La brevedad o una menor cantidad de llamadas no son un oráculo de calidad.

## Arquitectura existente

| Componente | Responsabilidad |
|---|---|
| `agent_evaluation.py` | Muestra de turnos, herramientas, errores, duraciones y consumo informado |
| `agent_suggestions.py` | Sugerencias y juicio sobre una muestra identificada |
| `jev.py` | Cliente OpenRouter Decisions y validación de respuesta/consumo |
| `jev_credentials.py` | Credenciales privadas; sin exposición al navegador |
| `optimization_activity.py` | Señales de actividad, recursos, sesiones y permisos |
| `optimization_queue.py` | Cola operacional persistente por PC |
| `optimization_scheduler.py` | Trabajo oportunista y piloto explícito |
| `optimization_memory.py` | Hipótesis y evidencias en la memoria existente |
| `optimizacion_trabajo.py` | Métricas de coordinación sobre capturas |
| `optimization_experiment.py` | Comparación de contratos locales RTK OFF/ON |
| `optimization_budget.py`, `optimization_cost.py` | Ledger, cotización y controles de gasto; `cli_maximum` |
| `optimization_research.py` | Investigador CLI: selección, paquete, esquema, validación, memoria, adaptadores |
| `optimization_research_policy.py` | Modos, autorización y techos del investigador |
| `optimization_research_quota.py` | Cuota de la suscripción Codex leída en vivo, sin inferencia |
| `optimization_research_runner.py` | Proceso propio cancelable, con plazo y sin tocar procesos ajenos |

Preferencias e instrucciones al lanzar están en `agent_improvements.py`, `launch.py` y
`tools/`. La UI está en `AgentImprovements.tsx` y `OptimizationScheduler.tsx`.

## Contrato de observación

Identificar proyecto, sesión, PC, agente, modelo, versión y ventana cuando estén disponibles.
Separar resultados conocidos, faltantes y errores explícitos. No convertir ausencias en éxito o cero.
Informar truncamiento y cobertura. No sumar contadores acumulados como si fueran consumo por turno.
Mantener créditos, tokens, bytes y dinero como unidades distintas.
Una respuesta tardía no puede reemplazar los datos de otra sesión; los datos remotos se consultan
en la PC dueña, sin fabricar una evaluación local cuando el peer falla.

## Jev

Se conserva como filtro económico; la CLI de investigación propuesta lo complementa.
El cliente existente usa `https://openrouter.ai/api/alpha/decisions`, modelo
`typesafe/jev-1.13`, proveedor ZDR/sin recolección, timeout y sin reintentos automáticos.
La muestra de métricas/referencias es revisable y no lleva prompts, argumentos, resultados de
herramientas ni credenciales de la sesión. La clave viaja únicamente en autorización del transporte.

La respuesta requiere opciones válidas, probabilidades finitas dentro de rango, suma coherente,
modelo, identificador y consumo válido. La confianza del modelo no mide acierto.
El modelo puede proponer ninguna o datos insuficientes. No instala ni aplica sus decisiones.

## Presupuesto y consentimiento

Una estimación no habilita consumo. El transporte valida condiciones, cotiza, reserva y concilia.
La cotización implementada reserva hasta USD 0.002688 cuando acredita las condiciones del proveedor;
no se asume válida sin revalidarla. Los costos inciertos conservan responsabilidad pendiente.
Un exceso de cota, cargo sin conciliación o adaptador sin garantía bloquea según el ledger.
Las guardias no deben poder saltarse usando una ruta de UI o un script alternativo.

La autorización histórica del 2026-10-12 fue reducida de USD 5 a USD 2 totales, incluidos costos
previos; no es USD 2 por proyecto o PC ni autorización nueva de esta conversación.
La política operacional sigue en `docs/specs/evaluador-harness/budget-policy.json`.
Sus documentos de autorización y piloto se conservan en esa carpeta por su valor de evidencia.
No se cambia el límite de una clave compartida para simular un presupuesto propio.

## Ejecución oportunista existente

El scheduler requiere 180 s de quietud, dos muestras aptas, CPU de 35 % o menos, al menos 1.5 GB
libres y ausencia de agentes ocupados o permisos vigentes. Una señal desconocida bloquea.
Los permisos expirados o de sesiones muertas permanecen en el historial sin bloquear.
La cola admite hasta 100 trabajos, deduplica versiones de fuentes y tiene cooldown de 120 s.
El análisis local toma hasta 30 incidentes recientes por proyecto; sus propias propuestas no
producen otra versión de incidentes. El análisis de coordinación mira 72 h, a lo sumo cada hora.

Los límites SQL y por tick son cooperativos; no se prometen plazos absolutos ante bloqueo del SO.
La pausa conserva resultados ya confirmados. Una ejecución interrumpida requiere revisión.
Los GET de estado no deben activar una cola, crear un ledger ni reparar la identidad.

El piloto Jev es una excepción explícita a la ausencia de inferencia: cuando está habilitado,
respeta ventana, topes, presupuesto y señales. El investigador CLI corre bajo su propia política (abajo).

## Memoria, creencias y checklist

Reutilizar `conocimiento.sqlite`, una base por instancia con separación por proyecto.
La cola y el ledger son estado operacional, no otra memoria semántica.
Conservar fuentes, contexto, vigencia, resultado, excepciones y trazabilidad de cada hipótesis.
El circuito objetivo es observación → hipótesis → experimento → evidencia → creencia → regla/checklist.
Una observación no prueba causalidad; una sugerencia no se promueve por confianza del modelo.
El checklist debe ser breve, contextual y excluir apoyos retirados, refutaciones y vencimientos.

`creencias.py` modela creencias como decisiones y deriva el checklist como vista con veredicto humano,
sin crear reglas duplicadas que puedan quedar vigentes al refutar o vencer la creencia.
El borrador `patrones_desarrollo.py` agrupa encargos con etiquetas explícitas de trabajo y controles.
No acredita una inferencia completa de patrones ni que los controles declarados se ejecutaran.

Primer corte del aprendizaje real (2026-10-19), sin motor nuevo:
- Todo encargo de la API declara `tipo_trabajo` (`sin_clasificar` se cuenta aparte).
- El checklist explica por qué una creencia no aplica. `respaldo_caido` reutiliza las cadenas de
  `aprendizaje._Respaldos`: las fuentes de una creencia se vinculan con `motivada_por` al proponerla.
- Al crear un encargo se devuelven hasta 3 aprendizajes aplicables y se registra que se mostraron.
- El uso declarado (`sirvio`, `no_aplico`, `ya_sabido`) sólo marca `revisar`; nunca cambia el estado.
- La evidencia `control_desarrollo` del bloque de un informe queda atada al encargo; el frente no
  puede declararla `verificada`.
- Memoria → Aprendizaje reemplaza Creencias, Checklist y Patrones, con veredicto y uso firmados por
  una persona. El experimento Prolog del mismo día está en `.temp/motor-logico/experimento-2026-10-19/`.
El estado de validación de esos borradores está en [Producto](PRODUCTO.md#estado-al-consolidar).

## Investigador CLI en segundo plano

Implementado el 2026-10-16 (frente A). Complementa a Jev: Jev filtra y prioriza, la CLI investiga.
Recorrido: selección → CLI de sólo lectura → respuesta JSON validada → evidencia → propuesta visible.

**Selección.** Lee la memoria sin crearla: primero evidencias del piloto Jev (si Jev eligió `ninguna`
o `datos_insuficientes`, el caso no se investiga), luego hipótesis propuestas, hallazgos propuestos e
incidentes observados. Las propias propuestas del investigador no vuelven a seleccionarse.
Cada caso tiene un área principal entre 16 (herramientas, contexto, memoria, arquitectura,
planificación, tareas, construcción, olas, coordinación, esperas, pruebas, review, auditoría,
retrabajo, documentación, capacidades ausentes) y siempre pregunta por capacidades ausentes.
La clave del caso combina versión del prompt, proyecto, área y fuentes; no se repite en el historial.

**Paquete y respuesta.** El paquete lleva texto y datos recortados de las fuentes, sin claves con nombres
de secretos. Valores con formato de credencial conocido (lista cerrada en `optimization_research.SENSITIVE`)
se redactan en el paquete, en la respuesta antes de guardarla y en los errores, con conteo por tipo;
un secreto con otro formato pasa. El investigador recibe la misma base agéntica que las sesiones
(las preferencias del panel de Mejoras, como respuestas breves y RTK), y queda registrado cuál se aplicó.
El prompt declara el caso como dato, no instrucciones. La respuesta sigue un esquema estricto:
problema, causas (observado/inferido, confianza), propuestas (problema, alcance, alternativa,
comprobación, riesgo), capacidades ausentes, limitaciones obligatorias, lo no medido y fuentes.
Sólo valen como fuente ids de memoria del paquete, sesiones citadas como trazas y rutas relativas
existentes del repo; toda cita debe estar declarada. Una respuesta inválida es un fallo con evidencia.

**Memoria.** Una evidencia `investigacion_cli` por caso y una `decision` en estado `propuesta` por
propuesta, vinculadas con `apoya` y `motivada_por`; requieren veredicto. Nada cambia de estado solo.
Los fallos y cancelaciones dejan evidencia `investigacion_cli_fallida`, sin reintento automático.

**Política y consumo.** Sólo el modo `read_only` puede habilitarse; experimentos aislados y aplicar
cambios quedan bloqueados. `optimization_cost.cli_maximum` exige una cota de USD 0 verificada con
fundamento antes de enviar; sin ella, bloqueado. No hay ledger CLI para montos mayores que cero.

- Codex usa la suscripción. Ariel lo autorizó el 2026-10-16 a correr mientras quede al menos 20 % de la
  ventana semanal (uso <= 80 %). La cuota se lee en vivo (`codex app-server`, `account/rateLimits/read`)
  antes de cada inicio y cada minuto de ejecución; bloquea con créditos cobrables, control de gasto o
  límite alcanzado, o si la lectura falla. Es cuota de la cuenta: incluye el uso de las dos PCs.
- El otro adaptador sólo aplica a proyectos de una regla local fuera de Git
  (`lienzo/extensiones/investigador-reglas.json`) y exige autorización firmada.
- `~/.lienzo/research-authorization.json` (versión 1, firma `persona:<nombre>`, vencimiento, topes y
  `presupuesto_usd` "0") restringe a Codex y es obligatorio para el otro adaptador. Si es inválido, bloquea.
- Techos del código: 900 s por ejecución, 6 ejecuciones en 24 h móviles, 20 MB de salida (stdout +
  stderr, contados durante la ejecución: al pasarlos se mata el árbol propio) y 2 inicios por caso.
  Una autorización puede bajarlos, no subirlos. La respuesta de Codex (`result.json`) no puede pasar
  200 kB. La salida cruda completa de cada intento queda en `~/.lienzo/research/<caso>/`, y el uso
  semanal se registra antes y después de cada ejecución.

Codex corre `exec --sandbox read-only --ephemeral` con `approval_policy="never"`, `--disable hooks`
y `notify=[]`, salida con `--output-schema`. El sandbox de sólo lectura no impide leer archivos fuera
del repo; el caso viaja al servicio de OpenAI. La respuesta se valida antes de tocar la memoria.

**Ejecución.** Un caso a la vez dentro del tick del scheduler; el tick queda ocupado mientras corre.
Actividad del usuario, pausa, cancelación, memoria por debajo de la reserva o cuota excedida matan
el árbol del proceso propio y pausan o cancelan conservando la última salida. La CPU no se mide durante
la ejecución porque incluye al propio proceso. Una política bloqueada pospone 30 min sin lanzar nada.
Tras reiniciar el server, un trabajo `running` pasa a revisión y su PID registrado nunca se mata.
El descubrimiento automático elige a lo sumo un caso por proyecto cada 30 min y sólo si la política lo habilita.

Ariel no respondió todavía qué experimentos puede ejecutar solo en un entorno aislado.

Para comparar alternativas, fijar tarea, entradas, código/hash, modelo, versión, permisos y oráculo.
Usar copias aisladas y condiciones comparables, registrar fallos y esperas, y comprobar calidad
antes de evaluar tiempo o costo. Una comparación inválida se conserva como tal.
El piloto propuesto de brief/RTK distingue cuatro perfiles 00/10/01/11 para separar efectos;
sigue siendo una propuesta, no ocho ejecuciones realizadas ni un ahorro demostrado.

El ensayo RTK existente corre contratos locales fijos en dos perfiles, con fuentes congeladas,
límite de proceso y pausa entre perfiles. No mide calidad de coding agents ni ahorro de tokens.
Nunca mata procesos de agentes ajenos para conseguir quietud.

## Controles de calidad y documentación

Registrar por separado pruebas ejecutadas y oráculos, review local de Claude, auditoría mediante
skill, hallazgos, correcciones verificadas y pendientes. Su mera declaración no prueba ejecución.
Mantener Explorer → Analyser → Designer → Executor → Detective donde lo exigen las instrucciones.
Ni el build ni pytest solos sustituyen ese recorrido. La compuerta conserva su veredicto real;
no aprobar baselines, mutaciones o tareas por decisión del evaluador.

Anatomy mejora explicaciones visuales y documentación. No sustituye esos controles.
RTK se invoca explícitamente, conserva códigos y permite recuperar diagnósticos originales.
El perfil breve conserva idioma, información necesaria, números, rutas, comandos y errores.
No se instala el proxy de Caveman ni se comprimen archivos.

## Investigación de comunidad

Buscar herramientas o integraciones relacionadas con necesidades observadas, no instalar por moda.
Guardar fuentes, fecha, problema, alternativas, costo, permisos y mantenimiento de cada propuesta.
Ariel decide adopción y activación. No hay periodicidad ni presupuesto nuevos aprobados todavía.
Los plugins y formas de trabajo se evalúan por su capacidad real, tengan tools o no.

## API y comprobaciones

Las rutas existentes incluyen `GET/PUT /agent-improvements`,
`GET /sessions/<sid>/improvements`, `POST /sessions/<sid>/improvements/jev`,
`GET/PUT /agent-improvements/scheduler` y `GET /trabajo/<proyecto>`.
Las escrituras mantienen autenticación, CSRF y propiedad de la sesión/proyecto.
`PUT /agent-improvements/scheduler` (sólo local) admite además `research_check` y `enqueue_research`
con `project`, y `cancel_research` con `job`. El estado expone `research.last_evaluation`; un GET
no lee la cuota. Creencias: `GET/POST /conocimiento/<p>/creencias`, `POST .../creencias/<id>/veredicto`,
`POST .../creencias/<id>/uso` y `GET .../checklist`.

La verificación debe cubrir muestras parciales, errores y consumo ausentes, aislamiento entre
sesiones/proyectos/PCs, respuestas tardías, concurrencia, pausa, recuperación y guardias de consumo.
Conservar originales de logs y códigos de salida. Los casos con fixtures y las mediciones reales
se informan separados. Una llamada sintética Jev verifica conectividad, no calidad del clasificador.

## Evidencia histórica

En `docs/specs/evaluador-harness/` se conservan `verification.md`, `acceptance-final.md`,
`piloto48h.md` y `budget-authorization.md`, todos fechados y con estados de aquella ronda.
Las propuestas y requisitos intermedios se consolidaron aquí. Sus originales quedan en Git.
Las reglas de aceptación de la configuración agéntica apuntan a este contrato cuando corresponda.
