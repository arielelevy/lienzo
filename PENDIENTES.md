# Pendientes del lienzo

Esta es la única lista de pendientes. MEJORAS.md conserva hechos históricos; DISENO.es.md
describe la arquitectura y docs/PRODUCTO.md las decisiones de producto.

Fecha: 2026-10-10.

Actualización documental: 2026-10-16. No se cerraron casillas al consolidar las specs.

## Producto, aprendizaje y extensiones (2026-10-16)

Checklist único de esta conversación. Todo queda pendiente; el estado técnico no cierra una tarea.
**Prioridad indicada por Ariel: primero el evaluador que usa Codex en segundo plano.**

### Cinco CLI Codex — cierre de integración 0.3.1 (2026-10-17)

Se lanzaron cinco CLI reales A–E por Lienzo, con archivos separados y reglas de retorno a
`01a14bf6-70e4-7c03-b9ae-7f3ad2bb5c0c`. Entregas, inventarios y logs completos en
`.temp/coordinacion/2026-10-17/ronda-cinco-final/`. La integración corrige cuota corta agotada,
retroceso de informes entregados, recorridos repetidos en memoria, tipo inválido de manifiesto
y validación/liberación de cuadros en Chrome remoto. La P0 de identidad recibe mitigación:
los handles no habilitan envío CLI; Desktop conserva su contrato. No es reidentificación resuelta.

Focales de raíz: 64 identidad, 94 cuota/informes y 83 memoria/plugins aprobadas; 18 UI en copia
aislada de E. Los conjuntos se solapan; la verificación global se documenta en
`code-review-2026-10-17-cinco.md`. No se cerraron casillas ni se aprobaron referencias. A–E
entregaron y se cerraron sus procesos propios; se conservaron informes pendientes y reglas
retiradas. Reinicio y mediciones reales siguen sujetos a las dependencias indicadas debajo.

### Ronda de cuatro Codex — avance y P0 reproducida (2026-10-17)

Cierre Desktop para 0.3.0: reconexión explícita de adaptador inactivo del mismo proceso,
caducidad visible del comando, descarte de respuesta tardía al cambiar de tarjeta y retiro
de coordinación aunque se pierda el canal. Claude y Codex Desktop mantienen las restricciones
de control de consola. Focal Desktop: 116 backend y 21 UI; contratos adicionales: 44 backend;
movimiento/autorización después de aislar avisos del servidor real: 15 UI. Los conjuntos se
solapan. Primera global fallida conservada; validación final y límites en
`code-review-2026-10-17-desktop.md`. Sin reconexión real nueva confirmada ni reinicio del backend
durante este cierre. No se cerraron casillas ni se aceptaron referencias.

Cuatro CLI propias recibieron encargos y reglas de retorno a la coordinadora
`01a14bf6-70e4-7c03-b9ae-7f3ad2bb5c0c`. Inventario de todos los tramos y evidencia en
`.temp/coordinacion/2026-10-17/ronda-cuatro/`. No se cerraron casillas ni se aprobaron referencias.

Cambios locales nuevos: UUID canónico y segunda observación de proceso/rollout en identidad
Codex (154 pruebas focales); evidencia ejecutada/verificada por lote en patrones (89 focales);
rechazo de aviso hacia la propia coordinadora mediante su ID anterior/restaurado (25 focales);
cliente de lanzamiento que no confunde el cambio de ID de una tarjeta previa con proceso nuevo
(20 focales). Las cifras son conjuntos focales con solapamiento, no una suma de cobertura global.
Los módulos nuevos posteriores al reinicio de 19:43 requieren activación coordinada; no se
reinició el backend durante esta ronda.

**P0 /new reproducida en CLI propia:** el 17 a las 19:53, después de `/new` y elegir
«Use current Git worktree», la consola quedó vacía pero el proceso conservó el único handle
del rollout anterior `01a14c08-d12a-7282-9801-a7a40719158d`. Incluso el probe corregido lo
dio por verificado. `/send` marcó entregado en ese hilo; se contaron un mensaje de usuario y
un ACK exacto en el rollout anterior, sin aparecer en la consola nueva. Un handle abierto y
dos snapshots estables no prueban que el hilo sea el visible. La P0 sigue abierta: se necesita
una fuente autoritativa del hilo actual o un transporte que no dirija al hilo abandonado.
No reinterpretar ese ACK como continuidad de la TUI. `/clear` real sigue sin medir.
Evidencia: `raiz/new-envio.json`, `new-verificacion.json` y `new-conteo.json` de la ronda.

Costo medido del probe nuevo: 372,83–489,63 ms por PID, una muestra en cada una de las cuatro
CLI propias bajo carga concurrente; no es benchmark en reposo ni justifica caché de identidad
para autorizar envíos. La medición dentro del sandbox no pudo abrir procesos; se midió afuera
con autorización. A/B fueron cerradas tras entregar y se comprobó que sus PID dejaron de existir.

UI integrada: Memoria del proyecto permite consultar creencias, checklist contextual y patrones
con estado y respaldo; sólo GET, contexto explícito y descarte de respuestas tardías. Se corrigió
el fixture de catálogo para que la recuperación dependa del gesto de reintento, no del número
de peticiones de montaje de React. La integración focal final `2026-10-17T22-57-09.839Z-33400`
dio 247 backend y 16 UI aprobados, más ESLint, build y unitarias con código 0. Runner y compuerta
salieron 1 por baseline ausente en la configuración aislada: no es PASS global ni aceptación.
La revisión está en `code-review-2026-10-17-ronda4.md`. Las cuatro CLI propias entregaron,
se cerraron y se comprobó la ausencia de sus PID. Sus reglas quedaron desactivadas, con
informes pendientes conservados; no se acusaron como integradas ni se completaron tareas.

### Ronda de cinco Codex — integración activada (2026-10-17, 19:43)

Se integraron identidad Codex por proceso/FILETIME/rollout abierto; conservación y acuses de informes;
guardias de cuota, decisión y cancelación del investigador; pasos de herramientas y vista externa
agregada; refutaciones y evidencia de controles separada por nivel. Codex Desktop puede ser
coordinadora si tiene transporte disponible. Este chat quedó con `coordinator: true` en la API viva.

Corrida global `2026-10-17T22-32-46.991Z-37680`: 7 de 7 casos con código 0,
2244 pruebas backend aprobadas y 3 omitidas, 136 recorridos UI aprobados; lint/build/unitarias y
memoria focal/e2e con código 0. El recorrido UI nuevo de recepción → integración pasó por separado.
Los 32 archivos de código/pruebas inventariados no cambiaron durante la medición.
Compuerta **ESCALAR (3)**: las mutaciones del 10/10 son de otro estado, no certifican este corte.
No se fijaron baselines ni se aceptaron propuestas nuevas. Revisión en `code-review-2026-10-17.md`.

Reinicio supervisado verificado: los siete PID de otras CLI presentes antes seguían vivos y con
tarjeta después. Lectura viva de `/conocimiento/lienzo/registro-externo`: nivel 3, 18 grupos,
sólo campos `nivel`, `proyecto`, `actividad`. Las cinco CLI de esta ronda entregaron y se cerraron.
Esta activación sustituye las notas históricas de «falta reiniciar» para estos módulos; no cierra casillas.

Siguen pendientes: `/new` y `/clear` reales y su carrera con encolado; medición de costo del sondeo
de handles; continuidad formal de coordinadora ocupada/quieta con dos frentes y reinicio; mutaciones
vigentes y aceptación de propuestas; primera investigación real y calidad causal; narrativa externa
curada, duración individual de herramientas, integración de productores/UI de controles y los
pendientes de hardware, otras PCs, presupuesto y decisiones humanas de las secciones siguientes.

API incorporada: acuse humano desde PC/LAN en `/rules/<r>/informes/<i>/acuse` (`recibido` antes de
`integrado`); `/conocimiento/<p>/registro-externo`; `/conocimiento/<p>/encargos/<id>/controles`.
El acuse no autentica una CLI mediante su UUID ni acredita por sí mismo calidad del trabajo.

### Release 0.2.0 — estado observado y pendientes (2026-10-17)

Publicado por pedido explícito de Ariel: `main` y tag `v0.2.0`, commit `98e65f7`.
Build, ESLint global y pruebas Node terminaron con código 0. Correcciones de diseño:
367 backend +13 UI; clasificación/respuestas tardías: 68 focales; bridge/bootstrap: 8 +6.
La prueba real por API principal a Claude Desktop contó un peer y un ACK exacto, y la API
publicó el mismo UUID como entregado con confirmación final. No se confunde con el self-test.
El servidor se reinició a las 13:44 con PID nuevo, conservando transcripciones e informes.
Sesiones de trabajo D/F cerradas después de leer sus entregas; reglas de retorno retiradas.
La sesión Desktop y las sesiones de otros proyectos no se cerraron.

La corrida global larga se interrumpió por pedido de simplificar el cierre; no tiene resultado
completo y no se declara aprobada. Baselines y mutaciones no se aprobaron automáticamente.
Detalle: [notas 0.2.0](docs/releases/0.2.0.md) y `code-review-2026-10-17.md`.

- [ ] Reconectar el adaptador de Claude Desktop después del reinicio del servidor: generar
  un bootstrap nuevo en la tarjeta y autorizar ese comando directamente en esa conversación.
  La conexión anterior probada caduca al cerrar el servidor; no reutilizar comandos vencidos.
  Conectado el adaptador, no hay autorización por cada mensaje.
- [ ] Retomar, si se prioriza, la automatización de conexión de sesiones Desktop nuevas o
  evaluar Claude Code como puente. Prototipo y pruebas conservados íntegros fuera del release
  en `.temp/coordinacion/2026-10-17/automatizacion-diferida`; sin cambiar hooks instalados,
  permisos ni modos para eludir rechazos. Exige una prueba real de sesión nueva.
- [ ] Ejecutar una batería global completa cuando se retome esa validación; aceptar baseline
  y mutaciones sólo tras revisión humana. Las pruebas focales no se publican como globales.
- [ ] Arrancar habitualmente mediante `lienzo-server.cmd` para disponer del relanzamiento.
  El proceso iniciado directamente con Python rechaza POST /restart de forma segura; este
  reinicio requirió detener el PID identificado y levantar un proceso nuevo.
- [ ] Revisar continuidad de mensajes Codex encolados al cerrar una CLI, y la sucesión de
  títulos/reglas cuando una sesión Desktop nueva comparte repo con un encargo CLI cerrado.
  No reutilizar el proceso ni el nombre de un emisor auxiliar como identidad de sesión.
- [ ] Evaluar handles fijados en copias si se necesita resistir sustituciones hostiles de
  rutas entre validación y uso; el rechazo actual de junctions existentes no elimina TOCTOU.

### P0 — Falla grave de continuidad de la coordinadora (2026-10-17)

- [ ] **Reidentificar el hilo activo de una Codex CLI después de `/new` o `/clear`, y rechazar
  el envío por cola si no puede vincularse al proceso actual.** Reportado por la coordinadora
  de opensyync `48befe79`, después de publicar 0.2.0. No se reprodujo todavía en una CLI propia.
  Caso reportado: PID31904 conservó tarjeta `01a14774-aa3f-7062-b3f3-aa996a33ff35` y rollout
  del 2026-10-16, aunque `/new` abrió `01a14a6b-1acc-7db2-9dbb-b7faf4033e22` el 17 a las 12:11.
  POST /send siguió aceptando codex_queue como encolado, sin recepción en la terminal actual;
  referencia de ejemplo `01a14ab6-ef97-73d2-a019-2f067e87f26d`, 13:34. Se confundió aceptación
  con trabajo efectivo durante unos 30 minutos. Mitigación de esa coordinadora: cerrar sólo su
  PID afectado y lanzar otra CLI; no repetir esa intervención sobre sus sesiones desde Lienzo.
  La guardia leída en codex_queue verifica UUID, rollout existente y PID vivo; eso no demuestra
  que el hilo siga siendo el activo de ese PID. No elegir simplemente el rollout más nuevo por cwd.
  Repro pendiente: CLI propia → `/new` → «Use current Git worktree» → POST /send; también /clear,
  dos CLI del mismo repo, codex exec paralelo y PID reciclado. Exigir nueva identidad comprobada
  o rechazo con motivo, preservando reglas/estado y sin reenviar automáticamente los mensajes
  inciertos del hilo anterior. La prueba anterior de entrega de 0.2.0 no cubre esta transición.

- [ ] **Garantizar que la entrega de un frente reanude la coordinación hasta integrar y verificar,
  sin esperar a que Ariel pregunte por el avance.** Pedido explícito de Ariel tras esta ronda.
  Evidencia en vivo: B entregó y su regla `c887b7b25512` registró `fired: 1`,
  `last_result: ok`, `last_fired: 2026-10-16T23:49:50.814-03:00`; el aviso llegó a esta
  conversación, pero la coordinadora respondió con estado y no continuó la integración autorizada.
  A también entregó con `ESTADO:` visible en `last_reply`, pero su regla `2054b0dd7f28`
  seguía en `fired: 0`, con `last_result: salteado: la respuesta no trae «ESTADO:» (turno intermedio)`.
  Investigar por separado la entrega fiable del informe final y la continuidad tras recibirlo;
  no atribuir ambos síntomas a una causa todavía no comprobada.
  Criterio: probar entrega mientras la coordinadora está ocupada y quieta, entrega simultánea de
  dos frentes, respuesta intermedia seguida de final y recuperación tras reinicio. Conservar
  informe pendiente hasta acuse de recepción y procesamiento; recuperar avisos perdidos sin
  duplicar encargos ni generar bucles. Mostrar entregado, recibido e integrado por separado.
  Registrar evidencia de que la coordinadora retoma revisión/integración/pruebas o comunica un
  bloqueo concreto, sin completar tareas ni aprobar baselines automáticamente.
  Estado (2026-10-17): causa de A comprobada con la transcripción y el log. Una `<task-notification>`
  reabrió el trabajo sin UserPromptSubmit; transcripts.py lo dio por terminado (23:55:20) con la
  respuesta intermedia y el Stop real con «ESTADO:» (23:56:13) no cambió el estado, así que la regla
  nunca evaluó la entrega. Corregido en local: la notificación reabre el turno (transcripts.py) y
  rules.py reconcilia turnos cerrados sin evaluar (marca persistida, sin duplicados ni bucles).
  Pruebas: tests/test_rules.py y test_transcripts.py, más la transcripción real de A cortada en
  02:55:20 (abierto) y 02:56:14 (cerrado con ESTADO:). Falta reinicio del backend, aceptación,
  la vista entregado/recibido/integrado y la continuidad de la coordinadora (síntoma de B, aparte).

### P0 — Evaluador e investigación en segundo plano

- [ ] **Implementar el evaluador con Codex/CLI en background, complementando a Jev.**
  Jev conserva el filtro barato y la priorización. Codex investiga los casos elegidos, relaciona
  código y trazas, identifica causas y propone mejoras. No reemplazar Jev por llamadas CLI para todo.
  Criterio: recorrer selección → investigación CLI → resultado estructurado → evidencia en memoria
  → propuesta visible, con un caso positivo y fallos reproducibles.
  Estado (2026-10-17): implementado localmente (optimization_research*, cola y scheduler) con
  pruebas y casos del runner; la vista del panel muestra cuota, bloqueos, candidatos y cancelación.
  Falta reiniciar el backend (puede lanzar `codex exec` real con la cuota de Ariel), primera
  ejecución real, aceptación, baseline y mutaciones aprobados.
- [ ] Integrar el investigador a la cola y al scheduler de Lienzo: un trabajo controlado,
  límites de duración/consumo, condiciones de inactividad y recursos, pausa, cancelación,
  recuperación y deduplicación. No afectar sesiones ajenas ni habilitar reintentos infinitos.
  Criterio: actividad del usuario o un fallo detiene/pospone según el contrato, conservando evidencia.
- [ ] Definir y comprobar la política de autonomía y consumo del investigador.
  Distinguir investigación de sólo lectura, experimentos aislados y aplicación de cambios.
  La conversación no concede un presupuesto monetario nuevo ni autoriza instalar lo que recomiende.
  Criterio: mostrar límites y motivos de bloqueo; ninguna ejecución puede saltarse las guardias.
- [ ] Ampliar las preguntas del evaluador al flujo completo: herramientas, contexto, memoria,
  arquitectura, planificación, tareas/features, construcción, iteraciones entre olas, coordinación,
  esperas, pruebas, review, auditoría, retrabajo, documentación y capacidades que faltan.
  Criterio: cada propuesta identifica problema, fuentes, alcance, alternativa y forma de comprobarla.

### Ciclo aparte — Tres niveles de registro (pedido de Ariel, 2026-10-17)

- [ ] **Guardar lo que pasa en Lienzo en tres niveles y que cada consumidor lea el suyo.**
  1. Crudo: todo (transcripciones, salidas completas, eventos). Se depura cada tanto con una retención que
     decide Ariel; depurar es borrar, no se automatiza sin esa decisión.
  2. Cómo se hizo el trabajo: llamadas, tiempos, esperas, quién hizo qué. Es para el investigador.
  3. Qué pasó: qué se hizo y en qué proyectos, resumido y limpio, sin cosas internas ni ruido. Es para todas
     las sesiones y para los sistemas externos que reciben información de Lienzo.
  El investigador usa los niveles 2 y 3 para optimizar. Hoy su paquete trae el 3 (nodos de memoria) y sólo
  ids de sesión del 2; las capturas (`captura`) son la fuente natural del nivel 2.
  Criterio: un consumidor externo recibe sólo el nivel 3; el investigador recibe el 2 y el 3 sin
  transcripciones; el crudo se puede recuperar hasta su depuración.
  Estado (2026-10-17): nivel 2 del investigador desde capturas hecho (por sesión y hasta 60 eventos
  recientes, redactados; el crudo no viaja). Faltan las llamadas a herramientas por paso, el nivel 3
  para sistemas externos y la depuración del crudo.
- [ ] Llevar la instrucción de RTK de la base agéntica (`lienzo/tools/rtk.py`) a todo lo que lee un agente
  (`rtk read`, `rtk rg`, `rtk find`, `rtk git`, `rtk recall`), no sólo a las salidas largas. La base la
  comparten las sesiones y el investigador.

### P1 — Memoria, creencias, patrones y decisión

- [ ] Integrar la base de creencias en la memoria existente, con fuentes, contexto, confianza,
  excepciones, vigencia y posibilidad de refutar/reemplazar sin borrar historia.
  Estado: código y contratos locales; falta aceptación y activación.
- [ ] Entregar el checklist contextual como vista de creencias respaldadas, corto y ajustado al trabajo.
  Excluir propuestas sin validar, vencimientos, refutaciones y apoyos retirados.
  Estado: implementación local sin reglas duplicadas; falta integración de uso y activación.
- [ ] Detectar y contrastar patrones de desarrollo sin tratar todo igual.
  Separar bugfix, feature, refactor, investigación, documentación y arquitectura, conservando
  proyecto, tecnología, área, fase, agente/modelo/versiones y condiciones relevantes.
  Estado: agrupación por etiquetas explícitas; falta investigación de patrones desde flujos reales.
- [ ] Incorporar evidencia de pruebas, review local de Claude y auditoría mediante skill.
  Distinguir controles declarados, ejecutados, hallazgos, correcciones verificadas y pendientes.
  Una revisión ejecutada o un turno cerrado no prueba calidad ni completa una tarea.
- [ ] Mostrar en Lienzo observaciones, investigaciones, propuestas, evidencia, creencias y checklist.
  Permitir que Ariel revise y decida adopción; no promover una recomendación del modelo por sí sola.
  Criterio: se puede seguir una propuesta hasta sus fuentes y conocer qué no fue medido.

### P1 — Catálogo y contrato de plugins

- [ ] Activar y verificar el catálogo ampliado: Anatomy y Commit (Image Preview y Sub Meter quedaron
  fuera de Lienzo por decisión de Ariel, 2026-10-17; siguen instalados en Claude Code).
  Estado: fichas implementadas y UI compilada/probada; backend activo observado con cinco fichas
  anteriores. La activación debe coordinarse: había dos sesiones corriendo y tres con turno terminado.
- [ ] Instalar y comprobar Better Claude en el entorno autorizado.
  Verificar manifiestos, activación y compatibilidad de Image Preview/Sub Meter/Commit en Claude Code.
  Mantener visible que Image Preview necesita verificación Windows, Sub Meter depende de suscripción,
  y Commit puede hacer commit/push en modo no interactivo. No ejecutar /commit como prueba automática.
  Estado (2026-10-17): instalados por pedido de Ariel en scope user (image-preview 0.1.1, sub-meter 0.1.0,
  commit 0.2.0); el catálogo vivo los ve habilitados. Falta verificar en una sesión nueva de Claude Code
  el hover de Image Preview en Windows (fullscreen) y la barra de Sub Meter. /commit no se ejecutó.
  Ariel confirmó el 2026-10-17 que Better Claude anda.
- [ ] Mostrar tools, integraciones y formas de trabajo sin confundir función con empaquetado.
  Estado: metadatos de formato/compatibilidad/límites e inventario de plugins locales implementados.
  Un plugin puede no tener tools ni GitHub. Cargado no equivale a conectado o sano.
- [ ] Implementar el contrato uniforme de incorporación de plugins:
  identidad/versión, compatibilidad, capacidades, configuración, permisos, ciclo de vida, estado,
  evidencia y relaciones opcionales. El manifiesto no obliga a tener endpoints, interfaz o tools.
  Criterio: validar un plugin mínimo y uno inválido, sin romper las extensiones existentes.
  Estado (2026-10-17): contrato v1 implementado localmente (plugin_manifest.py, plugins.py, fichas
  en el panel, parada al salir del server). Mínimo, inválido y Stepwise legacy probados. Falta
  reinicio del backend, aceptación y decidir el manifiesto propio de Stepwise.
- [ ] Conservar Stepwise como integración local existente entre sistemas y formas de trabajo.
  No copiar ni publicar su código en GitHub para registrarlo; verificar ficha y disponibilidad local.
- [ ] Conservar Anatomy como herramienta existente de documentación visual y reutilizar su integración.
  Su aporte documental se evalúa por claridad/utilidad; no sustituye controles de calidad del código.

### P2 — Investigación de comunidad

- [ ] Preparar investigación periódica de tools, integraciones y formas de trabajo de la comunidad.
  Relacionar cada candidata con necesidades observadas y guardar fuentes, fecha, alternativas,
  costos, permisos, mantenimiento y riesgos relevantes.
- [ ] Definir frecuencia y presupuesto de esa investigación, con propuestas para decisión de Ariel.
  Descubrir o recomendar no autoriza instalar, activar ni modificar proyectos.

### Transversal — Diseño, Markdown, calidad y entrega

- [ ] Mantener arquitectura, plan y tareas/features según alcance y riesgo, sin imponer SDD.
  Proceso flexible y calidad no negociable: no reducir revisión, pruebas o información necesaria
  para producir un número mejor de tiempo, longitud o tokens.
- [ ] Mantener alineados Producto, Arquitectura, Aprendizaje y Plugins con lo construido.
  Unificar y eliminar documentos intermedios/obsoletos preservando decisiones y evidencia útil.
  Estado: 13 specs retiradas; 26 Markdown revisados por enlaces, sin enlaces locales rotos.
- [ ] Mantener esta lista como única fuente de tareas; no cerrar casillas sin pedido explícito.
  Distinguir implementación, prueba local, aceptación, activación y medición en uso real.
- [ ] Aplicar Explorer → Analyser → Designer → Executor → Detective y code-audit a los cambios.
  Conservar logs/errores y el veredicto real; no aprobar baselines ni mutaciones por cuenta propia.
  Estado medido: 45 contratos del catálogo, 7 recorridos UI y 52 pruebas de creencias/patrones pasan;
  build/lint verificados. Compuertas código 1 por baseline ausente; no hay PASS certificado.
- [ ] Verificar el circuito integrado en una instancia aislada antes de activar el backend principal.
  Revalidar las áreas afectadas de consultas, WSL y memoria sin pisar cambios de otras sesiones.
  Retirar las specs no equivale a haber ejecutado sus verificaciones pendientes.

Referencias: [Producto](docs/PRODUCTO.md), [Arquitectura local](DISENO.es.md),
[Aprendizaje](docs/APRENDIZAJE.md), [Plugins](docs/PLUGINS.md) e
[índice documental](docs/README.md). Estas prioridades no conceden consumos nuevos ni aceptación de referencias.

Las casillas heredadas se conservan textuales. El 2026-10-10 se cerraron (con `[x]` y su evidencia
debajo) las verificadas en código, pruebas o decisión de Ariel; las demás siguen pendientes. La evidencia histórica no es una prueba
ejecutada hoy. Las referencias de código de esta consolidación se revisaron estáticamente.

## Orquestación de encargos

- [ ] **Incorporar a Lienzo las ideas de coordinación y verificación del experimento de Prime Agent**
  (pedido de Ariel, 2026-10-12). Mantener la tecnología y arquitectura actuales; no reescribir en Rust.
  - Etapas explícitas por encargo: pendiente → implementación → revisión → verificación. El cierre
    de un turno o una respuesta del agente no equivale a aprobación ni completa la tarea por sí solo.
  - Dependencias entre encargos: esperar los insumos necesarios y ejecutar en paralelo los frentes
    independientes, con la coordinadora controlando la integración.
  - Evaluar un `git worktree` por frente que modifica código para reducir interferencias.
  - Límites de gasto y reintentos por encargo, con detención y aviso cuando una ronda repite errores
    sin avanzar. Distinguir consumo medido de estimaciones y datos no disponibles.
  - Evidencia visible junto al informe: cambios, revisión, pruebas ejecutadas, resultados y pendientes.
    Priorizar la vinculación del encargo con su evidencia de revisión y pruebas.
  - Reutilizar la coordinadora, los mensajes, las reglas `on_stop` y sus límites existentes.
  - Criterio de aceptación: un encargo puede recorrerse de punta a punta con evidencia consultable;
    una dependencia bloquea su ejecución hasta disponer del insumo; un fallo de verificación permite
    devolverlo a implementación; los límites frenan reintentos sin avance; ninguna tarea se marca
    completada sin pedido explícito de Ariel.

  Origen: conversación con Ariel del 2026-10-12 sobre Prime Agent.
  Referencia: https://www.primeintellect.ai/blog/prime-agent-rust.
  **Actualización del 2026-10-16:** lo de arriba sirve como requisitos. Falta definir arquitectura,
  plan y tareas según el alcance: cómo encaja en `coordinar.py`, las reglas `on_stop` y las rondas.
  No exige un recorrido SDD obligatorio.

## Rondas largas: lo que quedó afuera (2026-10-16)

Lo hecho está en el README («Rondas largas») y en `code-review-2026-10-16.md`.

- [ ] Reiniciar el server de 7321 entre olas de OpenSyync: lo coordina su coordinadora (pedido del
  2026-10-16, no reiniciar mientras esté en ronda). Hasta entonces el tablero nuevo pide `/avisos` y
  `/memoria` y recibe 404, y Playwright `humo` y `salud` fallan contra 7321 por esos errores de consola.
- [ ] Aprobar o descartar `pruebas-agenticas/resultados/casos-rondas.nuevo.json` (rondas-focal,
  rondas-e2e) y `mutaciones-rondas.nuevo.json` (5 destructivas, 3 de control); después correr
  `mutar.mjs --sin-cache` y la compuerta sobre el estado commiteado.
- [ ] Medir con dos PCs: un aviso a un frente de otra PC se confirma leyendo `last_reply` del espejo,
  sin probar todavía con la otra PC real; `POST /avisos/<id>/ack` se manda al lienzo de quien creó el aviso.
- [ ] Medir con una restauración real tras reiniciar la PC que Claude y Codex hereden reglas y título
  (cubierto con pruebas sobre el registro; no con agentes reales).

## Trabajar con Claude Desktop y Codex desktop (2026-10-16)

- [ ] **Qué hace falta para que el lienzo trabaje del todo con las apps de escritorio** (pedido de
  Ariel, 2026-10-16: «solo documentalo, investigá»). Hoy el barrido las descarta y el envío las
  rechaza por no tener consola. El detalle, con lo verificado separado de lo inferido, está en
  [docs/desktop-apps.md](docs/desktop-apps.md).
  - **Claude Desktop** corre el mismo motor que la CLI: lee `~/.claude/settings.json` y sus hooks, y
    escribe la transcripción en `~/.claude/projects` con `entrypoint: claude-desktop`. Estado,
    contenido y permisos por hook deberían andar ya, como tarjeta de sólo lectura (sin medir). Mandar
    un mensaje no: no hay consola ni API. Los caminos a medir son el canal nativo Claude-Claude y
    Remote Control. Lanzar y retomar: `claude --desktop --resume <id>` lleva una sesión a la app, y
    `claude --resume` la devuelve a la terminal.
  - **Codex desktop** guarda sus hilos en `~/.codex/sessions` con `originator: Codex Desktop`, que el
    lienzo hoy descarta. No hay hook confirmado en la app. El camino firme es el app-server (JSON-RPC:
    `thread/resume`, `turn/start`, `turn/steer`, aprobaciones como pedidos al cliente), con el lienzo
    como cliente de hilos que lanza él. `codex://new?prompt=&path=` y `codex://threads/<id>` sólo
    abren o precargan.
  - **Riesgos:** `~/.codex/config.toml` tiene `[features] hooks = false` desde el 2026-10-07 al menos, y
    eso apaga los hooks de Codex también en la CLI. `is_tui` mira sólo la ruta y no reconoce el
    `claude.exe` que trae Desktop (`\Roaming\Claude\claude-code\`) ni el `codex.exe` de la app. Dos
    clientes en un mismo hilo de Codex no están documentados.
  - **Próximo paso:** una sesión de medición con las dos apps abiertas en una carpeta de prueba: qué
    eventos llegan a `~/.lienzo/events` desde Desktop y con qué proceso; contestar un permiso y una
    pregunta desde el lienzo; probar el canal nativo hacia una sesión de Desktop; y un cliente mínimo
    del app-server de Codex, fuera del server, que abra un hilo, mande un turno y conteste una
    aprobación.

## Puente con el orquestador externo, reglas por frecuencia y envío confirmado (2026-10-14)

Ariel aceptó la entrega del puente con veredicto ESCALAR. Detalle del code review en el historial de git (`code-review-2026-10-14.md`).

- [ ] Medir con un agente real autorizado que el `session_id` del hook coincida con la sesión que el
  orquestador ata a su corrida. Solo se probó con su ejecutor de prueba, que no lanza agentes.
- [ ] Puente: detección por proceso en tmux/WSL, tarjetas del orquestador por el espejo entre PCs, y
  relanzar desde Lienzo. Para relanzar faltan contratos medidos.
- [x] Decidir si el e2e del puente entra a la suite y si se aprueban sus mutaciones (propuesta en
  `pruebas-agenticas/resultados/`).
  **Cerrado el 2026-10-15 (Ariel lo dejó a criterio):** no entra. Prueba el plugin Stepwise, que vive en
  `lienzo/extensiones/` fuera de git, con un binario y fixtures de esta PC; en la suite del repo fallaría
  en cualquier otra. Si hace falta, va con el plugin.
- [x] Indicador "enviando…" en la tarjeta mientras un envío espera su `UserPromptSubmit`. Hoy queda en
  su estado anterior hasta la confirmación; sin confirmación a los 25 s, pasa a "te necesita".
  **Cerrado el 2026-10-15:** `envio_pendiente` se ve como «enviando…» en la cabecera de la tarjeta, sin cambiarle el alto (tests-ui/tarjeta.spec.ts).
- [x] backend-pytest roza el timeout de 300 s del runner: 240 s aislado y más bajo carga. Una corrida dio
  una `F` que no se reprodujo. Recalibrar el timeout con aprobación o separar la batería.
  **Cerrado el 2026-10-15:** Ariel aprobó subirlo a 450 s en `pruebas-agenticas.json`.
- [x] Dos permisos de sesiones que ya no estaban se auto-aprobaban cada hora: el hook murió sin leer la
  respuesta y el pedido quedó en disco. **Cerrado el 2026-10-15:** el auto-aprobar saltea un pedido que ya
  tiene su respuesta escrita (tests/test_autoaprobar.py). Los pedidos huérfanos siguen en
  `~/.lienzo/pending` hasta que alguien los borre. **Cerrado también:** el server borra un pedido vencido
  hace más de 2 minutos, con su respuesta (`sessions.purgar_huerfanos`, tests/test_ola1_sesiones.py).
- [x] Reglas `on_stop` agotadas por el tope total viejo: no se reactivan solas. Se reactivan editándolas
  con `limit:"rate"`.
  **Cerrado el 2026-10-15:** al arrancar, `rules.reactivar_agotadas_por_tope_viejo` las prende de nuevo (tests/test_rules_frecuencia.py).
- [ ] Hook en Unix: destino por `TMUX_PANE` sin probar (falta una PC Linux). Origen: code review del 2026-10-10.
- [x] Un diálogo de permiso que el auto-aprobar va a contestar pasa la tarjeta a `te_necesita` unos 5 s:
  `answer_dialog` limpia `dialog` pero el estado vuelve recién en la pasada de pantalla siguiente. La
  columna vacía se abre y se cierra y corre el tablero. Medido el 2026-10-15: unas 36 aprobaciones en una
  hora en una sola tarjeta codex. Toca `sessions.screen_once` y `autoaprobar`.
  **Cerrado el 2026-10-15:** queda en su estado mientras el auto-aprobar lo contesta (15 s de margen; después sí pasa) y contestar un diálogo saca ya la tarjeta de «te necesita» (tests/test_autoaprobar.py).
- [x] Si la pantalla pasa de un diálogo a otro sin quedar sin diálogo en el medio, `dialog_at` no se renueva y el
  segundo cae antes en «te necesita». Origen: code review del 2026-10-15. Gravedad: baja.
  **Cerrado el 2026-10-15:** se renueva cuando cambian la pregunta o las opciones (tests/test_autoaprobar.py).
- [x] `mirror._poll_health` llama a `on_change()` en cada health exitoso aunque nada cambie: el tablero
  recibe el estado completo cada 10 a 15 s y reemplaza todas las sesiones. No se ve, pero es render de más.
  **Cerrado el 2026-10-15:** solo avisa cuando el par vuelve o cambia su diagnóstico (tests/test_mirror.py).

## Pendientes trasladados de MEJORAS.md

### Seguridad

- [x] Pruebas que conviene escribir (salieron de la revisión adversarial): matriz de autenticación
  por ruta para el túnel, paridad entre `Handler` y `PeerHandler`, el contrato de los 404
  (`unknown_session` contra ruta desconocida) y referencias (golden) por agente en los parsers.
  - **Cerrado el 2026-10-10:** Ya escritas: matriz del túnel en `tests/test_ola1_seguridad.py` (`test_por_el_tunel_sin_cookie_todo_da_401_salvo_las_rutas_publicas`), paridad `Handler`/`PeerHandler` en `tests/test_ola2_server.py`, 404 `unknown_session` en `tests/test_server.py` y golden por agente en `tests/test_ola2_agentes.py`.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 5. Gravedad: media.

### Multiplataforma

- [ ] **Evaluar una forma más óptima de sincronizar las bases de memoria entre PCs** (pedido de Ariel,
  2026-10-10). Hoy cada server le pide a cada par, cada 120 s, los cambios y capturas nacidos allá desde su
  cursor (`lienzo/replica.py`, `/peer/conocimiento`), en lotes, aunque no haya nada nuevo; los cuerpos van
  aparte. Lo que habría que medir y comparar:
  - **Empujar en vez de sondear:** que el par avise por el SSE que ya tienen abierto (`/peer/events`) cuando
    nace un cambio, y recién ahí se pida; el ciclo de 120 s queda solo como red. Menos tráfico ocioso y la
    otra PC se entera en segundos, no en hasta dos minutos.
  - **Tamaño y forma de los lotes:** comprimir el JSON (gzip) y ajustar el límite por pedido; medir cuánto
    pesa hoy un ciclo vacío y uno con capturas largas.
  - **Changesets de SQLite** (extensión session) o una base CRDT (cr-sqlite) en vez de la tabla `cambio`
    propia: ver si ahorran código y bytes o si suman una dependencia que no paga (la stdlib no trae ninguna).
  - **Qué no replicar:** si las capturas `observado` de una carpeta temporal o los textos muy largos tienen que
    viajar enteros o alcanza con el resumen y el hash.
  - Criterio: latencia entre que nace un cambio y lo ve la otra PC, bytes por hora con el tablero quieto y
    activo, y que no se rompan los cursores ni la idempotencia (las 10 pruebas de `replica.py` siguen
    pasando).

  Origen: conversación con Ariel del 2026-10-10. Gravedad: **alta, prioridad** (Ariel, 2026-10-10).
  **Actualización del 2026-10-16:** primer paso: medir bytes de un ciclo vacío y de uno con capturas,
  y latencia hasta que la otra PC ve un cambio. Con esos datos definir arquitectura, plan y tareas
  según el alcance, sin exigir SDD. La medición entre PCs necesita ar-it33940 prendida.

- [ ] Integración uniforme de CLI y hallazgos del code review: capacidades compartidas entre
  Python/TypeScript, proveedores de identidad/transcripción/modelo/diálogo/reanudación, Kiro V3
  limitado explícitamente a Windows y diagnóstico de metadatos sin repetir errores.
  Evidencia inicial: 190 pruebas focales pasan y build del frontend pasa (2026-10-07).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 3. Gravedad: media.
  **Estado al 2026-10-15:** sin spec y poco definido. Antes de especificar, contrastar con el código: los
  perfiles de `agentes.py` (permisos, diálogos, transcripciones por agente) pueden cubrir buena parte.

### Federación

- [x] Coordinadora sólo del repo (pedido del 2026-10-07): eliminado el rol por PC del menú,
  cliente y API. Las marcas guardadas se migran al cargar; se conserva una marca local por repo,
  prefiriendo la general existente. Seleccionar una coordinadora desmarca las del mismo repo
  en las demás PCs visibles. Las PCs desconectadas requieren reconciliarse al volver.
  Prueba focal: 134 casos pasan. Corrida agéntica `2026-10-07T06-12-22.146Z-27252`:
  cinco suites sin fallas, 981 backend y 117 UI; menú real verificado con captura.
  - **Cerrado el 2026-10-10:** Implementado y probado el 2026-10-07 (nota de arriba); la compuerta del 2026-10-10 pasa con esas pruebas.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 1. Gravedad: media.

- [ ] Cierres del plan multi-PC (`docs/plan-multi-pc-2026-09-26.md`, historial de Git) que siguen sin
  prueba real con la otra PC: la regla de firewall real de `install.py --peer` (código y `--dry-run`
  probados); ver en vivo desde A las tarjetas y la salud de B; aprobar un permiso de B desde el
  tablero de A; lanzar un frente en B desde la ★ de A y que su informe vuelva solo; una ronda real
  repartida entre dos PCs usando solo el skill, y el skill corregido contra lo medido. Hasta ahora
  todo eso se probó entre dos procesos en la misma PC.

  Origen: `docs/plan-multi-pc-2026-09-26.md`, cierres F1 a F5. Gravedad: media.

- [x] Reiniciar lienzo en la otra PC cierra las codas que corren (medido el 2026-10-03; la recarga automática por `git pull` NO las cerró: la coda de la sesión 4 siguió viva; la hipótesis de pestañas de Windows Terminal en la misma ventana del server tampoco, según la coda A cada coda abre en su propia consola, aunque lo dijo leyendo el código y no la configuración): la coda de la sesión 3 quedó
  `ended_at` en el mismo segundo del reinicio y hubo que restaurarla (`restaurar`, con contexto). Además, con la causa sin
  resolver, todo lo que sale hacia esa PC dio `401 firma invalida` de repente (sin cambios de reloj ni de claves) y solo se
  arregló reiniciando su lienzo. Ideas: que las codas no cuelguen del proceso del server, y que ante un 401 el lienzo
  intente el reinicio del peer o avise con el motivo («su server no valida mi firma»), en vez de dejar el tablero mudo.
  - **Nota del 2026-10-10:** el 401 ya llega al tablero con su motivo («la otra PC no acepta mi firma», `federation.py`, con `causa_401`). Queda la causa de que mueran las codas, que necesita la otra PC.
  - **Cerrado el 2026-10-10 (no se reprodujo):** con el código de db12f5e se lanzó una coda en ar-it33940 desde el tablero de
    la otra PC (PID 16848, contestó «OK») y se reinició ahí el server matando solo el PID de 7321 y relanzando con
    `lienzo-server.cmd`: la coda siguió viva antes, durante y después (mismo padre, PID 19636), y el tablero la volvió a
    ver. Si vuelve a pasar, reabrir con el modo en que se abrió esa coda (a mano o desde el lienzo).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 10. Gravedad: alta.

- [x] El lienzo no puede cerrar un agente colgado de otra PC: `/exit` queda en cola y `interrupt` no
  alcanza si el proceso está clavado. Hoy hubo que pedirle a otro coda un `taskkill` por PID. Idea:
  `POST /sessions/<sid>/kill` que la PC dueña ejecute sobre su propio PID (con la misma
  confirmación que las demás acciones destructivas).
  - **Cerrado el 2026-10-10:** Implementado el 2026-10-07: `POST /sessions/<sid>/kill` con confirmación, que ejecuta la PC dueña (`lienzo/kill_agent.py`).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 13. Gravedad: media.

- [x] Latencia entre PCs: un pedido mínimo a la otra PC tarda ~86 ms (mediana, p95 136 ms) contra 2,5 ms
  local; la pantalla de una tarjeta remota, ~470 ms. Cada pedido abre una conexión TCP nueva y firma
  con HMAC. Idea: conexión persistente (keep-alive) por peer y cachear `screen` unos 500 ms.
  - **Cerrado el 2026-10-10:** Conexiones HTTP reutilizables por peer desde el 2026-10-07 (cierre de implementación). Queda medir por LAN con la otra PC (ítem de Chrome remoto).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 14. Gravedad: media.

- [x] El SSE del peer se corta y reconecta cada ~15 s (`peer GET /peer/events` en el log cada 15 s).
  Funciona, porque cada reconexión trae el snapshot entero, pero es tráfico de más y una ventana en
  la que el espejo se reemplaza. Hay que ver si el server corta el stream a propósito.
  - **Cerrado el 2026-10-10:** Causa: el timeout de lectura del cliente. `SSEClient` lo cambia después de conectar (verificado el 2026-10-07).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 15. Gravedad: media.

- [x] **`launch_roots` no se ve desde la otra PC**: `peers.json` no lo trae y no hay forma de saber qué
  carpetas permite un peer sin intentar lanzar. Mostrarlo en `GET /peers`.
  - **Cerrado el 2026-10-10:** `GET /peers` trae `launch_roots` en la salud de cada PC desde el contrato de capacidades (2026-10-07; `tests/test_health.py`).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 16. Gravedad: media.

- [x] Traspasar un encargo entre PCs: copiar y pegar trabajo entre tarjetas funciona dentro de una
  PC; entre PCs no hay forma de mover un encargo a una tarjeta de la otra.
  - **Cerrado el 2026-10-10:** Implementado el 2026-10-07 (traspaso de trabajo entre PCs, cierre de implementación).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 19. Gravedad: media.

- [x] Persistir las reglas cruzadas si la otra PC reinicia: una regla vive en la PC del `from`; si
  esa PC reinicia el lienzo, hay que ver que sobreviva (hoy se guardan en `~/.lienzo`, falta probarlo
  con un reinicio real).
  - **Nota del 2026-10-10:** la regla de qué se conserva al arrancar quedó nombrada (`server.conservar_regla`) y probada releyendo `rules.json` (tests/test_pendientes_tanda3.py): la regla hacia otra PC sobrevive aunque su destino todavía no se vea. Falta el reinicio real en la otra PC.
  - **Cerrado el 2026-10-10:** reinicio real en ar-it33940: la regla `on_stop` de su coda (`e3e32f37`) hacia una sesión
    de la otra PC siguió en `GET /rules` (vive en ar-it33940, la PC del `from`) después de reiniciar su server dos veces.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 20. Gravedad: media.

- [ ] Pruebas reales pendientes (solo se probaron con transportes simulados): recuperación cuando una
  tarjeta remota ya no existe, y el reintento ante conexión rechazada.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 21. Gravedad: media.

- [x] Detectar el lienzo viejo de la otra PC por capacidades: hoy se reconoce por el texto «ruta
  desconocida» de la respuesta (`cablear` y el reenvío). Un campo de capacidades en el handshake
  (`/peer/health` o el emparejado) sería un contrato; el texto cambia sin avisar.
  - **Cerrado el 2026-10-10:** Contrato de capacidades en la salud (`protocol.CAPABILITIES`) desde el 2026-10-07; el 2026-10-10 la réplica de memoria también lo consulta (`memoria.replica`, tests/test_pendientes_tanda1.py).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 22. Gravedad: media.

- [x] **`xpc` + `purge_stale_xpc` con hilo y reloj fijo**: la purga corre en un hilo con un reloj fijo y
  una regla hacia otra PC solo guarda el flag `xpc`. Guardar `to_pc` en la regla y conciliar por peer
  al aplicar su snapshot: hoy un peer apagado frena la purga de las reglas hacia los demás.
  - **Cerrado el 2026-10-10:** Las reglas hacia otra PC guardan su PC y se concilian por peer al aplicar su snapshot (2026-10-07).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 23. Gravedad: media.

- [x] El espejo se reconcilia por rebote: una tarjeta fantasma se detecta cuando un envío vuelve con
  `unknown_session` (`mirror.forward` → `_tarjeta_fantasma`). Debería reconciliarse con un snapshot
  periódico o una secuencia en el SSE, no esperar a que alguien escriba.
  - **Cerrado el 2026-10-10:** Snapshots periódicos con protección ante eventos nuevos (2026-10-07).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 24. Gravedad: media.

- [x] **El enrutado owner→forward está repetido en ~10 handlers de `lienzo/server.py`** (`_route_session`
  + `mirror.MIRROR.forward` en cada ruta de `/sessions/<id>/...`): una sola función `route_or_local`.
  - **Cerrado el 2026-10-10:** `atender_accion` y `ACCIONES_SESION` centralizan las acciones de los dos listeners (verificado el 2026-10-07).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 25. Gravedad: media.

- [x] **`restorables_all` y `cablear` consultan en serie**: una PC lenta o caída suma su timeout al de las
  demás. Paralelizar las consultas por peer.
  - **Cerrado el 2026-10-10:** `restorables_con_fallas` usa `fan_out` paralelo (2026-10-07) y `cablear` crea las reglas en paralelo desde el 2026-10-10 (tests/test_pendientes_tanda1.py).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 26. Gravedad: media.

- [x] Timeout de acciones lentas por sufijo de ruta (`SLOW_ACTIONS`, `RESTORE_ACTION` y
  `_timeout_para` en `lienzo/federation.py`): una ruta nueva lenta se olvida y cae en los 5 s.
  Pasar el timeout como parámetro de `forward`.
  - **Cerrado el 2026-10-10:** `forward` recibe el timeout explícito (2026-10-07).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 27. Gravedad: media.

### UI

- [x] La tarjeta se queda en «Te necesita» con un permiso que ya no existe (medido el 2026-10-02): la tarjeta del Claude del gestor
  mostró durante unas 16 horas «Pide permiso» con el comando de un ruff de un subagente, desde un aviso (Notification) de las 05:06,
  aunque en su terminal no había ningún cartel. Ese permiso lo había aprobado yo hacía horas y la marca no se limpió. Confunde a
  quien mira el tablero y a la coordinadora, que gasta consultas en revisar. Los permisos de los subagentes (forks) de Claude Code
  salen en la terminal del Claude principal y el tablero no los distingue. Idea: cuando el estado dice permiso en la terminal
  y la pantalla ya no muestra el cartel («Do you want to proceed?» o «Enter confirm»), limpiar `needs` y volver al estado real.
  - **Cerrado el 2026-10-10:** Se limpia cuando la pantalla ya no muestra el cartel y nunca ante un fallo de lectura (`tests/test_mejoras.py::test_old_terminal_permission_requires_visible_prompt`).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 6. Gravedad: media.

### Conocimiento por proyecto

- [ ] Replicar la base de conocimiento entre PCs con un protocolo explícito de propiedad,
  concurrencia y recuperación. El código de las etapas 1 a 5 de v5 §9 usa la base local de la
  PC que registra los encargos; un pull de Git no transfiere esa base. Se conservan todas las
  revisiones de informes y los duplicados se sugieren sin fusionarlos automáticamente.

  Origen: v5 §9. Gravedad: media.

  Nota del 2026-10-09: diseño en `docs/propuesta-memoria-2026-10-08/anexo-c-replica.md` e
  implementación en `lienzo/replica.py` (cada PC trae de sus pares los cambios nacidos allá, por
  `/peer/conocimiento`, con cursores transaccionales; choques y duplicados para la coordinadora).
  10 pruebas con dos bases simuladas en un proceso. Falta probarlo entre las dos PCs reales.
  - **Nota del 2026-10-10:** primera réplica real: con las dos PCs en db12f5e, esta PC trajo de ar-it33940
    «replica con dee050ccab4f: 9 aplicados» (12:00:21, en `lienzo.log`). Falta ver el sentido inverso en el log de
    ar-it33940 y un choque real.

- [x] **Decidir qué PC es dueña de la base de cada proyecto mientras no haya base compartida.**
  Propuesta, sin decidir (pedido de la ronda 3):
  - Opción A, ninguna dueña (lo que hace hoy la réplica del anexo C): cada PC escribe en su base y
    trae lo de las demás; los choques quedan para la coordinadora. Lo bueno: no depende de que una
    PC esté prendida. Lo malo: puede haber choques y duplicados para revisar.
  - Opción B, dueña la PC de la carpeta (la del remote más viejo): las demás le reenvían las
    escrituras. Sin choques, pero si esa PC está apagada, las otras no escriben.
  - Opción C, dueña la PC donde corre la coordinadora de la ronda: lo natural mientras dura una
    ronda, pero cambia de ronda a ronda y un frente de otra PC escribe por la red.
  - Recomendación: A, que ya está implementada. B o C sólo si en uso real los choques resultan
    frecuentes. Las capturas no chocan (son inmutables); los choques posibles son veredictos dados
    a la vez en dos PCs.
  - **Decidido por Ariel el 2026-10-10: opción A, ninguna dueña.** Revisar sólo si los choques
    resultan frecuentes en uso real.
  - **Cerrado el 2026-10-10:** Decidido (opción A).

- [x] **Decidir la retención de las revisiones de informes y de las capturas.**
  Medido el 2026-10-10: un día cargado (1525 capturas, 990 KB de texto) suma 2,0 MB a la base;
  las revisiones de informes son unos 10 KB cada una. Propuesta, sin decidir:
  - Opción A, todo para siempre: del orden de 0,3 a 0,7 GB por año por PC en el peor caso.
  - Opción B, revisiones para siempre y capturas por 180 días, con un respaldo
    (`POST /conocimiento/<p>/respaldo`) antes de borrar: el conocimiento declarado no se pierde y
    la prosa vieja queda en el respaldo.
  - Opción C, recortar el texto de las capturas viejas a su primera línea y conservar hash y fecha.
  - Recomendación: A por ahora (el volumen es chico) y medir otra vez a los tres meses; si pasa
    de 1 GB, B. Las revisiones de informes conviene conservarlas siempre: son la procedencia de
    lo declarado.
  - **Decidido por Ariel el 2026-10-10: opción A, todo se conserva por ahora.** Queda volver a medir
    el tamaño de las bases hacia enero de 2027.
  - **Cerrado el 2026-10-10:** Decidido (opción A); volver a medir hacia enero de 2027, como dice la nota.

### Otros

- [x] Identidad de Codex en el barrido (hallazgo del cierre, 2026-10-07): `codex.exe` de
  sandbox/helpers podía ocupar una tarjeta con transcripción de una CLI ya cerrada. Se filtran
  subcomandos no interactivos y flags internos `--codex-run-as-*`, y la comprobación de vida
  también lee el comando. Si no se puede leer, no se supone una TUI. Focal: 51 pruebas pasan;
  no se mataron helpers ni procesos de aplicaciones. El PID 26924 ya no existía al verificar.
  Corrida backend posterior `2026-10-07T06-16-42.580Z-16520`: 993 pruebas pasan.
  Revisión y cinco roles en resultados; baseline sin aprobar, compuerta exit 2. Estas notas
  documentales se agregan después de medir; el código probado no cambia.
  - **Cerrado el 2026-10-10:** Implementado con pruebas focales el 2026-10-07; la batería del 2026-10-10 (1313 pruebas) las incluye.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 2. Gravedad: media.

- [x] Validación con `pruebas-agenticas`: obligatoria por la preferencia global de Ariel.
  Reutilizar la configuración del repo; registrar los cinco roles, logs y veredicto sin fijar baseline.
  - **Cerrado el 2026-10-10:** Compuerta PASS el 2026-10-10 sobre daf92bb: 7 de 7 casos y 5 de 6 mutantes muertos, con requisitos y casos aprobados.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 4. Gravedad: media.

- [x] **Coda: `stop_reason` del Stop sin mirar** (medido el 2026-10-02): el `Stop` trae `stop_reason` y el doc solo muestra
  `turn_complete`; ver qué otros valores existen (respuesta cortada que continúa, error) y usarlos en vez de adivinar.
  - **Cerrado el 2026-10-10:** Implementado el 2026-10-07 (lectura de `stop_reason` de CODA).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 7. Gravedad: media.

- [ ] **Probar `PreCompact`/`PostCompact` con una coda real**: solo hay prueba con eventos simulados, y falta correr
  `install.py` en las dos PCs para que coda los mande (toca `~/.coda/config.json`).
  - **Nota del 2026-10-10:** en esta PC los hooks ya estaban y con una coda real (CODA 1.4.0) el PreCompact llegó. El
    PostCompact no se vio: con cinco vueltas cortas coda contesta «Too few messages for compaction» y aborta sin mandarlo (ni
    Stop), lo que dejaba la tarjeta trabada; arreglado (`sessions.coda_compactacion_abortada`). Falta una compactación que
    sí ocurra (conversación larga) y la otra PC.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 8. Gravedad: media.

- [x] **`--coda-home DIR` aísla la configuración de coda** (está en `coda --help`): sirve para lanzar con `--model` sin pisar el
  modelo por defecto de la PC (ver el punto de `--model`). Falta ver cómo conserva el login.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 9. Gravedad: media.
  - **Cerrado el 2026-10-10:** probado con `coda --globant --coda-home C:\Users\ArielLevy\.coda-prueba-home`. Una carpeta
    nueva arranca en el alta (log: «the coda home is not set up (missing .secrets and/or empty global config)»); con
    `--globant` se elige el entorno (Clients) y se pega la clave una vez, que queda en `<carpeta>/.secrets`, y hay que
    reiniciar coda para que cargue el proveedor (antes da 401). Después contestó por el DGX. Cambiar el modelo ahí
    escribió el `config.json` de esa carpeta (`globant_dgx/Qwen3.8-27B`) y el de `~/.coda` siguió en
    `globant_dgx/GLM-5.3-Flash`: aísla el default. Sin `--globant` el alta no ofrece Globant. Que `launch.py` lo use solo
    queda como mejora, sin pedido.

- [ ] **La herramienta `read` de coda se traba** (medido el 2026-10-02): se evita (el adjunto a un coda se lee con
  el shell y los mensajes cortos se tipean directo), pero la causa sigue en coda: avisar a quien lo mantiene.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 11. Gravedad: media.

- [x] **`--model` en coda cambia el modelo por defecto de la PC** (medido el 2026-10-02): `coda --model X` se
  documenta como «para esta corrida», pero el `config.json` de esa PC pasó de `globant_dgx/Qwen3.8-27B` a
  `globant_dgx/GLM-5.3-Flash` a las 00:52:18, justo al lanzar el primer coda con GLM, y las sesiones
  lanzadas después sin modelo ya mostraban GLM. Efectos: se pisa el default del usuario sin que lo sepa
  y las comparaciones entre modelos no valen (la medición «Qwen contra GLM» de esa noche fue GLM contra
  GLM). Ideas: que `lanzar` con `model` avise si el agente es coda, que el lienzo lea el default antes
  y lo restaure al terminar el lote, o lanzar con un `--coda-home` propio para aislar la configuración
  (hay que ver cómo conserva el login).
  - **Cerrado el 2026-10-10:** Desde el 2026-10-10 lanzar una coda con `model` devuelve un `aviso` (tests/test_pendientes_tanda2.py). Aislar con `--coda-home` sigue en su ítem.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 12. Gravedad: alta.

- [x] (Revisar: desactualizado) «Coda no tiene hooks»: el 2026-10-02 las codas figuran `hooked=True`; antes nacía como tarjeta de barrido (`pid-NNNN`, sin título ni
  transcripción), cambia de id, y su estado no refleja que está trabajando. Un hook de coda daría
  título, estado y `last_reply` confiables.
  - **Cerrado el 2026-10-10:** Desactualizado: las codas figuran `hooked=True` desde el 2026-10-02.

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 17. Gravedad: media.

- [x] Un solo modelo para todos los codas: Qwen en el DGX atiende de a poco; con 5 codas a la vez
  todos quedan en «Waiting for model». El coordinador tiene que escalonar el trabajo, no repartirlo
  en paralelo sin límite. `capacidad` mide RAM, no el cupo del modelo.
  - **Cerrado el 2026-10-10:** `coordinar.capacidad(pc, n, agent="coda")` cuenta las codas que ya corren en esa PC y deja entrar a lo sumo dos (`CODAS_EN_PARALELO`); lo demás se escalona (`tests/test_coordinar.py`, skill actualizado).

  Origen: `MEJORAS.md`, «Pendiente (con evidencia)», ítem 18. Gravedad: media.

### Notas de implementación y aceptación trasladadas

#### Cierre de implementación del 2026-10-07

Las casillas se conservan pendientes de aceptación. Implementado en esta ronda:
limpieza de permisos con prompt visible (sin limpiar ante fallo de lectura), lectura
de `stop_reason` de CODA, contrato de capacidades y `launch_roots`, snapshots periódicos
con protección ante eventos nuevos, conciliación de reglas por PC, conexiones HTTP
reutilizables, timeout explícito, traspaso de trabajo entre PCs y cierre forzado Windows
con confirmación e identificación del proceso. `POST /run` exige un comando nombrado
en `run_allowlist` de la PC destino y una carpeta dentro de sus `launch_roots`; no se
habilitó ninguna lista ni se ejecutaron comandos remotos reales.

Validación final y revisión: evidencia en `pruebas-agenticas/resultados/` (ignorada por
Git), corrida `2026-10-07T06-02-08.125Z-26940`: cinco suites con código 0; 981 pruebas
backend y 117 UI pasan, además de lint, build y unitarias frontend. Cinco roles registrados
secuencialmente en `roles.json`; revisión en `revision-cierre.json`. Falta baseline aprobado:
el runner sale con 1 y la compuerta con 2; no se certifica PASS ni se aprueban propuestas.
Sin mutaciones ejecutadas. Esta nota documental se agrega después de la medición.

Siguen pendientes las verificaciones con CODA real y dos PCs, aislamiento de login/modelo
con `--coda-home`, capacidad del servidor de modelos, instalación NUC desatendida y
paralelización del cableado. La integración visual de specs/SDD de Kiro no está implementada.
La documentación de Kiro V3 confirma que ofrece un agente Spec nativo; eso no acredita
su integración en Lienzo. El canal cifrado de secretos ya estaba implementado, como
consta en «Hecho»; se quitó la propuesta duplicada.

Checklist conservado por pedido de Ariel (2026-10-07). Las casillas quedan pendientes de
su aceptación; las notas distinguen implementación, pruebas y verificaciones externas.

Verificaciones del 2026-10-07: `restorables_con_fallas` ya usa `fan_out` paralelo;
`atender_accion` y `ACCIONES_SESION` ya centralizan las acciones de ambos listeners;
`SSEClient` ya cambia el timeout de lectura después de conectar; CODA ya registra
`PreCompact` y `PostCompact` en `install.py`. No equivalen a pruebas reales en ambas PCs.
La PC `ar-it33940` figura desconectada en `/peers`; no se puede verificar allí en vivo.

## Pendientes del triage de docs

### Seguridad

- [x] Restringir los datos de GET /health antes de autenticar, también por túnel.
  - Evidencia: lienzo/server.py: Handler.do_GET, rama health anterior a _authed; devuelve sessions, pending y ts.
  - Origen: `docs/pentest-2026-09-07.md, B1` (historial de Git). Gravedad: **media**.
  - **Cerrado el 2026-10-10:** Sin autenticar (o por el túnel) `/health` sólo dice `ok` y `ts` (`salud_publica`, tests/test_pendientes_tanda1.py; verificado en vivo con `CF-Connecting-IP`).

- [x] Definir controles de sesión web y una vista para listar y revocar sesiones activas.
  - Evidencia: lienzo/auth.py: check sólo comprueba token y vencimiento; login guarda ip/ua y SESSION_DAYS vale 7. logout no ofrece administración de otras sesiones.
  - Origen: `docs/pentest-2026-09-07.md, B4` (historial de Git). Gravedad: **media**.
  - **Cerrado el 2026-10-10:** `GET /auth/sessions` y `POST /auth/sessions/<id>/revoke`, con la lista y el botón Cerrar en el diálogo de Authenticator (tests/test_pendientes_tanda2.py).

- [x] Agregar cuota de adjuntos por sesión.
  - Evidencia: lienzo/server.py: MAX_ATTACH limita cada pedido; lienzo/sessions.py: limpieza por ATTACH_MAX_DAYS, sin cuota acumulada por sesión.
  - Origen: `docs/pentest-2026-09-07.md, B5` (historial de Git). Gravedad: **media**.
  - **Cerrado el 2026-10-10:** 200 MB por sesión en `/attach`, 413 al pasarse (tests/test_pendientes_tanda2.py).

- [x] Acotar hilos y conexiones SSE simultáneas.
  - Evidencia: lienzo/server.py: QuietServer hereda ThreadingHTTPServer; el servicio SSE no tiene cupo global. El cupo MAX_SESSIONS de Chrome no cubre SSE.
  - Origen: `docs/pentest-2026-09-07.md, B6` (historial de Git). Gravedad: **alta**.
  - **Cerrado el 2026-10-10:** Tope de 64 streams (`MAX_SSE`), 503 con `Retry-After` al pasarse (tests/test_pendientes_tanda2.py).

- [x] Validar request_id antes de construir la ruta de respuesta a permisos.
  - Evidencia: lienzo/sessions.py: answer_pending usa os.path.join(ANSWERS, f"{request_id}.json") tras buscar el pendiente, sin validar el identificador cargado desde disco.
  - Origen: `docs/pentest-2026-09-07.md, I2` (historial de Git). Gravedad: **baja**.
  - **Cerrado el 2026-10-10:** `answer_pending` rechaza con 400 lo que no sea `[A-Za-z0-9_-]{1,100}` (tests/test_pendientes_tanda1.py; verificado en vivo).

### Multiplataforma

- [x] Resolver PID y destino del hook en Unix.
  - Evidencia: lienzo/hook.py: find_agent_pid usa procinfo.proc_info; lienzo/procinfo.py devuelve valores vacíos fuera de Windows. Sin TMUX_PANE en lienzo/*.py; el destino se obtiene por barrido.
  - Origen: `docs/plan-multiplataforma-2026-09-08.md` (historial de Git). Gravedad: **media**.
  - **Cerrado el 2026-10-10:** fuera de Windows `procinfo.proc_info` lee `/proc` (o `ps` en macOS) y el hook manda `TMUX_PANE`, que pasa a ser el `target` de la tarjeta de tmux (tests/test_pendientes_tanda3.py). Sin corrida en un Linux real, que sigue en «Verificar el servidor nativo».

- [x] Hacer portable --remote y el arranque de cloudflared.
  - Evidencia: lienzo/server.py: CLOUDFLARED apunta a Program Files (x86)/cloudflared/cloudflared.exe; tunnel_loop pasa creationflags=0x08000000 sin condición POSIX.
  - Origen: `docs/plan-multiplataforma-2026-09-08.md` (historial de Git). Gravedad: **alta**.
  - **Cerrado el 2026-10-10:** `cloudflared` del PATH y `creationflags` sólo en Windows. Probado en Windows; Linux y macOS siguen en «Verificar el servidor nativo».

- [x] Traducir rutas de adjuntos de Windows para los agentes de WSL.
  - Evidencia: lienzo/sessions.py: compose_send y run_send pasan rutas locales; no hay conversión con wslpath en lienzo/*.py.
  - Origen: `docs/plan-multiplataforma-2026-09-08.md` (historial de Git). Gravedad: **media**.
  - **Cerrado el 2026-10-10:** `tmux.ruta_wsl` traduce lo que se tipea a un agente de WSL (`/mnt/c/...`) (tests/test_pendientes_tanda2.py).

- [x] Informar backend y fuentes activas en /health.
  - Evidencia: lienzo/server.py: Handler.do_GET, rama health, sólo devuelve ok, sessions, pending y ts; lienzo/backend.py distingue fuentes.
  - Origen: `docs/plan-multiplataforma-2026-09-08.md` (historial de Git). Gravedad: **baja**.
  - **Cerrado el 2026-10-10:** `/health` autenticado o local trae `fuentes` (`win32`, `tmux`) (tests/test_pendientes_tanda1.py).

- [x] Descubrir y direccionar varias distros de WSL.
  - Evidencia: lienzo/tmux.py: _PREFIX = ["wsl.exe"] en Windows, sin selección de distro; backend.proc_key distingue fuente y PID, no distro.
  - Origen: `docs/porting-linux-2026-09-08.md` (historial de Git). Gravedad: **baja**.
  - **Cerrado el 2026-10-15:** `backend.py` consulta los panes de cada distro y `distro` va en la tarjeta (spec `docs/WSL.md`, 538ac22).

- [ ] Verificar el servidor nativo en Linux y macOS, incluido emparejamiento.
  - Evidencia: lienzo/backend.py: sweep; lienzo/tmux.py: _ps_all. El documento de origen registra simulación de plataforma y pruebas desde Windows/WSL, no una corrida nativa completa; esta revisión no ejecutó esas plataformas.
  - Origen: `docs/porting-linux-2026-09-08.md, Integrado a main; README.md, Limitaciones` (historial de Git). Gravedad: **media**.

### Chrome remoto

- [ ] Verificar en vivo la aprobación de conexión del Chrome habitual de Globant.
  - Evidencia: lienzo/browser_consent.ps1 y lienzo/browser_host.mjs: approveChrome implementan el pedido; docs/code-review-2026-10-07.md deja expresamente pendiente la prueba de ese perfil.
  - Origen: `docs/code-review-2026-10-07.md` (historial de Git). Gravedad: **media**.

- [ ] Sincronizar el portapapeles en modo ventana.
  - Evidencia: lienzo/browser_window.py no implementa clipboard. web/src/components/RemoteBrowser.tsx: onPaste manda texto local, pero eso no sincroniza el portapapeles remoto; el copy por CDP es otro modo.
  - Origen: `docs/code-review-2026-10-07.md` (historial de Git). Gravedad: **media**.

- [ ] *(Opcional, 2026-10-15: Ariel lo descartó por ahora, el canal WebSocket anda bien.)* Evaluar transporte no ordenado para movimientos mediante WebRTC/UDP.
  - Evidencia: lienzo/browser_stream.py y lienzo/ws.py usan WebSocket ordenado; no hay transporte WebRTC/UDP para la entrada.
  - Origen: `docs/code-review-2026-10-07.md, Canal vivo` (historial de Git). Gravedad: **baja**.

- [ ] Medir latencia sostenida por LAN después del canal WebSocket.
  - Evidencia: lienzo/browser_stream.py: serve_viewer; docs/code-review-2026-10-07.md registra cuadros locales y la caída de ar-it33940 antes de medir el canal nuevo por LAN. No hay medición nueva en este encargo.
  - Origen: `docs/code-review-2026-10-07.md, Detective del canal vivo` (historial de Git). Gravedad: **media**.

### Federación

- [x] Incluir conexiones del espejo en GET /links.
  - Evidencia: lienzo/server.py: Handler.do_GET devuelve links.snapshot(); GET /rules sí agrega mirror.MIRROR.rules().
  - Origen: `docs/ronda2/` (historial de Git). Gravedad: **baja**.
  - **Cerrado el 2026-10-10:** `GET /links` suma `mirror.MIRROR.links()` (tests/test_pendientes_tanda1.py).

- [x] Unificar LIENZO_PEER_PORT entre pairing y el listener real.
  - Evidencia: lienzo/pairing.py lee LIENZO_PEER_PORT; lienzo/server.py no consulta esa variable para sus listeners.
  - Origen: `docs/ronda3/` (historial de Git). Gravedad: **baja**.
  - **Cerrado el 2026-10-10:** `--peer-port` toma por defecto `pairing._my_port()` (tests/test_pendientes_tanda1.py).

### UI

- [ ] Verificar un lanzamiento real en otra PC desde el selector de proyecto/PC del tablero; la UI está implementada y sus recorridos con fixtures pasan.
  - Evidencia: lienzo/server.py: accion_launch implementa POST /sessions/launch; la búsqueda de sessions/launch en web/src no tiene coincidencias.
  - Origen: `docs/ronda3/` (historial de Git). Gravedad: **media**.

## Alcance de la consolidación

Se trasladaron 27 casillas previas y 18 pendientes del cuerpo del triage. Su resumen decía
16: omitía la verificación nativa de Linux/macOS y la inconsistencia de LIENZO_PEER_PORT.
No se cerró ninguna casilla ni se aprobó un baseline. Las secciones «Plan» e «Ideas» de
MEJORAS.md quedan fuera de la edición autorizada de ese archivo; sus puntos se conservan allí.
