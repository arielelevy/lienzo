# Comparación propuesta OFF/ON

Estado: diseño; cero agentes o experimentos pagos lanzados en esta ronda. El scheduler actual solo analiza incidentes locales. No demuestra beneficio de Caveman/RTK. Ariel autorizó USD 5 totales para todo a las 13:10; fuente y bloqueo solicitado por coordinación en budget-authorization.md.

## Inventario observado, 2026-10-12

Windows: Codex, Claude, Pi, coda y Kiro presentes. Cinco sesiones observadas de Codex 0.162.1/gpt-6.1-sol en PC 75727ff74069; ventanas parciales de hasta diez turnos, tres truncadas. Consumo reportado acumulado: no sumarlo. No son baselines OFF.
WSL Ubuntu: Codex y Pi presentes; Claude, coda y RTK ausentes. Kiro sin inyección de mejoras demostrada. No extrapolar Windows a WSL. Brief: 372 caracteres; ambos: 886, no tokens.

## Piloto que requiere autorización presupuestaria

Codex Windows primero: dos tareas reales × cuatro perfiles = ocho ejecuciones. Replicación posterior duplica a dieciséis; no habilitada. Perfiles brief/RTK: 00,10,01,11 para distinguir efectos e interacción.

1. Trazar routing de juicio, propietario, snapshot y permisos; sin modificar código. Oráculo: referencias correctas a rutas, condición de muestra cambiada y autorización de costo; evaluación humana independiente del largo de respuesta.
2. Reparar contrato options→criteria o resultado ausente→desconocido en una copia privada congelada. Oráculo: pruebas de contrato existentes, negativos y revisión de alcance, sin llamada real a Jev.

Antes de correr: congelar archivos/hash (HEAD actual tiene cambios A/B), tarea, inputs, tests/oráculo, agente/modelo/versión/esfuerzo, OS/shell, versiones RTK, permisos y instrucciones del proyecto. Copias aisladas por ejecución; excluir secretos/.git/adjuntos y no alterar árbol compartido. Sesión nueva por perfil, orden balanceado e intercalado, condiciones de caché registradas. No reutilizar historiales como control. Ante divergencia de archivos/harness/contexto, invalidar comparación.

Retener logs originales antes de RTK, códigos, recuperación de diagnósticos; contrastar información necesaria, no igualdad textual tras compresión. Incluir fallas/timeouts y esperas de permisos. Métricas: oráculo/calidad primero, herramientas con resultado conocido/ausente, errores y reintentos separados, tiempo monotónico de inicio/ejecución/esperas, tokens por llamada o delta fiable. Costo desconocido = null; salida en caracteres no prueba ahorro facturado. Sobrecarga de instrucciones incluida.

No afirmar mejora por salida más corta o muestra sintética. Con n pequeño informar cada resultado y pendientes, sin estimaciones generales. Conservación de errores/seguridad/calidad es condición previa a proponer perfil futuro. Rollback vuelve al perfil anterior solo en lanzamientos nuevos.

## Política futura de ejecución

Presupuesto explícito por proyecto/PC/agente/modelo: máximo ejecuciones, duración, cuota de tokens y USD. Reserva previa conservadora y conciliación observable; costo incierto mantiene reserva y requiere revisión. Sin límite verificable por adaptador, no hay lanzamiento automático. Actividad pausa solo en límites cooperativos soportados; nunca matar una CLI ajena ni prometer detener una llamada ya enviada. Jev manual no autoriza llamadas de fondo.

Análisis local actual: USD 0 de servicios externos, sin agentes nuevos. Precio de ocho ejecuciones CLI: desconocido hasta fijar modelo/cuenta/cuotas y presupuesto; permanecen bloqueadas. Memoria conserva hipótesis propuestas, evidencia, contexto y vencimiento; la persona/coordinación emite el veredicto mediante flujo existente. Sin autoaceptación de baselines ni bucles de experimentación.
