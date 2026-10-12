# Requisitos: evaluador de harness

## Introducción

Ariel pidió continuar con el evaluador y usar la información para sugerir mejoras.
La primera versión analiza las sesiones reales que Lienzo ya lee, sin lanzar encargos
comparativos ni consumir llamadas adicionales a modelos. Cada sugerencia debe mostrar
la observación que la motivó. Las métricas operativas no acreditan por sí solas que una
respuesta sea correcta ni que un harness sea mejor que otro.

## Requisitos

### 1. Evaluar con datos observados

**Historia:** Como usuario quiero ver qué ocurrió en cada sesión para detectar problemas concretos.

1. CUANDO se solicita una evaluación ENTONCES el sistema DEBE identificar sesión,
   proyecto, PC, harness, modelo y versión cuando estén disponibles.
2. CUANDO lee turnos ENTONCES DEBE contar turnos abiertos/cerrados, llamadas de
   herramientas, resultados conocidos, resultados faltantes y errores explícitos.
3. SI no hay transcript, está truncado o solo se leyó una ventana ENTONCES DEBE
   indicar el alcance y DEBE evitar presentar la muestra como el historial completo.
4. SI falta un dato ENTONCES DEBE mostrarlo como desconocido, sin convertirlo en cero.

### 2. Medir eficiencia sin inventar comparabilidad

**Historia:** Como usuario quiero identificar gasto y demoras con una base verificable.

1. CUANDO hay inicio y fin válidos de un turno cerrado ENTONCES DEBE medir su duración;
   los turnos abiertos o con fechas inválidas DEBEN quedar fuera de ese cálculo.
2. SI la semántica del uso permite normalizar tokens ENTONCES DEBE informar los tokens
   y su cobertura; los contadores acumulados NO DEBEN sumarse como consumo por turno.
3. SI una fuente solo informa créditos u otra unidad ENTONCES DEBE mantener esa unidad
   separada; NO DEBE inventar un costo monetario ni convertirlo a tokens.
4. CUANDO muestra una tasa de errores ENTONCES DEBE mostrar numerador, denominador y
   resultados faltantes, para que el usuario pueda interpretar la cifra.

### 3. Sugerir mejoras con evidencia

**Historia:** Como usuario quiero convertir problemas observados en propuestas útiles.

1. CUANDO propone una mejora ENTONCES DEBE mostrar el problema, la evidencia
   (sesión, turno y herramienta cuando aplique), la acción propuesta y su límite.
2. SI solo existe una señal, por ejemplo una herramienta fallida, ENTONCES DEBE
   presentar una sugerencia de investigación, sin afirmar una causa no comprobada.
3. SI hay datos insuficientes ENTONCES DEBE sugerir qué medir o validar primero.
4. CUANDO se muestra una recomendación ENTONCES NO DEBE aplicar configuraciones,
   cambiar instrucciones, instalar plugins ni modificar proyectos automáticamente.

### 4. Separar operación y calidad del resultado

**Historia:** Como usuario quiero evitar un ranking engañoso.

1. SI no existe validación del resultado ENTONCES DEBE indicar que su corrección no
   está evaluada; una respuesta final o un turno cerrado NO DEBEN equivaler a éxito.
2. CUANDO agrupa sesiones por harness ENTONCES DEBE conservar proyecto, modelo,
   versión y cobertura de la muestra, sin atribuir todos los problemas al harness.
3. SI los encargos no son comparables ENTONCES NO DEBE producir un ganador ni una
   puntuación general de calidad entre harness.

### 5. Consultar desde el tablero

**Historia:** Como usuario quiero consultar la evaluación y sus sugerencias en Lienzo.

1. CUANDO abre una sesión ENTONCES DEBE poder consultar sus métricas y sugerencias.
2. CUANDO actualiza la evaluación o cambia de sesión ENTONCES DEBE conservar el
   contexto correcto; una respuesta tardía NO DEBE reemplazar otra sesión.
3. SI la PC dueña no responde ENTONCES DEBE informar el error; NO DEBE inventar
   métricas locales para una sesión remota.

### 6. Verificar el cambio

1. ANTES de entregar ENTONCES DEBEN ejecutarse los cinco roles de pruebas agénticas
   de forma secuencial y la revisión de código, conservando evidencia y limitaciones.
2. Las pruebas DEBEN cubrir muestras incompletas, turnos abiertos, uso acumulado,
   resultados faltantes, errores explícitos, aislamiento de sesiones y respuestas tardías.
3. Ninguna tarea, baseline, propuesta o recomendación DEBE aprobarse ni marcarse
   completada automáticamente.

### 7. Relacionar observaciones con herramientas de mejora

**Historia:** Como usuario quiero saber qué herramienta podría ayudar y cómo verificarlo.

1. SI hay salidas de terminal voluminosas ENTONCES DEBE poder sugerir evaluar un
   compresor como RTK, citando las llamadas observadas y preservando los diagnósticos.
2. SI hay muchas lecturas o búsquedas de código ENTONCES DEBE poder sugerir evaluar
   CodeGraph o Graphify; el número de lecturas por sí solo NO DEBE declararse desperdicio.
3. SI una propuesta requiere un plugin, skill o servicio ENTONCES DEBE indicar el
   proyecto exacto, la fuente, las condiciones y la medición que permitiría aceptarla.
4. Los porcentajes publicados por los autores NO DEBEN presentarse como ahorro
   medido en las sesiones del usuario. Los caracteres o bytes observados NO DEBEN
   etiquetarse como tokens facturados.
5. SI se prueba una mejora ENTONCES DEBE compararse el mismo caso con y sin ella,
   registrando versión, modelo, criterios de calidad, uso disponible y duración.
   Menos texto o menos código NO DEBEN equivaler automáticamente a mejor calidad.
6. Jev PUEDE considerarse como clasificador opcional de decisiones delimitadas;
   su criterio, uso de API y costo DEBEN definirse y autorizarse antes de integrarlo.

## Herramientas señaladas por Ariel

Investigación de fuentes primarias a partir de la captura adjunta, 2026-10-12.
Son candidatos para recomendaciones y pruebas posteriores; no se instalaron.

| Herramienta | Función documentada | Señal que justificaría investigarla |
|---|---|---|
| [RTK](https://github.com/rtk-ai/rtk) | Filtrar/comprimir salida de comandos antes de entregarla al agente. | Salidas de terminal voluminosas; comprobar que no se pierdan errores necesarios. |
| [CodeGraph](https://github.com/colbymchenry/codegraph) | Índice local de símbolos y relaciones de código, consultable por MCP. | Exploración repetida de código; medir consultas y exactitud con el índice vigente. |
| [Graphify](https://github.com/Graphify-Labs/graphify) | Grafo de código y otros materiales; el tratamiento semántico de documentos puede usar modelos. | Necesidad de relacionar código con documentación; medir también costo del indexado. |
| [Caveman](https://github.com/JuliusBrussee/caveman) | Instrucciones de respuestas breves y componentes de compresión. | Salida narrativa extensa; verificar comprensión y calidad antes de adoptar el estilo. |
| [Ponytail](https://github.com/DietrichGebert/ponytail) | Instrucciones para reutilizar soluciones y escribir el mínimo código necesario. | Posible sobreimplementación confirmada por revisión; mantener validaciones y pruebas. |
| [Jev](https://docs.typesafe.ai/introduction/coding-agents) | Decisiones tipadas: elección, puntuación según rúbrica y juicio verdadero/falso. | Clasificación o selección acotada con criterios definidos; no sustituye pruebas de corrección. |

La captura menciona nombres sin URLs: se identificaron estos proyectos como candidatos,
sin afirmar que sean exactamente las variantes usadas en la demostración de lidr.co.
Las sugerencias deberán respetar las instrucciones de Ariel en `AGENTS.md`.

## Selección para Lienzo (2026-10-12)

Pedido de Ariel: Lienzo debe mejorar el trabajo de los coding agents CLI o sugerir mejoras usando únicamente las herramientas que aporten; REA queda excluida.

| Candidato | Decisión propuesta | Uso dentro de Lienzo | Condición antes de activar |
|---|---|---|---|
| RTK | Primera prioridad | Sugerir compresión cuando haya salidas de comandos voluminosas; ofrecer activación para un harness compatible. | Verificar códigos de salida, recuperar salida original y compatibilidad real del shell/hook por agente, PC y distro. |
| CodeGraph | Primera prioridad | Sugerir exploración e impacto mediante índice por proyecto. | Verificar vigencia y cobertura del índice; conservar lectura directa para datos ausentes o inconsistentes. |
| Ponytail | Modo opcional | Ofrecer instrucciones de cambio mínimo y reutilización para un encargo. | Instrucciones de Ariel y del proyecto prevalecen; conservar code review, pruebas agénticas, validación y accesibilidad. |
| Graphify | Uso específico | Sugerirlo cuando la investigación necesite relaciones entre código y documentación. | Declarar qué usa AST local y qué usa modelos; autorizar costo y datos antes de la extracción semántica. |
| Caveman | Postergar | Evaluar después el compresor, separado del estilo de respuesta. | Medir sobre casos reales y no apilarlo con RTK sin demostrar mejora; no comprimir instrucciones obligatorias automáticamente. |
| Jev/TypeSafe | Incorporar como juez opcional | Clasificar señales y elegir entre sugerencias delimitadas, incluyendo ninguna o datos insuficientes. | Ariel indica que Chesstudia ya dispone de API y pide adaptarla a Lienzo. Reutilizar el contrato OpenRouter de apps/api/tutor/jev.py, con credencial propia de Lienzo, sin importar el proyecto chess ni exponer claves. |

### Criterios propuestos de integración

1. CUANDO muestra herramientas ENTONCES DEBE distinguir clonado, instalado, compatible, disponible y activo. Una carpeta presente NO acredita disponibilidad.
2. CUANDO propone una herramienta ENTONCES DEBE citar llamadas/turnos observados y explicar el problema al que responde, sin un umbral arbitrario de desperdicio.
3. SI el usuario autoriza una activación ENTONCES DEBE mostrar su alcance (sesión/proyecto, agente, PC y distro), cambios, versión y reversión antes de aplicarla. La autorización puede conservarse para lanzamientos posteriores dentro de ese alcance.
4. CUANDO configura herramientas ENTONCES DEBE conservar los hooks y MCP existentes y las instrucciones del usuario; NO DEBE crear ni mantener CLAUDE.md.
5. SI falta una herramienta o el índice no es vigente ENTONCES DEBE informar la limitación sin impedir lanzar el agente.
6. CUANDO verifica beneficio ENTONCES DEBE conservar el resultado funcional y contrastar el mismo caso antes/después. Las pruebas, revisiones y diagnósticos originales NO DEBEN desaparecer por compresión.
7. REA NO DEBE aparecer como candidato de mejora de coding agents en este alcance.

### Fuentes inspeccionadas

Revisión estática focalizada, sin ejecución ni auditoría exhaustiva:

- RTK `311ebcbf`: README.md; src/hooks/init/codex.rs; src/hooks/init/pi.rs; src/core/tee.rs. La recuperación puede estar desactivada: no asumir que toda salida original queda guardada.
- CodeGraph `7ba8eee4`: README.md; src/mcp/server-instructions.ts. Sus instrucciones promueven confiar en el índice sin releer; Lienzo debe respetar la verificación en vivo exigida por Ariel y comprobar su vigencia.
- Graphify `a5ba60d`: README.md; pyproject.toml. El análisis de documentación agrega procesamiento semántico; no es equivalente al AST local gratuito.
- Ponytail `9b58c1f`: skills/ponytail/SKILL.md. Es una pauta de trabajo, no una compresión de herramientas.
- Caveman `2e08b917`: README.md; INSTALL.md; package.json. El checkout distingue skill, hooks y proxy; no instalar el paquete completo para obtener únicamente respuestas breves.
- TypeSafe `65a39f3`: README.md; skills/typesafe-ai/SKILL.md. La carpeta llamada jev contiene instrucciones, no el modelo.

Estado de esta sección: propuesta para revisión. No hay mejoras instaladas o habilitadas, pruebas funcionales ni ahorro medido en esta evaluación.

### Jev: adaptación solicitada desde Chesstudia

El 2026-10-12 Ariel pidió adaptar a Lienzo la API ya usada en Chesstudia. Fuente inspeccionada: D:/Apps/chess/apps/api/tutor/jev.py y docs/jev.md. Ese cliente usa POST https://openrouter.ai/api/alpha/decisions, el alias ~typesafe/jev-latest y provider con zdr=true/data_collection=deny. Esto documenta el contrato del cliente, no verifica disponibilidad actual ni precio vigente.

- El secreto de Chesstudia está documentado en /etc/chesstudia/env dentro de WSL, bajo CHESSTUDIA_OPENROUTER_API_KEY. No copiar el archivo entero ni escribir el secreto en config.json, Git, navegador o logs.
- Lienzo necesita almacenamiento local privado para la credencial y límites explícitos de uso; no debe leer el secreto de chess en cada evaluación ni depender de su código.
- Una evaluación semántica será solicitada explícitamente o habilitada para un alcance y presupuesto definidos. No hacer llamadas pagas por cada evento SSE.
- Enviar únicamente evidencia seleccionada y revisable; no transcripts completos ni variables de entorno por defecto.
- Jev seleccionará candidatos o datos insuficientes; las métricas y citas siguen calculadas y verificadas en código. Las probabilidades no prueban causas ni corrección del código.
- Conservar modelo efectivo, id, usage y costo; costo ausente es desconocido/error, nunca cero. Timeout, falta de saldo, errores de proveedor y respuestas inválidas deben ser visibles; sin reintentos automáticos.
- El patrón validado de Chesstudia sirve de referencia para el adaptador; se necesita una prueba funcional propia de Lienzo antes de afirmar disponibilidad o beneficio.

## Evidencia de exploración original

Lectura en vivo de `GET /sessions` y `GET /sessions/<id>/turns?n=20`, 2026-10-12,
sin escrituras en sesiones ni llamadas a modelos:

| Fuente | Turnos observados | Cerrados | Con usage | Herramientas | Con resultado | Errores explícitos |
|---|---:|---:|---:|---:|---:|---:|
| Pi, proyecto chess | 9 | 8 | 8 | 128 | 128 | 8 |
| Codex, proyecto lienzo | 2 | 1 | 2 | 102 | 102 | 15 |

Ambas fuentes informaron modelo `gpt-6.1-sol` y `has_more: false`; la versión y el
indicador de truncamiento existen en `meta`, pero todavía no se registró su valor en
esta muestra. El inventario no certifica exhaustividad ni compara resultados de trabajo.
Los contadores de la tarjeta corresponden a otro alcance y no sustituyen esta evaluación.

## Supuestos para revisión

- La intención se interpreta como análisis de sesiones reales y recomendaciones.
- La primera versión usa reglas deterministas; un juez con modelo y un benchmark de
  encargos idénticos requieren definir criterios, costo y autorización por separado.
- La calidad del resultado queda explícitamente sin evaluar hasta contar con una
  validación autorizada; no se crea una puntuación arbitraria.
- Estado: propuesta de requisitos, sin aprobación. Diseño y código todavía pendientes.
## Extensión autorizada: aprendizaje oportunista (2026-10-12)

8.1 CUANDO hay un proyecto en cola, el servidor DEBE analizar memoria existente solo con inactividad real >=180 s, dos muestras CPU <=35%, memoria libre >=1.5 GB, sin permisos pendientes ni sesiones locales trabajando o de estado desconocido. Señales ausentes bloquean.
8.2 MIENTRAS vuelve actividad, el trabajo local DEBE suspenderse cooperativamente; nunca detener agentes. Una ejecución por PC, <=30 nodos y plazo cooperativo de 30 s. Esperas SQLite limitadas a 250 ms; no red ni procesos.
8.3 La cola DEBE persistir IDs/estados por proyecto, recuperar ejecuciones interrumpidas como pendientes de revisión, y evitar reintentos automáticos o reencolado al finalizar.
8.4 Las hipótesis DEBEN ser decisiones propuestas en conocimiento.sqlite, citar nodos fuente y contexto conocido, distinguir probabilidad del modelo de evidencia empírica, tener vencimiento y rollback. Nunca confirmar ni aprobar baselines.
8.5 Sin presupuesto explícito, el scheduler DEBE impedir agentes nuevos, Jev, embeddings y servicios pagos. La autorización manual Jev existente no se hereda.
8.6 El panel DEBE mostrar cola, motivo de bloqueo y resultados propuestos, permitir pausar y encolar análisis local. No acepta comandos arbitrarios ni aplica perfiles a sesiones existentes.
8.7 Experimentos OFF/ON DEBEN congelar tarea, contexto y oráculo; medir calidad, errores, herramientas, tiempos y consumo observable separadamente por agente/OS. Datos ausentes no son cero. Esta ronda no ejecuta experimentos CLI.
## Contabilidad y experimentos autorizados (2026-10-12 13:18)

9.1 La ronda DEBE usar un tope TOTAL USD 2 (reducción de Ariel 13:24), incluidos gastos anteriores, con una autoridad única en PC 75727ff74069. Otras PCs no crean saldos utilizables ni pueden ejecutar cargos.
9.2 Toda llamada paga DEBE reservar previamente un máximo verificable dentro de transacción persistente. Presupuesto agotado, costo previo desconocido, proveedor sin cota, autoridad ausente o actividad bloquean antes de red/CLI.
9.3 Respuestas con costo confirmado DEBEN conciliar la reserva incluso si luego falla el guardado; timeout/error/costo ausente conservan la reserva pendiente. Reiniciar no devuelve dinero ni dispara reintentos. Una reserva solo se envía una vez.
9.4 Los casos OFF/ON autorizados DEBEN distinguir pruebas locales de salida RTK de agentes reales: costos de servicios cero en los primeros, tokens/costo de agentes desconocidos. No presentar pruebas de comandos como validación de Caveman u obediencia de CLI.
## Cierre funcional autorizado (adjuntos 135359/135503, 2026-10-12)

10.1 GET scheduler DEBE ser lectura, incluso con ledger ausente o identidad corrupta. Inicialización/recuperación solo al start/activación explícita.
10.2 CUANDO hay quietud/recursos y evidencia nueva, el servidor DEBE encolar automáticamente una muestra de incidentes por proyecto/versión. Cooldown 120 s, cola <=100, <=30 fuentes; versión repetida no se reencola, las hipótesis propias no cambian la versión.
10.3 DEBE revalidar actividad/cancelación después de sources y antes de propose. Una transacción en curso termina; se conserva su resultado/cursor y se pausa sin iniciar otra. No prometer latencia absoluta sin medición real.
10.4 UI DEBE distinguir origen automático/solicitado y mostrar IDs/versiones fuente y propuestas. Experimentación CLI/Caveman y ahorro siguen desconocidos sin ensayo.
## Permisos vigentes y encargo local (aprobación 140806/140823)

11.1 Para inactividad, permisos vencidos (expires_at con zona <=ahora) o de sesión muerta NO bloquean. Fecha/contexto vivo desconocidos bloquean. No aprobar, denegar ni borrar el historial.
11.2 El encargo OFF/ON integrado DEBE esperar inactividad/recursos reales, preservar perfil y pausar antes del siguiente; manifiesto cambiado/oráculo fallido → revisión, sin reintento automático. Contratos fijos de Lienzo, sin agentes ni servicios pagos, evidencia y veredicto humano.
