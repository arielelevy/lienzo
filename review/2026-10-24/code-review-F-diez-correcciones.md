# Revisión de las diez correcciones E/F

Alcance: `revision-F-hallazgos.md`, en su orden. Sin commit ni reinicio.
Revisión estática secuencial con el skill code-review, sobre código y pruebas modificadas.

## Cambios revisados

1. `preguntas.es_trabajo`: una omisión del auto-aprobar no autoriza una consulta.
   Confianza, cambio de modelo y permisos quedan humanos. Los diálogos ambiguos también.
2. `preguntas.bucle` corre en su propio hilo, iniciado en `server.main`.
   `scan_pending_once` no llama consultas. Las excepciones se registran por tarjeta.
3. `limpiar`, `actualizar_pregunta` y la limpieza de vista eliminan avisos antiguos al cerrar
   o cambiar una pregunta, incluso sin ★. Un fallo de lectura no borra la deduplicación durable.
4. La comparación adicional de pregunta en `_dialogo_en_pantalla` se limita al lector CODA,
   normalizando espacios. El flujo de trabajo de `/responder` conserva su revalidación específica.
5. La lectura tiene una espera de cinco segundos por fuente, incluso si no hay diálogo parseable.
   Un cambio real de fuente permite leer inmediatamente.
6. Las operaciones reservan la sesión bajo `state.lock`, trabajan sobre copia y hacen I/O fuera
   del lock. Publican sólo si siguen vigentes tarjeta, turno y pregunta. Las llamadas concurrentes
   no duplican el envío. La reserva durable se escribe antes del transporte, verificando también
   que el objeto de tarjeta reservado siga siendo el mismo, no sólo sus campos.
7. `_reservar_recordatorio` usa `save(strict=True)` y revierte su marca ante error. El error
   se captura por informe, se publica el estado y se continúa con los demás.
8. El cliente transmite `from: YO`. El servidor registra ese actor, su título o su id corto.
   Sin identidad explícita registra `tablero`; no atribuye la respuesta a la ★ consultada.
9. Los no-200 y las excepciones de transporte quedan con espera creciente 15/30/60 segundos,
   y tope de cuatro intentos. Una sucesora conocida, viva, ★ del mismo repo, recibe el reintento.
10. La identidad incluye pregunta y opciones normalizadas, además de sesión/hora. `hora=None`
    no colisiona con otra pregunta y la reenvoltura no crea otra entrega.

## Verificación revisada

Cada hallazgo tuvo una prueba roja antes del cambio y luego verde. Los casos nuevos están
en `tests/test_revision_F.py`. Se preservó el contrato de las pruebas existentes; la prueba E
de disco ahora verifica que no se envía, en vez de exigir que se aborte el barrido entero.

Se revisaron además: concurrencia real con eventos/hilos, cambio durante I/O, continuidad
por tarjeta, llamada cliente → HTTP → `/responder` con actor explícito y cierre del servidor
efímero de prueba. El test HTTP alinea su registro con el servidor importado; no introduce
alias de módulos ni modificaciones de compatibilidad en producción.

El caso adicional de reemplazo de tarjeta durante lectura falló antes de asociar la reserva
al objeto original. Se descartó la ejecución global parcial y se prepara una corrida completa
nueva sobre la versión corregida; sus resultados no se mezclan.

Ruff se limita a los archivos Python de esta corrección. No se cambiaron dependencias,
permisos, hooks de desarrollo, baselines ni aprobaciones. No se tocó el servidor vivo.

No quedan hallazgos funcionales conocidos de los diez sin corregir en esta revisión.
El resultado de la suite completa y sus límites se conserva en el informe de ejecución:
`.temp/coordinacion/2026-10-24/informe-F-diez-correcciones.md` y `F-revision/resultados/`.

La revisión no declara PASS de la compuerta ni medición de mutación. Esos veredictos
dependen de los artefactos reales del runner y de las aprobaciones vigentes.
