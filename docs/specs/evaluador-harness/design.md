# Diseño: mejoras de agentes CLI

Diseño aprobado por Ariel el 2026-10-12. Requisitos: requirements.md. Alcance inicial solicitado: Caveman para respuestas breves, RTK para comandos y Jev para sugerencias. REA excluida.

## Experiencia

- El menú del tablero ofrece «Mejoras de agentes» para ver disponibilidad y preferencias de esta PC. Caveman breve y RTK se pueden habilitar o deshabilitar para nuevos lanzamientos. No se activa el proxy de Caveman.
- En el panel de una sesión aparece «Mejoras»: muestra primero métricas locales y sugerencias, con evidencia por turno. «Consultar Jev» realiza una llamada paga explícita sobre una muestra revisable. No hay llamadas automáticas por SSE.
- La UI distingue instalado, disponible y habilitado. Sesiones que ya corren no reciben instrucciones ni reinicios automáticamente.

## Componentes

### lienzo/agent_improvements.py

Módulo de políticas y disponibilidad, sin dependencias externas. Lee preferencias desde un archivo propio bajo LIENZO_HOME y detecta RTK por ruta absoluta. El archivo contiene solo preferencias, nunca credenciales.

`status() -> dict`: preferencias, disponibilidad local y limitaciones por agente.

`configure(data: dict) -> dict`: valida campos booleanos permitidos y persiste atómicamente. Ningún argumento de comando arbitrario entra desde la UI.

`launch_instructions(agent: str, distro: str | None) -> str`: compone instrucciones breves que conservan idioma, comandos, números, errores, revisión y pruebas. Para RTK recomienda comandos explícitos compatibles y recuperación de diagnósticos completos. No altera herramientas internas Read/Grep ni fuerza un hook global.

### Lanzamiento

`launch.launch(cwd, title, agent, resume=None, model=None, distro=None)` conserva su interfaz. Agrega instrucciones con flags propios del agente y sin reemplazar instrucciones del proyecto:

- Claude, Pi y coda: --append-system-prompt, presente en su ayuda local.
- Codex: `-c developer_instructions=...` agrega instrucciones sin reemplazar el prompt base, según documentación oficial consultada. Se conserva la configuración de usuario/proyecto leída; WSL resuelve su CODEX_HOME y sus archivos a través de su propia distro. Si la configuración no es legible, se informa y no se reemplaza. No se afirma obediencia sin observar un agente real.
- Agente sin soporte demostrado: informar limitación en vez de modificar archivos globales.

`_launch_cmd` debe citar argumentos nuevos como datos y rechazar metacaracteres peligrosos; no insertar texto libre de UI en .cmd. `_launch_tmux` mantiene argv sin shell. No crear CLAUDE.md.

La disponibilidad de RTK en Windows no acredita que exista en WSL. Su ruta y versión se resuelven en el entorno donde correrá el agente. Si falta, se muestra un aviso sin impedir el lanzamiento.

### RTK y Caveman

Instalar una versión fija de RTK desde publicación oficial con verificación de integridad. Usar llamadas explícitas inicialmente: no sustituir todos los comandos de shell ni alterar hooks de otros plugins. Verificar que códigos de salida y diagnósticos originales siguen disponibles.

Caveman se incorpora únicamente mediante reglas de respuestas breves basadas en el skill inspeccionado, conservando licencia/atribución correspondiente si se distribuye texto. No instalar proxy, compresor de archivos, ni hooks adicionales. La preferencia del usuario y AGENTS.md prevalecen.

### lienzo/jev.py

Cliente stdlib HTTP para OpenRouter Decisions. Referencia: D:/Apps/chess/apps/api/tutor/jev.py; no importar código de chess ni añadir httpx al producto.

Credencial: origen localizado en /etc/chesstudia/nube.env (WSL Ubuntu), variable CHESSTUDIA_OPENROUTER_API_KEY. /etc/chesstudia/env no contiene esa clave. Se verificó su presencia sin mostrarla. La transferencia, autorizada por Ariel, copiará únicamente el valor a almacenamiento privado de Lienzo: DPAPI por usuario en Windows y archivo 0600 en plataformas POSIX. El navegador y /config no reciben la clave.

`decide(evidence: dict) -> dict`: un pedido, timeout explícito, sin reintentos. Endpoint https://openrouter.ai/api/alpha/decisions; modelo fijo configurado; provider zdr=true/data_collection=deny. Confirmar contrato actual antes de primera llamada.

Pregunta choice limitada a rtk, codegraph, graphify, ponytail, ninguna y datos_insuficientes. Caveman breve ya es preferencia explícita y no requiere juicio semántico para activarla. Jev no instala, ejecuta, aprueba permisos ni determina que el código es correcto.

Validar respuestas, opciones y probabilidades finitas/rango/suma. Exigir modelo efectivo, id y usage.cost; costo ausente no equivale a cero. Guardar solo decisión, evidencia seleccionada, uso y costo; sin cabeceras, secretos ni entorno ambientado. Errores HTTP, timeout, falta de credencial y respuesta inválida se muestran en UI sin volcar cuerpos sensibles.

## API y UI

- GET /agent-improvements: estado público sin secretos.
- PUT /agent-improvements: preferencias de esta PC; autenticación y CSRF existentes.
- GET /sessions/{sid}/improvements: resumen determinista de muestra; resolver propietario antes de leer una sesión.
- POST /sessions/{sid}/improvements/jev: petición explícita, con muestra y autorización de costo visibles. La PC dueña hace el juicio; una sesión remota no se analiza con datos locales inventados.

El panel usa un componente por session_id. Cancela/ignora respuestas tardías al cambiar de sesión. La configuración local no aparenta cambiar preferencias de otras PCs.

## Datos observados

Contar herramientas con resultado conocido, errores explícitos y resultados ausentes por separado. Bytes/caracteres de salida no se presentan como tokens. Lecturas repetidas son una señal de investigación, no una prueba automática de desperdicio. Ventanas y truncamiento se muestran.

Sin validación funcional, calidad del trabajo queda desconocida. Las reglas locales y Jev proponen; no marcan tareas o baselines aprobados/completados.

## Verificación

Recorrido Explorer → Analyser → Designer → Executor → Detective secuencial, con registro de roles y sin aprobar baselines.

- Launch: conservar flags, reanudación, títulos, paths con espacios, Windows y WSL; no inyección de comandos.
- Preferencias: tipos inválidos, escritura atómica y ausencia de secretos en API.
- Jev: transporte simulado para errores, respuestas inválidas, costo ausente, timeout y proveedor no admitido; una llamada real acotada para comprobar conectividad, sin confundirla con calidad del clasificador.
- UI: guardar/desactivar preferencias, datos insuficientes, sesión remota caída, cambio de sesión con petición pendiente y error visible.
- RTK: comparar comando propio exitoso y fallido con/sin RTK, recuperar salida original y verificar códigos.
- Caveman: verificar instrucciones en el lanzamiento; no afirmar que un agente las obedeció sin una sesión real.

Code review del diff final y checks de las áreas tocadas. Beneficio económico o calidad solo se declara con casos comparables medidos.

## Pendiente antes de código

Diseño y tareas aprobados por Ariel el 2026-10-12. RTK 0.51.0 instalado con hash oficial; preferencias breve/RTK habilitadas en esta PC y credencial transferida a DPAPI. Jev respondió en prueba sintética con modelo efectivo typesafe/jev-1.13-20260917 y costo USD 0.00002268. Sin reinicios del servidor principal: la integración de código queda a cargo de la coordinación. Ningún baseline o tarea se marcó aprobado/completado por cuenta propia.
## Aprendizaje oportunista autorizado (2026-10-12)

Integración local autorizada por coordinación; presupuesto de llamadas nuevas = cero. No hay automatización externa. Primera entrega: análisis determinista de memoria, propuestas y cola manual por proyecto. Experimentos CLI permanecen bloqueados hasta presupuesto y oráculos aprobados.

- `optimization_activity.py`: GetLastInputInfo de Windows, ticks DWORD con wrap, CPU/memoria de health, actividad del panel y sesiones/permisos locales. Desconocido bloquea. Dos muestras aptas consecutivas; 180 s de quietud, CPU <=35%, reserva 1.5 GB. Son límites conservadores iniciales, no umbrales calibrados.
- `optimization_queue.py`: archivo operacional local atómico, IDs/estados solamente, máximo 100 trabajos. Sin réplica ni ejecución remota: cada encolado pertenece a esta PC. Un trabajo activo; estado interrumpido requiere revisión, nunca reintento automático. Pausa conserva cursor; finalizar no genera otros trabajos.
- `optimization_memory.py`: lee <=30 incidentes recientes del proyecto en la base existente. Hipótesis = decision propuesta con clase hipotesis_optimizacion; vínculo motivada_por a incidente, idempotencia por fuente/perfil/contexto. No copia textos, secretos ni transcripciones. Metadatos: agente/modelo/PC conocidos, condiciones OFF/ON, apoyo empírico desconocido, vencimiento 7 días, resultado no ejecutado y rollback al perfil previo. Incidente no acredita beneficio. Solo candidatos shell→RTK y exploración→CodeGraph; sin candidato produce evidencia de datos insuficientes. Lectura/escritura usan una transacción con espera SQLite 250 ms y checkpoints; máximo cooperativo 30 s, no límite duro ante bloqueo del SO.
- `optimization_scheduler.py`: un hilo del servidor cada 2 s, una etapa pequeña por tick, sin locks del estado durante SQL. GET estado; POST encolar/pausar/actividad con autenticación/CSRF. Cola solo local; la actividad remota del panel también bloquea. No API de comandos, presupuestos o agentes automáticos en esta etapa.
- UI integrada en Mejoras de agentes: proyectos existentes, encolar análisis, pausar, motivo y referencias propuestas. No permite aprobar una creencia; el veredicto usa el flujo de memoria ya existente.

No hay segunda memoria semántica. Se reutilizan decisiones, incidentes y evidencia de conocimiento.sqlite. No cambia el esquema ni se inventa tipo belief. No se aplica automáticamente una propuesta. La vigencia exige revisar versiones/contexto antes de experimentar; no extrapolar entre proyectos/PCs/modelos. Las referencias de resultado apuntan a memoria, no al archivo operacional.

Comparación propuesta: brief/RTK 00,10,01,11; piloto Codex Windows con dos tareas representativas (trazado de rutas y reparación aislada de contrato), ocho ejecuciones aún no autorizadas. Misma copia congelada, modelo/versión/permisos/contexto, orden balanceado y oráculo previo; calidad primero, luego tiempos, errores/reintentos, herramientas y tokens/costo solo medidos. Codex reporta consumo acumulado: no sumar turnos. Brief añade 372 caracteres; ambos 886, no equivalen a tokens. WSL: Codex/Pi presentes, RTK ausente; no inventar celda RTK ON. Kiro sin soporte de instrucciones demostrado. Precio de agentes desconocido: requiere presupuesto explícito; costo de este análisis local USD 0 en servicios externos.

Pruebas: transiciones de cola/reinicio, exclusión concurrente, datos corruptos visibles, actividad/CPU/memoria desconocidas bloquean, retorno de usuario pausa sin matar procesos, idempotencia y vínculos en memoria real temporal, límites y no llamadas pagas. UI y Handler reales aislados; ninguna mutación sobre archivos compartidos ni aprobación de baseline.
## Contabilidad de ronda (autorizada 13:18)

`optimization_budget.py`: ledger SQLite operacional (no memoria semántica) en LIENZO_HOME, autoridad única de la ronda. Política verificable en budget-policy.json: USD 2 total (Ariel redujo a las 13:24), costo previo confirmado USD .00002268, intento HTTP400 anterior de monto desconocido. No imputarlo cero ni multiplicar saldo por PC. Transacciones BEGIN IMMEDIATE, Decimal como texto, claves idempotentes. La reducción queda persistida: una política antigua no vuelve a subir el tope. Reservas: held→settled con costo informado; errores quedan held, no devolución automática. Cota excedida → breach y bloquear nuevos pagos. Unknown histórico bloquea cualquier nueva reserva paga. Política/ledger inválidos bloquean.

`optimization_cost.py`: adaptadores declarados. CLI existente: máximo no comprobado → bloqueado. Jev: .001 solo estimación; sin contrato de máximo por petición → bloqueado, aunque haya consentimiento de UI. Prueba local RTK de comandos fijos: USD 0 de servicios, permite controles locales; no es experimento de agente ni calidad Caveman. Proveedores requieren cota documentada/contexto/token/fees vigentes antes de habilitar envío. No modificar límite de la clave compartida Chesstudia.

Jev integra la reserva en el único punto de red (decide), incluyendo el script de comprobación, para evitar bypass desde UI/ops. Guardado fallido posterior no pierde cobro confirmado; costo inválido o HTTP/timeout retiene responsabilidad. Estado del presupuesto se muestra junto al scheduler y el juez explica por qué está bloqueado. Local análisis continúa sin gasto, no lanza optimizaciones ni agentes automáticamente.

OFF/ON local autorizado: ejecutar los mismos tests de contrato reales del repo (memoria y bloqueo de actividad) con pytest directo y RTK pytest; una repetición por perfil Windows, comandos fijos y archivos congelados por hash, tiempo/códigos/diagnósticos, recuperación proxy. Tokens/costos de agente = null y calidad = oráculo de tests, no calidad del coding agent. No ejecutar automáticamente mientras haya trabajo/usuario; no prometer suspensión segura de CLI sin adaptador.
## Cierre funcional: automática local y lectura pura

La aprobación 135503 reemplaza la primera etapa de solo cola manual: scheduler recorre proyectos en forma circular, uno por tick apto; obtiene snapshot de <=30 incidentes (id/fecha/datos/origen) y su hash. Solo incidentes: decisiones/evidencia propias no disparan nuevas versiones. Cola guarda versión/IDs/origen/hora; no reencola una versión ya registrada, cooldown por proyecto 120 s y máximo100. Vacío o fallo de lectura no encola. No llama a modelos ni abre CLIs.

Revalidación: después de sources/snapshot, antes de propose y tras conservar su transacción confirmada. Actividad/permisos/pausa desconocidos bloquean. Transacción en curso no se interrumpe por la UI: termina o falla según límites SQLite existentes. Timer de polling2s; SQLite espera250ms por lock y progress handler1s, escritura atómica tiene reintentos. Esto NO es máximo absoluto de reacción: el SO/FS y operaciones en curso añaden demora. Máximo real bajo inactividad productiva no medido; host ocupado impidió ensayo. Los tests deterministas prueban pausa en cada frontera, no latencia física de teclado.

GET: Budget.status usa conexión mode=ro, no inicializa; lectura de peer.json directa, sin reparación/rename de identidad corrupta. Scheduler/Queue se construyen sin guardar; la recuperación se persiste explícitamente en start. Start activa ledger y cola antes del bucle. Ledger ausente/identidad inválida bloquea pagos. Reserve/settle son escrituras transaccionales autorizadas, distintas de lectura de estado.
