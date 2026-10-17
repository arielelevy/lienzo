# Piloto48h autorizado, pendiente de evaluación

Registro histórico del 2026-10-12. Sus estados, importes y autorizaciones corresponden a esa ronda;
no son un estado operativo verificado hoy ni una autorización nueva.
Contrato actual: [Aprendizaje](../../APRENDIZAJE.md). Las specs intermedias citadas en el cuerpo
se retiraron al consolidar; sus versiones originales permanecen en Git.

2026-10-12. USD2 TOTAL de la misma ronda, incluye manual/automático/histórico. Sin agentes CLI nuevos, sin modificar clave compartida, sin git/restart autónomo. Nuevas sesiones pueden recibir preferencias reversibles; perfil de CLI existentes desconocido sin evidencia de lanzamiento. No se declara ahorro causal entre tareas distintas ni se acepta una tarea por fin de turno.

## Histórico

GET autenticado /generation confirmó gen-dec-1791817912-L2TPZcw7ifWYEqwFFw1G: modelo typesafe/jev-1.13-20260917, TypeSafe, 2026-10-12T15:11:52.698Z, total_cost .00002268. El400anterior no dejó generationID/usage. GET /activity?date=2026-10-12 devolvió400; la documentación dice días UTC completados y clave administrativa, por lo que este resultado no concilia el evento.

GET /key a17:55:53UTC: usage .037418892, byok_usage0, limit50, remaining49.962581108, resetnull. Credencial DPAPI modificada15:05:17UTC, antes del40015:11:02UTC; huella SHA256 registrada por ops/verificar-cota.py, clave nunca mostrada. El script no cambia límites. [Fuente primaria](https://openrouter.ai/docs/api_reference/limits) define usage como créditos utilizados de toda la vida, separado de ventanas diarias/semanales/mensuales; limit_resetnull no reinicia. Se reserva TODO ese uso para el único400, incluyendo gasto ajeno como sobre-reserva. Costo real del400permanece null. Ninguna reserva histórica baja ni se libera automáticamente; unknown sin cota sigue bloqueando. Si la credencial fue modificada después del intento, activación bloquea por identidad histórica no acreditada. Esta evidencia presupone continuidad del archivo DPAPI y contabilidad del proveedor; no acredita factura individual ni ausencia de ajustes tardíos. La prueba de uso total permite una cota contable, no inferir costo0.

[Política primaria de errores](https://openrouter.ai/blog/insights/reliability-failover/) publicada antes del intento dice que malformed400 vuelve sin fallback y errores fallidos no se cobran, con excepciones429/parciales. Sirve como evidencia adicional; no se usa para imputar0.

## Cota futura y guardias

[Metadatos primarios](https://openrouter.ai/api/v1/models/typesafe/jev-1.13/endpoints): prompt .000000042/token, completion0; max_prompt32000, contexto64000. Se reserva contexto total: USD.002688 por intento. GET público fresco antes de cada envío; cambios/ausencias/modelo/contexto no acreditado bloquean. Provider TypeSafe único, allow_fallbacksfalse, max_price prompt.042/millón, completion/request/image0, ZDR y deny. [ProviderPreferences/max_price](https://openrouter.ai/docs/guides/routing/provider-selection) limita precio, no es una estimación de gasto; /alpha/decisions admite ProviderPreferences según [SDK primario](https://openrouter.ai/docs/client-sdks/python/sdks/decisions/README). Sin plugins, imágenes, BYOK ni herramientas remotas. Payload máximo12000bytes no se convierte a tokens. Costo real se concilia antes de validar semántica/modelo; cota excedida persiste breach. Timeout/HTTP/error de guardado no libera reserva ni dispara retry.

Inicio/vencimientoUTC persistidos en el mismo ledger operacional;48h,24intentos máximo,3600segundos de cooldown global. Reserva de muestra por hash persistente; reinicio no renueva fecha, saldo, contador ni dedup. Deadline se verifica al reservar y justo antes de enviar. Retorno de usuario antes del envío bloquea; petición en vuelo termina/conciliación, no prometer reembolso. Timeout de HTTP12s no es límite duro de tarea: GETmetadata12s + POST12s + GETfacturación en activación12s y operacionesFS/SQLite; las llamadas individuales pueden tardar más porDNS/OS. La pausa cooperativa revalida entre esas operaciones.

Activación explícita PUT /agent-improvements/scheduler action=start_pilot consulta facturación/cotización y conserva proof local antes de reservar histórico e iniciar48h. No ejecutada por B aún. Scheduler automático solo tras dos muestras aptas,180s sinactividad, sin agentes trabajando/permisos vigentes y recursos suficientes. Lee hasta10turnos; solo recuentos, booleanos y hashes de contexto/evidencia salen. Fuente de perfil desconocida explícita. No se envían prompts/resultados/IDs/modelos crudos. Estado turno=termino habilita leer métricas; no cierra ni acepta tarea.

## Calidad y ensayos

Respuesta es hipótesis con probabilidades y costo observado; evidencia en conocimiento.sqlite sin confirmar beliefs. Etiquetas independientes todavía ausentes: no medir acierto/calibración ni beneficio con confianza del modelo. P01-P06/P09-P11 de revisiónA incorporados parcialmente en guardias; P07/P08/P12 y cuatro perfiles00/10/01/11 requieren oráculos/etiquetas y ensayos reales independientes. No se sustituyen con pruebas de contrato RTK ni mutaciones viejas51cd1d4.

Config nueva pruebas-agenticas/piloto48h.json conserva baseline previo. Falta aceptación humana del nuevo baseline/casos y medición de mutaciones de este código. UI/backend nuevo pendiente de activación coordinada. No declarar PASS integral ni marcar tareas completadas.

## Activación de ledger y llamada real, 15:06:32 Argentina

El ledger fue activado explícitamente por CLI (sin restart), reemplazando el estado pendiente descrito arriba. Inicio2026-10-12T18:06:32.617681UTC, vencimiento2026-10-14T18:06:32.617681UTC (15:06Argentina),24intentos/3600s. Una llamada sobre métricas reales de sesiónB/proyectoLienzo, fuente manifest del código, perfil unknown. Snapshot2d463c3d9ba97667ab10237c70ccc4e637f806c89000cb93de0cf7d59aff7d9b. Jev eligió datos_insuficientes con .83; RTK.05/Caveman.09/ninguna.03. Modelo esperado jev-1.13-20260917; generation gen-dec-1791828390-WSB3nA2o2AaP3PmDDrrv. Usage1178entrada/59salida/costoUSD.000049476, inferior a reserva.002688000. Es una observación sin etiqueta, no demuestra acierto.

Memoria existente: evidencia6090b52da3a44f5eb9e1cb4325ef4058, requiere_veredicto. Artefacto privado ~/.lienzo/improvements/pilot-<snapshot>.json contiene métricas anonimizadas/hashes, respuesta/usage/costo, sin prompts/resultados. Saldo real leído después: confirmadoUSD.000072156 (incluye anterior), reserva históricaUSD.037418892, disponibleUSD1.962508952,1intento. Ningún gasto/confirmación0inventado. Backend antiguo no reconoce estados nuevos del ledger: activación final/restart pertenece a coordinación; no se ejecutó por B.

Corrección de pausa: staged significa persistido reservado-no-enviado. Solo el flujo que aún no marcó envío puede cancelar explícitamente staged y conservar rastro cancelled_unsent, liberando reserva sin inventar costo. Devuelve contador/cooldown/dedup porque no hubo POST. mark_sent persiste held inmediatamente antes de POST; desde allí error/timeout/reinicio/incierto retiene saldo. Un staged abandonado tras crash también bloquea hasta revisión, sin auto-liberar. Tests prueban cero POST ante regreso de usuario después de reserve, reanudación de misma muestra y rechazo de liberar held tras timeout. Latencia de cancelación cooperativa sujeta a operaciones antes descritas, sin garantía dura DNS/FS/OS.

## Backend activado por coordinación

El 12/10 a las 15:12 Argentina se reinició únicamente el servidor. Health respondió OK y GET scheduler leyó el ledger nuevo sin 503: enabled=true, pilot_enabled=true, attempts=1, blocked=false, los mismos importes y vencimiento. paid_enabled=false: hay agentes trabajando o permisos pendientes; cotización pendiente/expirada exige preflight fresco. No se forzó quietud ni se repitió la llamada. Las sesiones CLI y sus tareas se conservaron.

Revisión final de coordinación: se contrastaron los cambios con los logs de 94 tests backend y 6 recorridos UI (API simulada), los cinco roles registrados y la llamada real. Sin bloqueantes de código observados en el alcance revisado. El nuevo baseline/propuestas no se aceptan automáticamente para publicar; mutaciones del código anterior no certifican esta versión. La compuerta y la evaluación de calidad permanecen pendientes, con sus artefactos preservados. La publicación permite observar el piloto, no declara PASS integral ni aprendizaje demostrado.
